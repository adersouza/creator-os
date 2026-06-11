import { logger } from "./logger.js";

export const MAX_RETRIES = 3;
export const API_MAX_RETRIES = 5;

interface RetryOptions {
	maxRetries?: number | undefined;
	baseDelayMs?: number | undefined;
	maxDelayMs?: number | undefined;
	shouldRetry?: (error: unknown) => boolean | undefined;
	/** Legacy support */
	label?: string | undefined;
}

/**
 * Legacy: Check if we should retry based on attempt count.
 */
export function shouldRetry(
	attempt: number,
	max: number = MAX_RETRIES,
): boolean {
	return attempt < max;
}

/**
 * Legacy: Calculate exponential backoff. Returns a Date object.
 */
export function calculateBackoff(
	attempt: number,
	baseDelay: number = 1000,
): Date {
	const baseDelay2 = Math.min(baseDelay * 2 ** attempt, 30000);
	const jitter = Math.floor(Math.random() * baseDelay2 * 0.25);
	const delay = baseDelay2 + jitter;
	return new Date(Date.now() + delay);
}

/**
 * Legacy: Check if a Meta/Threads error is retryable.
 */
export function isRetryableMetaError(
	status: number | unknown,
	error?: unknown,
): boolean {
	const statusAsRecord = status as Record<string, unknown>;
	const actualStatus =
		typeof status === "number"
			? status
			: (statusAsRecord?.status as number) || 0;
	const actualError = typeof status === "number" ? error : status;

	const actualErrorObj = actualError as Record<string, unknown>;
	const actualErrorNested =
		(actualErrorObj?.error as Record<string, unknown>) ?? {};
	const code = actualErrorNested?.code ?? actualErrorObj?.code;
	const subcode =
		actualErrorNested?.error_subcode ?? actualErrorObj?.error_subcode;

	// 429, 500, or specific transient subcodes
	return (
		actualStatus === 429 ||
		actualStatus >= 500 ||
		[2207026, 2207051].includes(subcode as number) ||
		code === 341 ||
		code === 429 ||
		(typeof code === "number" && code >= 500)
	);
}

/**
 * Parse Retry-After header from a Meta API error response.
 * Returns delay in milliseconds, or 0 if not present.
 */
function parseRetryAfter(error: unknown): number {
	const err = error as Record<string, unknown>;
	const errHeaders = err?.headers as Record<string, unknown> | undefined;
	const errResponse = err?.response as Record<string, unknown> | undefined;
	const errResponseHeaders = errResponse?.headers as
		| Record<string, unknown>
		| undefined;
	const retryAfter =
		(errHeaders?.get as ((k: string) => unknown) | undefined)?.(
			"retry-after",
		) ??
		errHeaders?.["retry-after"] ??
		(errResponseHeaders?.get as ((k: string) => unknown) | undefined)?.(
			"retry-after",
		) ??
		errResponseHeaders?.["retry-after"];

	if (!retryAfter) return 0;

	// Retry-After can be seconds (integer) or an HTTP date
	const seconds = Number(retryAfter);
	if (!Number.isNaN(seconds) && seconds > 0) {
		return Math.min(seconds * 1000, 600_000); // Cap at 10 minutes
	}

	// Try parsing as HTTP date
	const date = new Date(retryAfter as string);
	if (!Number.isNaN(date.getTime())) {
		return Math.min(Math.max(date.getTime() - Date.now(), 0), 600_000);
	}

	return 0;
}

class RetryableHttpResponseError extends Error {
	status: number;
	headers: Headers;

	constructor(response: Response) {
		super(`HTTP ${response.status}`);
		this.name = "RetryableHttpResponseError";
		this.status = response.status;
		this.headers = response.headers;
	}
}

/**
 * Standardized exponential backoff retry utility for API calls.
 * Respects Retry-After headers from Meta/external APIs.
 */
export async function withRetry<T>(
	fn: () => Promise<T>,
	options: RetryOptions = {},
): Promise<T> {
	const {
		maxRetries = 3,
		baseDelayMs = 500,
		maxDelayMs = 5000,
		shouldRetry = (err: unknown) => {
			const e = err as Record<string, unknown>;
			const status = e?.status ?? e?.code;
			return (
				!status ||
				status === 429 ||
				(typeof status === "number" && status >= 500)
			);
		},
	} = options;

	let lastError: unknown;

	for (let attempt = 0; attempt <= maxRetries; attempt++) {
		try {
			const result = await fn();
			if (result instanceof Response && isRetryableMetaError(result.status)) {
				throw new RetryableHttpResponseError(result);
			}
			return result;
		} catch (error: unknown) {
			lastError = error;

			if (attempt === maxRetries || !shouldRetry(error)) {
				throw error;
			}

			// Prefer Retry-After header from API response over computed backoff
			const retryAfterMs = parseRetryAfter(error);
			const computedWait = Math.min(baseDelayMs * 2 ** attempt, maxDelayMs);
			const jitter = Math.floor(Math.random() * computedWait * 0.25);
			const delay =
				retryAfterMs > 0 ? retryAfterMs + jitter : computedWait + jitter;

			logger.warn(
				`[Retry] Attempt ${attempt + 1} failed. Retrying in ${delay}ms...`,
				{
					error: (error as Error).message || String(error),
					retryAfterMs: retryAfterMs || undefined,
				},
			);

			await new Promise((resolve) => setTimeout(resolve, delay));
		}
	}

	throw lastError;
}

/**
 * Detect DEFINITIVE OAuth/token errors from Meta API responses.
 * Returns true only for confirmed token revocations — NOT for transient API errors.
 *
 * "An unknown/unexpected error" is Meta's generic 500 — NOT a dead token.
 * "Container expired" is a media processing timeout — NOT a token issue.
 *
 * Canonical check — all publish paths must use this single function.
 */
export function isDefinitiveOAuthError(error: string): boolean {
	const lower = error.toLowerCase();
	// Exclude transient Meta errors (generic 500s)
	if (lower.includes("unknown error") || lower.includes("unexpected error"))
		return false;
	// Exclude container/media expiry (not token-related)
	if (lower.includes("container expired") || lower.includes("upload container"))
		return false;
	return (
		lower.includes("oauthexception") ||
		lower.includes("invalid oauth") ||
		lower.includes("expired") ||
		lower.includes("error validating access token") ||
		lower.includes("access token could not be decrypted") ||
		lower.includes("session has been invalidated") ||
		lower.includes("token verification failed") ||
		lower.includes("code 190")
	);
}

/**
 * Classify a webhook processing error as permanent or transient.
 *
 * Permanent: the same payload will always produce the same failure —
 * retrying wastes cycles and delays DLQ visibility.
 * Transient: network/service hiccup — retrying may succeed.
 *
 * Conservative by design: only classifies as permanent when certain.
 * Unknown/ambiguous errors default to transient so events are not
 * dropped prematurely due to a misclassification.
 */
export function classifyWebhookError(err: unknown): "permanent" | "transient" {
	const msg = (err instanceof Error ? err.message : String(err)).toLowerCase();
	const isPermanent =
		msg.includes("invalid json") ||
		msg.includes("unexpected token") ||
		msg.includes("missing required field") ||
		msg.includes("payload exceeds size limit");
	return isPermanent ? "permanent" : "transient";
}

/**
 * Detect transient Threads container errors — Meta returns "UNKNOWN" or vague
 * messages for temporary video processing failures. Re-creating the container
 * often works.
 */
export function isTransientContainerError(errorMsg: string): boolean {
	const msg = errorMsg.toLowerCase();
	return (
		msg === "unknown" ||
		msg === "container processing failed" ||
		msg.includes("unknown error")
	);
}

// ============================================================================
// Shared Threads Container Polling
// ============================================================================

export interface ContainerPollResult {
	ready: boolean;
	error?: string | undefined;
	/** true = transient error, caller should retry with a new container */
	transient?: boolean | undefined;
}

/**
 * Poll a Threads container until FINISHED/PUBLISHED, ERROR, or EXPIRED.
 * Shared by threadsApi.ts (user-initiated publish) and publisher.ts (auto-post).
 */
export async function pollContainerStatus(opts: {
	creationId: string;
	token: string;
	maxAttempts: number;
	delayMs: number;
	firstDelayMs: number;
	containerAttempt: number;
	maxContainerRetries: number;
}): Promise<ContainerPollResult> {
	for (
		let statusAttempt = 0;
		statusAttempt < opts.maxAttempts;
		statusAttempt++
	) {
		await new Promise((resolve) =>
			setTimeout(
				resolve,
				statusAttempt === 0 ? opts.firstDelayMs : opts.delayMs,
			),
		);
		try {
			const statusRes = await fetch(
				`https://graph.threads.net/v1.0/${opts.creationId}?fields=status,error_message`,
				{
					headers: { Authorization: `Bearer ${opts.token}` },
					signal: AbortSignal.timeout(8000),
				},
			);
			const statusData = await statusRes.json();
			const status = statusData.status;

			if (status === "FINISHED" || status === "PUBLISHED") {
				return { ready: true };
			}
			if (status === "ERROR") {
				const errorMsg =
					statusData.error_message || "Container processing failed";
				if (
					isTransientContainerError(errorMsg) &&
					opts.containerAttempt < opts.maxContainerRetries
				) {
					logger.warn("Transient container error, will re-create", {
						creationId: opts.creationId,
						errorMsg,
						attempt: opts.containerAttempt,
					});
					return { ready: false, transient: true, error: errorMsg };
				}
				logger.error("Container entered ERROR state", {
					creationId: opts.creationId,
					errorMsg,
				});
				return { ready: false, error: `Media processing failed: ${errorMsg}` };
			}
			if (status === "EXPIRED") {
				logger.error("Container expired", { creationId: opts.creationId });
				return {
					ready: false,
					error: "Upload container expired. Please try again.",
				};
			}
			logger.info("Container still processing", {
				creationId: opts.creationId,
				status,
				attempt: statusAttempt,
				maxAttempts: opts.maxAttempts,
			});
		} catch {
			// Status check failed — proceed to publish attempt anyway
			break;
		}
	}
	// Timed out or status check failed — optimistically continue to publish
	return { ready: true };
}
