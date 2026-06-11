/**
 * OAuth Callback Security Tests
 *
 * Source-code scan tests for the two most critical untested handlers:
 * 1. Threads OAuth callback (api/auth/threads/callback.ts)
 * 2. Instagram OAuth callback (api/auth/instagram/callback.ts)
 *
 * Validates security-critical patterns:
 * - CORS lockdown, rate limiting, CSRF state validation
 * - Token exchange & encryption
 * - Account limit enforcement
 * - Audit logging
 */

import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

const THREADS_CB = join(__dirname, "../../api/auth/threads/callback.ts");
const IG_CB = join(__dirname, "../../api/auth/instagram/callback.ts");

const threadsCode = readFileSync(THREADS_CB, "utf-8");
const igCode = readFileSync(IG_CB, "utf-8");

// ============================================================================
// Shared: Both Callbacks
// ============================================================================

describe.each([
	["Threads", threadsCode],
	["Instagram", igCode],
] as const)("%s OAuth Callback — Shared Security", (platform, code) => {
	// ── CORS ──
	it("must lock CORS to juno33.com (not wildcard)", () => {
		expect(code).toContain('"https://juno33.com"');
		expect(code).not.toContain('"Access-Control-Allow-Origin", "*"');
	});

	it("must set Access-Control-Allow-Origin header", () => {
		expect(code).toContain("Access-Control-Allow-Origin");
	});

	it("must handle OPTIONS preflight", () => {
		expect(code).toContain('"OPTIONS"');
	});

	// ── Auth ──
	it("must verify user auth via getAuthUserOrError", () => {
		expect(code).toContain("getAuthUserOrError");
	});

	it("must import getAuthUserOrError from apiResponse", () => {
		expect(code).toContain("getAuthUserOrError");
		expect(code).toMatch(/import\s*\{[^}]*getAuthUserOrError/);
	});

	// ── Rate Limiting ──
	it("must rate-limit auth attempts via Redis", () => {
		const lcPlatform = platform.toLowerCase();
		expect(code).toContain(`rl:auth:${lcPlatform}:`);
	});

	it("must extract client IP from x-forwarded-for", () => {
		expect(code).toContain("x-forwarded-for");
	});

	it("must return 429 when rate limit exceeded", () => {
		expect(code).toContain("429");
		expect(code).toContain("Retry-After");
	});

	it("must fail-open when Redis rate limit is unavailable", () => {
		// The rate limit block should have a catch that allows the request through
		const rateLimitBlock = code.slice(
			code.indexOf("rl:auth:"),
			code.indexOf("rl:auth:") + 600,
		);
		expect(rateLimitBlock).toMatch(/catch/);
	});

	// ── CSRF State Validation ──
	it("must validate OAuth state parameter", () => {
		expect(code).toContain("validateOAuthState");
	});

	it("must check Redis for OAuth state (CSRF protection)", () => {
		expect(code).toContain("oauth_state:");
	});

	it("must delete Redis state after validation (prevent reuse)", () => {
		expect(code).toContain("redis.del(");
	});

	// ── Authorization Code ──
	it("must require authorization code in request body", () => {
		expect(code).toMatch(/code.*required|Authorization code is required/i);
	});

	it("must reject missing authorization code with 400", () => {
		expect(code).toContain("Authorization code is required");
	});

	// ── Token Encryption ──
	it("must import encrypt from encryption module", () => {
		expect(code).toMatch(/import\s*\{[^}]*encrypt/);
	});

	it("must encrypt the access token before storage", () => {
		expect(code).toContain("encrypt(");
	});

	it("must calculate token expiry date", () => {
		expect(code).toContain("token_expires_at");
		expect(code).toContain("expiresIn");
	});

	// ── Account Limits ──
	it("must check subscription tier for account limits", () => {
		expect(code).toContain("subscription_tier");
		expect(code).toContain("extra_accounts");
	});

	it("must import getAccountLimit from billing module", () => {
		expect(code).toContain("getAccountLimit");
	});

	it("must count both Threads + Instagram accounts toward limit", () => {
		// Both platforms should count active accounts from both tables
		expect(code).toContain('.eq("is_active", true)');
	});

	it("must return ACCOUNT_LIMIT_REACHED code when at capacity", () => {
		expect(code).toContain("ACCOUNT_LIMIT_REACHED");
	});

	it("must enforce limits using apiError (not raw res.json)", () => {
		// All 403 responses should go through apiError now
		expect(code).not.toMatch(/res\.status\(403\)\.json/);
	});

	it("must include currentCount, maxAllowed, tier in limit errors", () => {
		expect(code).toContain("currentCount");
		expect(code).toContain("maxAllowed");
	});

	// ── Database Safety ──
	it("must handle database query errors with 500", () => {
		expect(code).toContain("Database");
		expect(code).toMatch(/apiError\(res,\s*500/);
	});

	it("must set needs_reauth to false on successful connection", () => {
		expect(code).toContain("needs_reauth: false");
	});

	it("must set is_active to true on successful connection", () => {
		expect(code).toContain("is_active: true");
	});

	it("must reset consecutive_refresh_failures on reconnect", () => {
		expect(code).toContain("consecutive_refresh_failures: 0");
	});

	// ── Audit Logging ──
	it("must log account connection via logAudit", () => {
		expect(code).toContain("logAudit");
		expect(code).toContain("account.connect");
	});

	// ── Error Handling ──
	it("must have a top-level try-catch for unhandled errors", () => {
		// The handler should catch all errors and return 500
		expect(code).toContain("Internal server error");
	});

	it("must log errors with context", () => {
		expect(code).toContain("logger.error");
	});

	// ── Configuration Safety ──
	it("must check for client secret before token exchange", () => {
		expect(code).toContain("Server configuration error");
	});
});

// ============================================================================
// Threads-Specific
// ============================================================================

describe("Threads OAuth Callback — Platform Specific", () => {
	it("must exchange code at graph.threads.net", () => {
		expect(threadsCode).toContain("graph.threads.net/oauth/access_token");
	});

	it("must exchange for long-lived token with th_exchange_token", () => {
		expect(threadsCode).toContain("th_exchange_token");
	});

	it("must fetch profile from Threads v1.0 API", () => {
		expect(threadsCode).toContain("graph.threads.net/v1.0/me");
	});

	it("must request username and profile picture fields", () => {
		expect(threadsCode).toContain("username");
		expect(threadsCode).toContain("threads_profile_picture_url");
	});

	it("must store encrypted token as threads_access_token_encrypted", () => {
		expect(threadsCode).toContain("threads_access_token_encrypted");
	});

	it("must use threads_user_id for account lookup", () => {
		expect(threadsCode).toContain("threads_user_id");
	});

	it("must set posting_method to official", () => {
		expect(threadsCode).toContain('"official"');
	});

	it("must upsert with onConflict on user_id,threads_user_id", () => {
		expect(threadsCode).toContain("user_id,threads_user_id");
	});

	it("must check THREADS_CLIENT_SECRET env var", () => {
		expect(threadsCode).toContain("THREADS_CLIENT_SECRET");
	});

	it("must strip #_ suffix from authorization code", () => {
		expect(threadsCode).toContain("#_");
	});
});

// ============================================================================
// Instagram-Specific
// ============================================================================

describe("Instagram OAuth Callback — Platform Specific", () => {
	it("must exchange code at api.instagram.com", () => {
		expect(igCode).toContain("api.instagram.com/oauth/access_token");
	});

	it("must exchange for long-lived token with ig_exchange_token", () => {
		expect(igCode).toContain("ig_exchange_token");
	});

	it("must fetch profile from graph.instagram.com", () => {
		expect(igCode).toContain("graph.instagram.com");
	});

	it("must request follower/media count fields", () => {
		expect(igCode).toContain("followers_count");
		expect(igCode).toContain("media_count");
	});

	it("must store encrypted token as instagram_access_token_encrypted", () => {
		expect(igCode).toContain("instagram_access_token_encrypted");
	});

	it("must use instagram_user_id for account lookup", () => {
		expect(igCode).toContain("instagram_user_id");
	});

	it("must set login_type to instagram", () => {
		expect(igCode).toContain('"instagram"');
	});

	it("must not upsert mutable user ownership on instagram_user_id", () => {
		expect(igCode).toContain("ACCOUNT_ALREADY_LINKED");
		expect(igCode).toContain(".insert(");
		expect(igCode).not.toContain('onConflict: "instagram_user_id"');
	});

	it("must check INSTAGRAM_CLIENT_SECRET env var", () => {
		expect(igCode).toContain("INSTAGRAM_CLIENT_SECRET");
	});

	it("must subscribe to Instagram webhooks after connection", () => {
		expect(igCode).toContain("subscribeInstagramUserToWebhooks");
	});

	it("must import webhook subscription function", () => {
		expect(igCode).toContain("webhook-subscribe");
	});

	it("must handle webhook subscription failure gracefully", () => {
		// Webhook subscription call site (not the import) should be wrapped in try-catch
		const callIdx = igCode.indexOf("subscribeInstagramUserToWebhooks(");
		expect(callIdx).toBeGreaterThan(0);
		// Look backwards from call site for a try block
		const preceding = igCode.slice(Math.max(0, callIdx - 200), callIdx);
		expect(preceding).toContain("try");
	});
});
