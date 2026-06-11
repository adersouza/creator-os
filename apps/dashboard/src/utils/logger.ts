/**
 * Frontend logger — wraps console.* with environment check.
 * In production builds, only warnings and errors are logged.
 * Debug/info output is suppressed to reduce console noise.
 */

import { addBreadcrumb, captureException, captureMessage } from '@/lib/sentry';

const isDev = import.meta.env.DEV;
const DEDUPE_WINDOW_MS = 60_000;
const recentCaptures = new Map<string, number>();

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function findError(args: unknown[]): Error | null {
  for (const arg of args) {
    if (arg instanceof Error) return arg;
    if (isRecord(arg) && arg.error instanceof Error) return arg.error;
  }
  return null;
}

function toMessage(args: unknown[]): string {
  const first = args[0];
  if (typeof first === 'string') return first;
  if (first instanceof Error) return first.message;
  return String(first ?? 'Logged error');
}

function toExtra(args: unknown[]): Record<string, unknown> | undefined {
  if (args.length <= 1) return undefined;
  const [, ...rest] = args;
  if (rest.length === 1 && isRecord(rest[0])) return rest[0];
  return { args: rest };
}

function stableSerialize(value: unknown, depth = 0, seen = new WeakSet<object>()): string {
  if (depth > 4) return '"[truncated]"';
  if (typeof value === 'bigint') return JSON.stringify(value.toString());
  if (typeof value === 'function') return '"[function]"';
  if (typeof value === 'symbol') return JSON.stringify(value.toString());
  if (typeof value === 'undefined') return '"[undefined]"';
  if (value instanceof Error) {
    return JSON.stringify({ name: value.name, message: value.message });
  }
  if (Array.isArray(value)) {
    if (seen.has(value)) return '"[circular]"';
    seen.add(value);
    return `[${value.map((item) => stableSerialize(item, depth + 1, seen)).join(',')}]`;
  }
  if (isRecord(value)) {
    if (seen.has(value)) return '"[circular]"';
    seen.add(value);
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableSerialize(value[key], depth + 1, seen)}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

function shouldCapture(kind: 'error' | 'warning', message: string, extra?: Record<string, unknown>): boolean {
  const key = `${kind}:${message}:${stableSerialize(extra ?? {})}`;
  const now = Date.now();
  for (const [existingKey, capturedAt] of recentCaptures) {
    if (now - capturedAt > DEDUPE_WINDOW_MS) recentCaptures.delete(existingKey);
  }
  const last = recentCaptures.get(key);
  if (last && now - last < DEDUPE_WINDOW_MS) return false;
  recentCaptures.set(key, now);
  return true;
}

function captureLoggedError(args: unknown[]): void {
  if (isDev) return;
  const message = toMessage(args);
  const error = findError(args) ?? new Error(message);
  const extra = toExtra(args);
  if (!shouldCapture('error', message, extra)) return;

  try {
    captureException(error, { logger: { message } }, extra);
  } catch {
    // Sentry failure must not recurse through logger.error.
  }
}

function captureLoggedWarning(args: unknown[]): void {
  if (isDev) return;
  const message = toMessage(args);
  const extra = toExtra(args);
  if (!shouldCapture('warning', message, extra)) return;

  try {
    captureMessage(message, { level: 'warning', extra });
  } catch {
    // Sentry failure must not recurse through logger.warn.
  }
}

function breadcrumb(level: 'debug' | 'info' | 'log', args: unknown[]): void {
  if (isDev) return;
  try {
    addBreadcrumb({
      category: 'logger',
      level,
      message: toMessage(args),
      data: toExtra(args),
    });
  } catch {
    // Breadcrumb failures are non-critical.
  }
}

export const logger = {
  debug: (...args: unknown[]) => {
    // biome-ignore lint/suspicious/noConsole: intentional logging utility
    if (isDev) console.log('[DEBUG]', ...args);
    breadcrumb('debug', args);
  },
  log: (...args: unknown[]) => {
    // biome-ignore lint/suspicious/noConsole: intentional logging utility
    if (isDev) console.log(...args);
    breadcrumb('log', args);
  },
  info: (...args: unknown[]) => {
    // biome-ignore lint/suspicious/noConsole: intentional logging utility
    if (isDev) console.log('[INFO]', ...args);
    breadcrumb('info', args);
  },
  warn: (...args: unknown[]) => {
    // biome-ignore lint/suspicious/noConsole: intentional logging utility
    console.warn(...args);
    captureLoggedWarning(args);
  },
  error: (...args: unknown[]) => {
    // biome-ignore lint/suspicious/noConsole: intentional logging utility
    console.error(...args);
    captureLoggedError(args);
  },
};

export default logger;
