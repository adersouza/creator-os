import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { AsyncLocalStorage } from "async_hooks";
import { createHash, randomUUID } from "crypto";
import { recordRateLimit, recordSuccess } from "./rateLimiter.js";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export const API_BASE = process.env.TD_API_BASE ?? "https://juno33.com/api";
// TD_API_KEY (permanent key) takes priority over TD_AUTH_TOKEN (expiring JWT)
export const AUTH_TOKEN = process.env.TD_API_KEY ?? process.env.TD_AUTH_TOKEN;

// ---------------------------------------------------------------------------
// Per-request auth (concurrency-safe via AsyncLocalStorage)
// ---------------------------------------------------------------------------
// The HTTP transport serves multiple users concurrently on warm containers.
// AsyncLocalStorage isolates each request's token in its own async context
// so there's no credential bleed between concurrent calls.

const authStore = new AsyncLocalStorage<string>();

/** Returns the auth token for the current async context, falling back to env. */
export function getAuthToken(): string {
  return authStore.getStore() ?? AUTH_TOKEN ?? "";
}

/** Run `fn` with `token` as the auth token for all nested async calls. */
export function runWithAuthToken<T>(token: string, fn: () => T): T {
  return authStore.run(token, fn);
}

// Stable session ID for this MCP server process (reset on restart)
export const SESSION_ID = randomUUID();

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type HttpMethod = "GET" | "POST" | "PUT" | "DELETE" | "PATCH";

interface ApiResult<T = unknown> {
  ok: true;
  data: T;
}

interface ApiError {
  ok: false;
  error: {
    code: "forbidden" | "not_found" | "rate_limit" | "tier_required" | "invalid_input" | "timeout" | "server_error";
    message: string;
    status: number;
    retryAfterMs?: number;
    details?: unknown;
  };
}

type ApiResponse<T = unknown> = ApiResult<T> | ApiError;

type McpToolResponse = {
  content?: Array<{ type?: string; text?: string }>;
  isError?: boolean;
};

// ---------------------------------------------------------------------------
// HTTP helper
// ---------------------------------------------------------------------------

function errorCodeFromStatus(status: number): ApiError["error"]["code"] {
  if (status === 401 || status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 429) return "rate_limit";
  if (status === 402) return "tier_required";
  if (status === 400 || status === 422) return "invalid_input";
  return "server_error";
}

export async function api<T = unknown>(
  path: string,
  method: HttpMethod = "GET",
  body?: Record<string, unknown>,
  timeoutMs = 15_000
): Promise<ApiResponse<T>> {
  const url = `${API_BASE}${path}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${getAuthToken()}`,
    "Content-Type": "application/json",
    "X-Agent-Session": SESSION_ID,
  };
  if (method !== "GET" && !headers["Idempotency-Key"]) {
    headers["Idempotency-Key"] = `mcp:${SESSION_ID}:${method}:${path}:${hashStableValue(body ?? {}).slice(0, 24)}`;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err: unknown) {
    clearTimeout(timeout);
    if (err instanceof Error && err.name === "AbortError") {
      return {
        ok: false,
        error: {
          code: "timeout",
          message: `API ${method} ${path} timed out after ${timeoutMs}ms`,
          status: 408,
        },
      };
    }
    return {
      ok: false,
      error: {
        code: "server_error",
        message: err instanceof Error ? err.message : "Unknown fetch error",
        status: 0,
      },
    };
  }
  clearTimeout(timeout);

  const text = await res.text();
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    data = text;
  }

  if (!res.ok) {
    const retryAfter = res.headers.get("retry-after");
    const retryAfterMs = retryAfter ? Number(retryAfter) * 1000 : undefined;

    // Track 429s for exponential backoff
    if (res.status === 429) {
      recordRateLimit(retryAfterMs);
    }

    return {
      ok: false,
      error: {
        code: errorCodeFromStatus(res.status),
        message: typeof data === "object" && data && "error" in data
          ? String((data as Record<string, unknown>).error)
          : typeof data === "string" ? data : `HTTP ${res.status}`,
        status: res.status,
        retryAfterMs,
        details: data,
      },
    };
  }

  // Reset backoff counter on success
  recordSuccess();
  return { ok: true, data: data as T };
}

function hashStableValue(value: unknown): string {
  return createHash("sha256").update(stableStringify(value)).digest("hex");
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  return `{${Object.entries(value as Record<string, unknown>)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, child]) => `${JSON.stringify(key)}:${stableStringify(child)}`)
    .join(",")}}`;
}

// ---------------------------------------------------------------------------
// Agent action logger (fire-and-forget, never blocks tool calls)
// ---------------------------------------------------------------------------

export function logAgentAction(
  toolName: string,
  params: Record<string, unknown>,
  result: ApiResponse | McpToolResponse,
  durationMs: number,
  reason?: string,
): void {
  const sanitized = sanitizeForAgentLog(params) as Record<string, unknown>;

  const resultSummary = summarizeAgentLogResult(result);

  api("/agent/log", "POST", {
    session_id: SESSION_ID,
    tool_name: toolName,
    params_json: sanitized,
    reason: reason?.slice(0, 500),
    result_summary: resultSummary,
    success: isAgentLogSuccess(result),
    duration_ms: durationMs,
  }).catch(() => { /* non-fatal */ });
}

function sanitizeForAgentLog(value: unknown, key = ""): unknown {
  if (isSensitiveLogKey(key)) return "[redacted]";

  if (Array.isArray(value)) {
    return value.map((item) => sanitizeForAgentLog(item, key));
  }

  if (value && typeof value === "object") {
    const sanitized: Record<string, unknown> = {};
    for (const [childKey, childValue] of Object.entries(value)) {
      sanitized[childKey] = sanitizeForAgentLog(childValue, childKey);
    }
    return sanitized;
  }

  if (typeof value === "string") {
    if (value.length > 512) return `${value.slice(0, 512)}...[truncated]`;
    return value;
  }

  return value;
}

function isSensitiveLogKey(key: string): boolean {
  return /token|secret|password|api[_-]?key|authorization|webhook|credential/i.test(key);
}

function isApiResponse(result: ApiResponse | McpToolResponse): result is ApiResponse {
  return "ok" in result;
}

function isAgentLogSuccess(result: ApiResponse | McpToolResponse): boolean {
  return isApiResponse(result) ? result.ok : result.isError !== true;
}

function summarizeAgentLogResult(result: ApiResponse | McpToolResponse): string {
  if (isApiResponse(result)) {
    return result.ok
      ? "ok"
      : `error(${result.error.code}): ${result.error.message.slice(0, 120)}`;
  }

  if (result.isError) {
    const text = result.content?.find((part) => part.text)?.text ?? "Tool returned an error";
    return `error(tool_error): ${text.slice(0, 120)}`;
  }

  return "ok";
}

function toolResponseData(result: ApiResponse | McpToolResponse): unknown {
  if (isApiResponse(result)) return result.ok ? result.data : result.error.details;

  const text = result.content?.find((part) => part.text)?.text;
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function countValue(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return 0;
}

export function deriveAgentActionReason(
  toolName: string,
  params: Record<string, unknown>,
  result?: ApiResponse | McpToolResponse,
): string | undefined {
  if (toolName === "set_agent_paused") {
    return params.paused
      ? "Operator paused agent via dashboard"
      : "Operator resumed agent via dashboard";
  }

  if (toolName === "toggle_auto_post") {
    const enabled = params.enabled === true;
    const scope = Array.isArray(params.groupIds)
      ? `${params.groupIds.length} groups`
      : params.groupId
        ? "group scope"
        : `${typeof params.scope === "string" ? params.scope : "master"} scope`;
    return `Workspace autoposter ${enabled ? "enabled" : "paused"} via ${scope}`;
  }

  if (toolName === "override_account_state") {
    return typeof params.reason === "string" && params.reason.trim()
      ? params.reason.trim()
      : `Operator ${String(params.action ?? "updated")} account autoposter state`;
  }

  if (toolName === "verify_autoposter_state") {
    if (!result || !isAgentLogSuccess(result)) {
      return "Autoposter preflight failed; operator review required before changing publish state.";
    }

    const payload = asRecord(toolResponseData(result));
    const data = asRecord(payload.data ?? payload);
    const overdue = countValue(data.overdue_items_count);
    const failed = countValue(data.failed_count);
    const stuck = countValue(data.stuck_publishing_count);
    const burstAlerts = Array.isArray(data.burst_alerts) ? data.burst_alerts.length : 0;
    const issues = [
      overdue ? `${overdue} overdue queued item${overdue === 1 ? "" : "s"}` : "",
      failed ? `${failed} failed item${failed === 1 ? "" : "s"}` : "",
      stuck ? `${stuck} stuck publish${stuck === 1 ? "" : "es"}` : "",
      burstAlerts ? `${burstAlerts} burst alert${burstAlerts === 1 ? "" : "s"}` : "",
    ].filter(Boolean);

    return issues.length
      ? `Autoposter preflight found ${issues.join(", ")}.`
      : "Autoposter preflight passed; no overdue, failed, stuck, or burst publish risks found.";
  }

  return undefined;
}

// ---------------------------------------------------------------------------
// MCP response helpers
// ---------------------------------------------------------------------------

export function success(data: unknown) {
  return {
    content: [
      {
        type: "text" as const,
        text: typeof data === "string" ? data : JSON.stringify(data, null, 2),
      },
    ],
  };
}

export function error(err: ApiError["error"]) {
  const parts = [`Error (${err.code}): ${err.message}`];
  if (err.retryAfterMs) parts.push(`Retry after: ${Math.ceil(err.retryAfterMs / 1000)}s`);
  return {
    content: [
      {
        type: "text" as const,
        text: parts.join("\n"),
      },
    ],
    isError: true as const,
  };
}

export function respond(result: ApiResponse) {
  if (result.ok) return success(result.data);
  return error(result.error);
}

// ---------------------------------------------------------------------------
// Dry-run helper for destructive actions
// ---------------------------------------------------------------------------

export function dryRunResponse(description: string, payload: Record<string, unknown>) {
  return success({
    dryRun: true,
    wouldExecute: description,
    payload,
    hint: "Set dryRun to false to execute this action.",
  });
}

// ---------------------------------------------------------------------------
// Schema helpers
// ---------------------------------------------------------------------------

// MCP clients may send boolean params as strings ("false"/"true").
// This coerces them correctly — z.coerce.boolean() won't work because
// Boolean("false") === true (truthy string).
import { z } from "zod";
export const zBool = z.preprocess(
  (v) => (v === "false" ? false : v === "true" ? true : v),
  z.boolean()
);

// MCP clients send number params as strings too.
export const zNum = z.preprocess(
  (v) => (typeof v === "string" && v !== "" ? Number(v) : v),
  z.number()
);

// ---------------------------------------------------------------------------
// Shared timeout constants
// ---------------------------------------------------------------------------

/** Default timeout for AI-powered tool calls (generation, analysis, scoring). */
export const AI_TIMEOUT = 30_000;

// ---------------------------------------------------------------------------
// Tool registration type
// ---------------------------------------------------------------------------

export type ToolRegistrar = (server: McpServer) => void;
