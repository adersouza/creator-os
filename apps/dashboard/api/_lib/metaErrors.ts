/**
 * Structured Meta API Error Taxonomy
 *
 * Replaces fragile string-matching with code-based error classification.
 * Meta Graph API errors always include: code, error_subcode, type, message.
 *
 * Sources:
 * - https://developers.facebook.com/docs/graph-api/guides/error-handling/
 * - https://developers.facebook.com/docs/instagram-platform/reference/error-codes/
 */

import { logger } from "./logger.js";

// ============================================================================
// Error Categories
// ============================================================================

export type MetaErrorCategory =
	| "transient" // Retry after short delay (Meta infra issue)
	| "rate_limit" // Retry after longer delay (throttled)
	| "auth" // Token invalid/expired — needs reauth, do NOT retry
	| "permanent" // Invalid request — fix the request, do NOT retry
	| "media" // Media-specific error — wrong format, too large, etc.
	| "unknown"; // Unclassified — treat as transient (fail-open)

export interface ClassifiedError {
	category: MetaErrorCategory;
	/** Whether the request can be retried (transient + rate_limit = yes) */
	retryable: boolean;
	/** Suggested action for the system */
	action:
		| "retry"
		| "retry_with_backoff"
		| "reauth"
		| "fail"
		| "fix_media"
		| "investigate";
	/** Human-readable reason */
	reason: string;
}

// ============================================================================
// Error Code Classification
// ============================================================================

/**
 * Classify a Meta API error by its structured error codes.
 *
 * Prefer this over string-matching. Call with the parsed error object
 * from Meta's JSON response: { code, error_subcode, type, message }.
 */
export function classifyMetaError(error: {
	code?: number | undefined;
	error_subcode?: number | undefined;
	type?: string | undefined;
	message?: string | undefined;
	httpStatus?: number | undefined;
}): ClassifiedError {
	const { code, error_subcode: subcode, type, message, httpStatus } = error;

	// ── Auth errors (do NOT retry) ──
	if (code === 190) {
		return {
			category: "auth",
			retryable: false,
			action: "reauth",
			reason: `Token invalid (code 190, subcode ${subcode || "none"}): ${message?.substring(0, 100) || "expired or revoked"}`,
		};
	}

	// OAuthException with code 102 = session expired
	if (code === 102) {
		return {
			category: "auth",
			retryable: false,
			action: "reauth",
			reason: "Session expired (code 102)",
		};
	}

	// ── Rate limits ──
	if (code === 4 || code === 32 || code === 613) {
		return {
			category: "rate_limit",
			retryable: true,
			action: "retry_with_backoff",
			reason: `Rate limited (code ${code})`,
		};
	}

	// Subcode 2446079 = publishing rate limit specifically
	if (subcode === 2446079) {
		return {
			category: "rate_limit",
			retryable: true,
			action: "retry_with_backoff",
			reason: "Publishing rate limit (subcode 2446079)",
		};
	}

	// ── Transient / Server errors ──
	// Code 1: "An unknown error occurred" — Meta returns this with HTTP 400 AND
	// HTTP 500 for genuine transient failures. Do NOT treat HTTP 400 as permanent;
	// Meta's status codes are unreliable for code=1. Circuit breakers and failure
	// tracking catch truly restricted accounts.
	// Code 2: "Service temporarily unavailable" — always Meta infra issue.
	if (code === 1 || code === 2) {
		return {
			category: "transient",
			retryable: true,
			action: "retry",
			reason: `Meta transient error (code ${code}, HTTP ${httpStatus ?? "unknown"}): ${message?.substring(0, 100) || "unknown"}`,
		};
	}

	// ── Permanent errors ──
	// Code 100: Invalid parameter (wrong media format, missing field, etc.)
	if (code === 100) {
		// Subcode 33: Object does not exist (e.g., expired story)
		if (subcode === 33) {
			return {
				category: "permanent",
				retryable: false,
				action: "fail",
				reason: "Object does not exist (expired or deleted)",
			};
		}
		// Subcode 2207026: Media upload error
		if (subcode === 2207026) {
			return {
				category: "media",
				retryable: false,
				action: "fix_media",
				reason: "Media upload error — wrong format or corrupted file",
			};
		}
		return {
			category: "permanent",
			retryable: false,
			action: "fail",
			reason: `Invalid parameter (code 100, subcode ${subcode || "none"}): ${message?.substring(0, 100) || "unknown"}`,
		};
	}

	// Code 10: Permission denied
	if (code === 10) {
		return {
			category: "permanent",
			retryable: false,
			action: "fail",
			reason: "Permission denied (code 10) — missing required scope",
		};
	}

	// Code 24: Not existing object — deleted or expired
	if (code === 24) {
		return {
			category: "permanent",
			retryable: false,
			action: "fail",
			reason: "Object deleted or expired (code 24)",
		};
	}

	// ── Media-specific errors ──
	// Code 36003: Media type not supported
	if (code === 36003) {
		return {
			category: "media",
			retryable: false,
			action: "fix_media",
			reason: "Media type not supported (code 36003)",
		};
	}

	// ── Type-based fallback (if code didn't match) ──
	if (type === "OAuthException") {
		// OAuthException without recognized code — check message for clues
		const lower = (message || "").toLowerCase();
		if (lower.includes("unknown error") || lower.includes("unexpected error")) {
			// Meta's transient 500 disguised as OAuthException
			return {
				category: "transient",
				retryable: true,
				action: "retry",
				reason: `Meta transient OAuthException: ${message?.substring(0, 100)}`,
			};
		}
		// Real OAuth issue
		return {
			category: "auth",
			retryable: false,
			action: "reauth",
			reason: `OAuthException: ${message?.substring(0, 100) || "unknown"}`,
		};
	}

	// ── Fallback: string matching for unstructured errors ──
	if (message) {
		const lower = message.toLowerCase();
		if (lower.includes("rate limit") || lower.includes("too many")) {
			return {
				category: "rate_limit",
				retryable: true,
				action: "retry_with_backoff",
				reason: `Rate limit (message): ${message.substring(0, 100)}`,
			};
		}
		if (
			lower.includes("timeout") ||
			lower.includes("etimedout") ||
			lower.includes("econnreset")
		) {
			return {
				category: "transient",
				retryable: true,
				action: "retry",
				reason: `Network error: ${message.substring(0, 100)}`,
			};
		}
	}

	// Unknown — log for investigation, treat as transient (fail-open)
	logger.warn(
		"[metaErrors] Unclassified Meta error — defaulting to transient",
		{
			code,
			subcode,
			type,
			message: message?.substring(0, 200),
		},
	);

	return {
		category: "unknown",
		retryable: true,
		action: "investigate",
		reason: `Unclassified (code ${code || "none"}, type ${type || "none"}): ${message?.substring(0, 100) || "no message"}`,
	};
}

// ============================================================================
// Convenience helpers (drop-in replacements for string-matching functions)
// ============================================================================

/**
 * Check if a Meta error is transient (safe to retry).
 * Drop-in replacement for string-based isTransientError().
 * Accepts either a structured error object or a plain error message string.
 */
export function isTransientMetaError(
	error:
		| string
		| {
				code?: number | undefined;
				error_subcode?: number | undefined;
				type?: string | undefined;
				message?: string | undefined;
		  },
): boolean {
	if (typeof error === "string") {
		return classifyMetaError({ message: error }).retryable;
	}
	return classifyMetaError(error).retryable;
}

/**
 * Check if a Meta error indicates an auth/token issue (needs reauth).
 * Drop-in replacement for string-based isOAuthError().
 */
export function isAuthError(
	error:
		| string
		| {
				code?: number | undefined;
				error_subcode?: number | undefined;
				type?: string | undefined;
				message?: string | undefined;
		  },
): boolean {
	if (typeof error === "string") {
		return classifyMetaError({ message: error }).category === "auth";
	}
	return classifyMetaError(error).category === "auth";
}
