import { describe, expect, it } from "vitest";

/**
 * Tests for the OAuth error detection logic used across the publish pipeline.
 *
 * This function is the gate between "transient Meta 500" and "dead token".
 * Misclassification either kills live accounts or lets dead ones keep failing.
 *
 * Canonical implementation: api/_lib/handlers/auto-post/queue.ts:42-58
 * Also duplicated in: auto-post-publish.ts:399-411
 */

// Extract the canonical logic inline (same as queue.ts:42-58)
function isOAuthError(error: string): boolean {
	const lower = error.toLowerCase();
	if (lower.includes("unknown error") || lower.includes("unexpected error"))
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

describe("isOAuthError", () => {
	// ── SHOULD flag as OAuth (definitive token death) ──────────────────

	it("detects OAuthException", () => {
		expect(isOAuthError("Error: OAuthException - Invalid token")).toBe(true);
	});

	it("detects invalid oauth (case-insensitive)", () => {
		expect(isOAuthError("Invalid OAuth 2.0 Access Token")).toBe(true);
	});

	it("detects token expired", () => {
		expect(isOAuthError("The access token has expired")).toBe(true);
	});

	it("detects session expired", () => {
		expect(isOAuthError("The session has expired")).toBe(true);
	});

	it("detects session invalidated", () => {
		expect(
			isOAuthError("Session has been invalidated because the user changed password"),
		).toBe(true);
	});

	it("detects error validating access token", () => {
		expect(
			isOAuthError("Error validating access token: Session has expired"),
		).toBe(true);
	});

	it("detects access token could not be decrypted", () => {
		expect(isOAuthError("The access token could not be decrypted")).toBe(true);
	});

	it("detects token verification failed", () => {
		expect(isOAuthError("Token verification failed")).toBe(true);
	});

	it("detects code 190 (token revoked)", () => {
		expect(isOAuthError("Error code 190: token invalid")).toBe(true);
	});

	// ── MUST NOT flag (transient Meta 500s) ────────────────────────────

	it("does NOT flag Meta generic 500: 'An unknown error has occurred'", () => {
		expect(
			isOAuthError(
				"An unknown error has occurred (code=1, type=OAuthException)",
			),
		).toBe(false);
	});

	it("does NOT flag 'An unexpected error has occurred'", () => {
		expect(
			isOAuthError("An unexpected error has occurred. Please retry your request later."),
		).toBe(false);
	});

	it("does NOT flag rate limit errors", () => {
		expect(
			isOAuthError("(#4) Application request limit reached"),
		).toBe(false);
	});

	it("does NOT flag generic API errors", () => {
		expect(isOAuthError("Failed to create container")).toBe(false);
	});

	it("does NOT flag network errors", () => {
		expect(isOAuthError("ECONNRESET")).toBe(false);
	});

	it("does NOT flag timeout errors", () => {
		expect(isOAuthError("The operation was aborted due to timeout")).toBe(false);
	});

	// ── Edge case: 'unknown error' inside OAuthException ───────────────
	// Meta's transient 500 wraps 'unknown error' inside OAuthException type.
	// The 'unknown error' check must take priority over 'oauthexception'.

	it("unknown error takes priority even when OAuthException is in the string", () => {
		expect(
			isOAuthError(
				"An unknown error has occurred (code=1, type=OAuthException)",
			),
		).toBe(false);
	});
});
