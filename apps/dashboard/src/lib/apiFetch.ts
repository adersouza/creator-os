import type { z, ZodType } from 'zod';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { randomUUID } from '@/lib/uuid';
import { apiUrl } from './apiUrl';
import { addBreadcrumb, captureMessage } from './sentry';
import { analytics } from './analytics';

/**
 * Runtime-validated fetch wrapper for the Juno33 /api/* backend.
 *
 * Plain `fetch` + `res.json()` assumes the backend response matches the TS
 * interface forever. When the contract drifts (added field, renamed key,
 * backend returns 502 HTML page, etc), the app silently rehydrates with
 * garbage and we find out via a Sentry stack trace in a totally unrelated
 * component. This wrapper validates at the edge so we fail fast.
 *
 * Usage:
 *   const schema = z.object({ daysRemaining: z.number() });
 *   const data = await apiFetch('/api/subscription?action=check-trial', schema, { method: 'POST' });
 *
 * Auth header is attached automatically from the current Supabase session.
 * Pass `auth: false` to skip for public endpoints.
 */
export class ApiValidationError extends Error {
  constructor(public path: string, public issues: z.ZodError, public requestId?: string | undefined) {
    super(`API response validation failed for ${path}: ${issues.message}`);
    this.name = 'ApiValidationError';
  }
}

export class ApiHttpError extends Error {
  constructor(
    public path: string,
    public status: number,
    public body: string,
    public requestId?: string | undefined,
    public retryAfter?: number | undefined,
  ) {
    super(`API ${path} returned ${status}`);
    this.name = 'ApiHttpError';
  }
}

export class ApiTimeoutError extends Error {
  constructor(public path: string, public timeoutMs: number, public requestId?: string | undefined) {
    super(`API ${path} timed out after ${timeoutMs}ms`);
    this.name = 'ApiTimeoutError';
  }
}

export class ApiNetworkError extends Error {
  constructor(public path: string, public cause: unknown, public requestId?: string | undefined) {
    super(`API ${path} network request failed`);
    this.name = 'ApiNetworkError';
  }
}

interface ApiFetchOptions extends Omit<RequestInit, 'body'> {
  /** Structured body — JSON-encoded + content-type set automatically. */
  json?: unknown | undefined;
  /** Skip attaching the Supabase access token. Default false. */
  auth?: boolean | undefined;
  /** Abort the request after this many milliseconds. Default 30s. */
  timeoutMs?: number | undefined;
}

const REQUEST_ID_HEADER = 'x-request-id';
const DEFAULT_TIMEOUT_MS = 30_000;
const SLOW_API_MS = 3_000;
const TIMEOUT_WARN_KEY = 'juno33.apiTimeoutWarnings';

export async function apiFetch<T>(
  path: string,
  schema: ZodType<T>,
  options: ApiFetchOptions = {},
): Promise<T> {
  const {
    json,
    auth = true,
    headers: extraHeaders,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    signal: callerSignal,
    ...init
  } = options;

  const headers: Record<string, string> = { ...(extraHeaders as Record<string, string> | undefined) };
  const clientRequestId = headers[REQUEST_ID_HEADER] || headers['X-Request-Id'] || randomUUID();
  headers[REQUEST_ID_HEADER] = clientRequestId;

  if (auth) {
    Object.assign(headers, await getApiAuthHeaders());
  }

  if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  const controller = new AbortController();
  let didTimeout = false;
  const timeoutId = timeoutMs > 0
    ? globalThis.setTimeout(() => {
        didTimeout = true;
        controller.abort();
      }, timeoutMs)
    : null;
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  if (callerSignal) {
    if (callerSignal.aborted) abortFromCaller();
    else callerSignal.addEventListener('abort', abortFromCaller, { once: true });
  }

  const requestInit: RequestInit = { ...init, headers, signal: controller.signal };
  const existingBody = (init as { body?: BodyInit | undefined }).body;
  if (json !== undefined) {
    requestInit.body = JSON.stringify(json);
  } else if (existingBody !== undefined) {
    requestInit.body = existingBody;
  }

  let res: Response;
  const startedAt = performance.now();
  const method = requestInit.method || 'GET';
  try {
    res = await fetch(apiUrl(path), requestInit);
  } catch (error) {
    const requestId = clientRequestId;
    const durationMs = Math.round(performance.now() - startedAt);
    recordApiBreadcrumb({
      path,
      method,
      clientRequestId,
      requestId,
      timeoutMs,
      durationMs,
      outcome: didTimeout ? 'timeout' : 'network_error',
    });
    if (didTimeout) {
      recordRepeatedTimeout(path, timeoutMs, requestId);
      throw new ApiTimeoutError(path, timeoutMs, requestId);
    }
    throw new ApiNetworkError(path, error, requestId);
  } finally {
    if (timeoutId !== null) globalThis.clearTimeout(timeoutId);
    if (callerSignal) callerSignal.removeEventListener('abort', abortFromCaller);
  }

  const responseRequestId = res.headers.get(REQUEST_ID_HEADER) || clientRequestId;
  const durationMs = Math.round(performance.now() - startedAt);
  const retryAfterHeader = res.headers.get('retry-after');
  const retryAfter = Number(retryAfterHeader);
  recordApiBreadcrumb({
    path,
    method,
    clientRequestId,
    requestId: responseRequestId,
    status: res.status,
    retryAfter: Number.isFinite(retryAfter) ? retryAfter : undefined,
    timeoutMs,
    durationMs,
    outcome: res.ok ? 'ok' : 'http_error',
  });
  if (durationMs > SLOW_API_MS) {
    analytics.capture('api_guardrail_warning', {
      type: 'slow_api',
      path,
      method,
      status: res.status,
      durationMs,
      requestId: responseRequestId,
    });
    captureMessage('Slow frontend API call', {
      level: 'warning',
      extra: { path, method, status: res.status, durationMs, requestId: responseRequestId },
    });
  }

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new ApiHttpError(
      path,
      res.status,
      body.slice(0, 500),
      responseRequestId,
      Number.isFinite(retryAfter) ? retryAfter : undefined,
    );
  }

  const raw = await res.json().catch(() => null);
  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    throw new ApiValidationError(path, parsed.error, responseRequestId);
  }
  return parsed.data;
}

function recordApiBreadcrumb(data: {
  path: string;
  method: string;
  clientRequestId: string;
  requestId: string;
  status?: number | undefined;
  retryAfter?: number | undefined;
  timeoutMs: number;
  durationMs: number;
  outcome: 'ok' | 'http_error' | 'timeout' | 'network_error';
}) {
  addBreadcrumb({
    category: 'api',
    message: `${data.method} ${data.path}`,
    level: data.outcome === 'ok' ? 'info' : 'warning',
    data,
  });
}

function recordRepeatedTimeout(path: string, timeoutMs: number, requestId: string) {
  if (typeof window === 'undefined') return;
  try {
    const now = Date.now();
    const raw = window.localStorage.getItem(TIMEOUT_WARN_KEY);
    const previous = raw ? (JSON.parse(raw) as Array<{ path: string; at: number }>) : [];
    const recent = previous.filter((item) => now - item.at < 10 * 60 * 1000);
    recent.push({ path, at: now });
    window.localStorage.setItem(TIMEOUT_WARN_KEY, JSON.stringify(recent.slice(-20)));
    const countForPath = recent.filter((item) => item.path === path).length;
    if (countForPath >= 3) {
      analytics.capture('api_guardrail_warning', {
        type: 'repeated_timeout',
        path,
        timeoutMs,
        requestId,
        count: countForPath,
      });
      captureMessage('Repeated frontend API timeouts', {
        level: 'warning',
        extra: { path, timeoutMs, requestId, count: countForPath },
      });
    }
  } catch {
    // Telemetry storage is best-effort only.
  }
}
