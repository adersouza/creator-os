/**
 * Structured Logger
 *
 * Outputs JSON-structured log entries with automatic sensitive data scrubbing.
 * All log output goes through console.log/warn/error for Vercel log ingestion.
 */

// DEP0169 (url.parse) suppressed via NODE_OPTIONS=--disable-warning=DEP0169 in vercel.json

type LogLevel = "debug" | "info" | "warn" | "error";

interface LogContext {
	[key: string]: unknown;
}

const SENSITIVE_KEYS = [
	"token",
	"secret",
	"key",
	"password",
	"authorization",
	"encrypted",
];

const PII_KEYS = new Set([
	"email",
	"recipient",
	"recipients",
	"phone",
	"address",
	"ip",
]);

const USER_CONTENT_KEYS = new Set([
	"body",
	"caption",
	"captions",
	"content",
	"message",
	"payload",
	"prompt",
	"response",
	"sample_captions",
	"text",
]);

// Patterns that indicate token-like values (redact in string values, not just keys)
const TOKEN_VALUE_PATTERNS = [
	/^juno_ak_/, // API key prefix
	/^Bearer\s+\S/, // Bearer token in string values
	/^sha256=[0-9a-f]{40,}/i, // HMAC signatures
];

const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;

// Long base64 strings (>40 chars) that look like tokens/secrets
const LONG_BASE64_RE = /^[A-Za-z0-9+/=_-]{40,}$/;

function looksLikeToken(value: string): boolean {
	if (TOKEN_VALUE_PATTERNS.some((p) => p.test(value))) return true;
	if (value.length >= 40 && LONG_BASE64_RE.test(value)) return true;
	return false;
}

function redactString(value: string): string {
	return value
		.replace(EMAIL_RE, "[EMAIL_REDACTED]")
		.replace(/access_token=[^\s&]+/gi, "access_token=[REDACTED]")
		.replace(/refresh_token=[^\s&]+/gi, "refresh_token=[REDACTED]")
		.replace(/Bearer\s+[A-Za-z0-9._-]+/g, "Bearer [REDACTED]");
}

export function summarizeUserContent(value: unknown): Record<string, unknown> {
	const seen = new WeakSet<object>();
	let maxDepth = 0;

	function walk(node: unknown, depth: number): void {
		maxDepth = Math.max(maxDepth, depth);
		if (!node || typeof node !== "object") return;
		if (seen.has(node)) return;
		seen.add(node);
		if (depth >= 6) return;
		for (const child of Array.isArray(node)
			? node
			: Object.values(node as Record<string, unknown>)) {
			walk(child, depth + 1);
		}
	}

	walk(value, 0);

	const topLevelKeys =
		value && typeof value === "object" && !Array.isArray(value)
			? Object.keys(value as Record<string, unknown>).sort()
			: [];
	const byteSize = (() => {
		try {
			return Buffer.byteLength(JSON.stringify(value));
		} catch {
			return 0;
		}
	})();
	const source =
		value && typeof value === "object" && !Array.isArray(value)
			? (value as Record<string, unknown>)
			: {};

	return {
		redacted: true,
		type: Array.isArray(value) ? "array" : typeof value,
		topLevelKeys,
		depth: maxDepth,
		byteSize,
		hasField: {
			entry: Object.hasOwn(source, "entry"),
			object: Object.hasOwn(source, "object"),
			values: Object.hasOwn(source, "values"),
			changes: Object.hasOwn(source, "changes"),
			messaging: Object.hasOwn(source, "messaging"),
		},
	};
}

/**
 * Serialize an error value into a loggable string.
 * Handles Error objects (extracts .message), plain strings, and everything else.
 * Exported so callers can use it in non-logger contexts (e.g. apiError messages).
 */
export function errMsg(err: unknown): string {
	if (err instanceof Error) return err.message;
	if (typeof err === "string") return err;
	try {
		return JSON.stringify(err);
	} catch {
		return String(err);
	}
}

export function scrubSensitive(obj: Record<string, unknown>): Record<string, unknown> {
	const scrubbed: Record<string, unknown> = {};
	for (const [k, v] of Object.entries(obj)) {
		const key = k.toLowerCase();
		if (SENSITIVE_KEYS.some((s) => key.includes(s))) {
			scrubbed[k] = "[REDACTED]";
		} else if (PII_KEYS.has(key)) {
			scrubbed[k] = "[REDACTED]";
		} else if (USER_CONTENT_KEYS.has(key)) {
			scrubbed[k] = summarizeUserContent(v);
		} else if (typeof v === "string" && looksLikeToken(v)) {
			scrubbed[k] = "[REDACTED]";
		} else if (typeof v === "string") {
			scrubbed[k] = redactString(v);
		} else if (Array.isArray(v)) {
			scrubbed[k] = v.map((item) =>
				item && typeof item === "object" && !Array.isArray(item)
					? scrubSensitive(item as Record<string, unknown>)
					: typeof item === "string"
						? redactString(item)
						: item,
			);
		} else if (v instanceof Error) {
			// Auto-serialize Error objects — prevents "[object Object]" from String(err)
			scrubbed[k] = redactString(v.message);
		} else if (typeof v === "object" && v !== null && !Array.isArray(v)) {
			scrubbed[k] = scrubSensitive(v as Record<string, unknown>);
		} else {
			scrubbed[k] = v;
		}
	}
	return scrubbed;
}

function log(level: LogLevel, message: string, context?: LogContext) {
	const entry = {
		level,
		message,
		timestamp: new Date().toISOString(),
		...(context ? scrubSensitive(context) : {}),
	};

	// biome-ignore lint/suspicious/noConsole: logger is the designated console wrapper
	if (level === "error") console.error(JSON.stringify(entry));
	// biome-ignore lint/suspicious/noConsole: logger is the designated console wrapper
	else if (level === "warn") console.warn(JSON.stringify(entry));
	// biome-ignore lint/suspicious/noConsole: logger is the designated console wrapper
	else console.log(JSON.stringify(entry));
}

export const logger = {
	debug: (msg: string, ctx?: LogContext) => log("debug", msg, ctx),
	info: (msg: string, ctx?: LogContext) => log("info", msg, ctx),
	warn: (msg: string, ctx?: LogContext) => log("warn", msg, ctx),
	error: (msg: string, ctx?: LogContext) => log("error", msg, ctx),
};

/**
 * Create a logger instance pre-bound with request context (requestId, traceId).
 * Every log call automatically includes the bound context for correlation.
 */
export function createRequestLogger(context: {
	requestId?: string | undefined;
	traceId?: string | undefined;
}) {
	return {
		debug: (msg: string, ctx?: LogContext) =>
			log("debug", msg, { ...context, ...ctx }),
		info: (msg: string, ctx?: LogContext) =>
			log("info", msg, { ...context, ...ctx }),
		warn: (msg: string, ctx?: LogContext) =>
			log("warn", msg, { ...context, ...ctx }),
		error: (msg: string, ctx?: LogContext) =>
			log("error", msg, { ...context, ...ctx }),
	};
}

/**
 * Safely serialize any error value into a readable string.
 * Handles Error instances, Supabase PostgrestError plain objects
 * (which have `.message` but are NOT Error instances), and arbitrary values.
 */
export function serializeError(err: unknown): string {
	if (err instanceof Error) return err.message;
	if (typeof err === "string") return err;
	if (
		err !== null &&
		typeof err === "object" &&
		"message" in err &&
		typeof (err as { message?: unknown | undefined }).message === "string"
	) {
		return (err as { message: string }).message;
	}
	try {
		const json = JSON.stringify(err);
		// Avoid returning "{}" for objects with no enumerable props
		return json === "{}" ? String(err) : json;
	} catch {
		return String(err);
	}
}
