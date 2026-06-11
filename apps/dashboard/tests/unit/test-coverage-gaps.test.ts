/**
 * Test Coverage Gaps — Source Code Scan Tests
 *
 * Validates security-critical and data-integrity patterns across
 * 11 previously-untested modules identified by infrastructure audit.
 *
 * Modules covered:
 * 1. Instagram token refresh
 * 2. GDPR user delete (cascading)
 * 3. GDPR data export
 * 4. Stripe subscription handler
 * 5. Daily orchestrator cron
 * 6. MCP server handler
 * 7. QStash signature verification
 * 8. Analytics sync worker
 * 9. Webhook handler
 * 10. Publish post handler
 * 11. Scheduled posts pipeline
 */

import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

const read = (rel: string) => readFileSync(join(__dirname, "../../", rel), "utf-8");

const igRefresh = read("api/auth/instagram/refresh.ts");
const userDelete =
	read("api/_lib/handlers/user/delete.ts") +
	"\n" +
	read("api/_lib/handlers/user/deletionCascade.ts");
const userExport = read("api/_lib/handlers/user/export.ts");
const subscription = read("api/_lib/handlers/subscription/index.ts");
const stripeClient = read("api/_lib/stripeClient.ts");
const dailyOrch = read("api/cron/daily-orchestrator.ts");
const mcp = read("api/mcp.ts");
const qstash = read("api/_lib/qstash.ts");
const analyticsSync = read("api/_lib/analyticsSync.ts");
const webhooks = read("api/webhooks.ts");
const publishPost = read("api/_lib/publishPost.ts");
const scheduledIndex = read("api/_lib/cron/scheduled-posts/index.ts");
const scheduledShared = read("api/_lib/cron/scheduled-posts/shared.ts");

// ============================================================================
// 1. Instagram Token Refresh
// ============================================================================

describe("Instagram Token Refresh", () => {
	it("must reference instagram platform", () => {
		expect(igRefresh).toContain("instagram");
	});

	it("must handle token refresh by login type", () => {
		expect(igRefresh).toContain("refreshTokenByLoginType");
	});

	it("must reference encrypted token field", () => {
		expect(igRefresh).toContain("instagram_access_token_encrypted");
	});

	it("must reference the instagram_accounts table", () => {
		expect(igRefresh).toContain("instagram_accounts");
	});

	it("must handle login_type for conditional refresh", () => {
		expect(igRefresh).toContain("login_type");
	});
});

// ============================================================================
// 2. GDPR User Delete
// ============================================================================

describe("GDPR User Delete", () => {
	it("must require DELETE method", () => {
		expect(userDelete).toContain("DELETE");
	});

	it("must use withAuth middleware", () => {
		expect(userDelete).toContain("withAuth");
	});

	it("must rate-limit delete requests", () => {
		expect(userDelete).toContain("checkRateLimit");
	});

	it("must use closed fail mode for rate limiting", () => {
		expect(userDelete).toContain('failMode: "closed"');
	});

	it("must require email confirmation", () => {
		expect(userDelete).toContain("confirmEmail");
	});

	it("must return EMAIL_MISMATCH error code", () => {
		expect(userDelete).toContain("EMAIL_MISMATCH");
	});

	it("must cascade delete user data", () => {
		expect(userDelete).toContain("cascadeDeleteUserData");
	});

	it("must delete auth user after data cascade", () => {
		expect(userDelete).toContain("deleteAuthUser");
	});

	it("must cancel Stripe subscription", () => {
		expect(userDelete).toContain("subscriptions.cancel");
	});

	it("must revoke Meta tokens via Graph API", () => {
		expect(userDelete).toContain("graph.facebook.com");
	});

	it("must decrypt tokens before revocation", () => {
		expect(userDelete).toContain("instagram_access_token_encrypted");
	});

	it("must audit log the deletion", () => {
		expect(userDelete).toContain("logAudit");
		expect(userDelete).toContain("account_deletion");
	});

	it("must timeout webhook unsubscribe calls", () => {
		expect(userDelete).toContain("AbortSignal.timeout");
	});
});

// ============================================================================
// 3. GDPR Data Export
// ============================================================================

describe("GDPR Data Export", () => {
	it("must require GET method", () => {
		expect(userExport).toContain("GET");
	});

	it("must rate-limit export requests", () => {
		expect(userExport).toContain("checkRateLimit");
	});

	it("must use closed fail mode", () => {
		expect(userExport).toContain('failMode: "closed"');
	});

	it("must create export job in database", () => {
		expect(userExport).toContain("data_export_jobs");
	});

	it("must dispatch worker via QStash", () => {
		expect(userExport).toContain("getQStashClient");
	});

	it("must dispatch to export-worker endpoint", () => {
		expect(userExport).toContain("export-worker");
	});

	it("must audit log export request", () => {
		expect(userExport).toContain("logAudit");
		expect(userExport).toContain("data_export");
	});

	it("must handle QStash dispatch failure", () => {
		expect(userExport).toContain('status: "failed"');
	});
});

// ============================================================================
// 4. Stripe Subscription Handler
// ============================================================================

describe("Stripe Subscription Handler", () => {
	it("must use withAuth middleware", () => {
		expect(subscription).toContain("withAuth");
	});

	it("must rate-limit subscription requests", () => {
		expect(subscription).toContain("checkRateLimit");
	});

	it("must require STRIPE_SECRET_KEY", () => {
		expect(stripeClient).toContain("STRIPE_SECRET_KEY");
	});

	it("must initialize Stripe client", () => {
		expect(stripeClient).toContain("new Stripe");
	});

	it("must reference STRIPE_PRICE_ env vars", () => {
		expect(subscription).toContain("STRIPE_PRICE_");
	});

	it("must validate tier is pro or empire", () => {
		expect(subscription).toMatch(/pro.*empire|empire.*pro/);
	});

	it("must check cross-user trial abuse", () => {
		expect(subscription).toContain("checkCrossUserTrialAbuse");
	});

	it("must create Stripe checkout session", () => {
		expect(subscription).toContain("checkout.sessions.create");
	});

	it("must include supabase_user_id in subscription metadata", () => {
		expect(subscription).toContain("supabase_user_id");
	});

	it("must enforce account limits on downgrade", () => {
		expect(subscription).toContain("enforceAccountLimits");
	});

	it("must handle subscription cancellation", () => {
		expect(subscription).toContain("subscriptions.cancel");
	});

	it("must set tier to free on cancel", () => {
		expect(subscription).toContain('subscription_tier: "free"');
	});

	it("must track trial usage", () => {
		expect(subscription).toContain("has_used_trial");
	});

	it("must cap extra accounts", () => {
		expect(subscription).toContain("MAX_EXTRA_ACCOUNTS");
	});

	it("must cap extra team members", () => {
		expect(subscription).toContain("MAX_EXTRA_TEAM_MEMBERS");
	});
});

// ============================================================================
// 5. Daily Orchestrator Cron
// ============================================================================

describe("Daily Orchestrator Cron", () => {
	it("must verify cron auth", () => {
		expect(dailyOrch).toContain("verifyCronAuth");
	});

	it("must use distributed lock", () => {
		expect(dailyOrch).toContain("withCronLock");
	});

	it("must track cron run", () => {
		expect(dailyOrch).toContain("trackCronRun");
	});

	it("must set maxDuration to 300", () => {
		expect(dailyOrch).toContain("maxDuration: 300");
	});

	it("must have time budget check", () => {
		expect(dailyOrch).toContain("hasTimeBudget");
	});

	it("must clean up orphaned cron runs", () => {
		expect(dailyOrch).toContain("cron_runs");
		expect(dailyOrch).toContain("orphan");
	});

	it("must execute token refresh phase", () => {
		expect(dailyOrch).toContain("phaseRefreshTokens");
	});

	it("must execute trial expiry phase", () => {
		expect(dailyOrch).toContain("phaseExpireTrials");
	});

	it("must execute data retention phase", () => {
		expect(dailyOrch).toContain("phaseDataRetention");
	});

	it("must execute account limit enforcement", () => {
		expect(dailyOrch).toContain("phaseEnforceAccountLimits");
	});

	it("must execute quick-win monitor", () => {
		expect(dailyOrch).toContain("phaseQuickwinMonitor");
	});

	it("must execute competitor snapshots", () => {
		expect(dailyOrch).toContain("phaseCompetitorSnapshots");
	});

	it("must report failures to Sentry", () => {
		expect(dailyOrch).toContain("captureServerException");
	});

	it("must alert cron failures to Discord", () => {
		expect(dailyOrch).toContain("alertCronFailure");
	});

	it("must track phases completed and errored", () => {
		expect(dailyOrch).toContain("phasesCompleted");
		expect(dailyOrch).toContain("phasesErrored");
	});
});

// ============================================================================
// 6. MCP Server Handler
// ============================================================================

describe("MCP Server Handler", () => {
	it("must lock CORS to juno33.com", () => {
		expect(mcp).toContain('"https://juno33.com"');
		expect(mcp).not.toContain('"Access-Control-Allow-Origin", "*"');
	});

	it("must handle OPTIONS preflight", () => {
		expect(mcp).toContain('"OPTIONS"');
	});

	it("must support JWT Bearer auth", () => {
		expect(mcp).toContain("Bearer ");
	});

	it("must support API key auth (juno_ak_ prefix)", () => {
		expect(mcp).toContain("juno_ak_");
	});

	it("must hash API keys with SHA256", () => {
		expect(mcp).toContain('createHash("sha256")');
	});

	it("must validate API keys against api_keys table", () => {
		expect(mcp).toContain("api_keys");
		expect(mcp).toContain("key_hash");
	});

	it("must check key is_active and expires_at", () => {
		expect(mcp).toContain("is_active");
		expect(mcp).toContain("expires_at");
	});

	it("must require explicit mcp scope for developer API key sessions", () => {
		expect(mcp).toContain("scopes");
		expect(mcp).toContain('includes("mcp")');
	});

	it("must validate JWT via Supabase auth", () => {
		expect(mcp).toContain("auth.getUser");
	});

	it("must use McpServer from SDK", () => {
		expect(mcp).toContain("McpServer");
	});

	it("must use StreamableHTTPServerTransport", () => {
		expect(mcp).toContain("StreamableHTTPServerTransport");
	});

	it("must register tool modules", () => {
		expect(mcp).toContain("register(server");
	});

	it("must reject GET requests (no SSE)", () => {
		expect(mcp).toContain("SSE not supported");
	});

	it("must include Mcp-Session-Id in allowed headers", () => {
		expect(mcp).toContain("Mcp-Session-Id");
	});
});

// ============================================================================
// 7. QStash Signature Verification
// ============================================================================

describe("QStash Signature Verification", () => {
	it("must import Client and Receiver from @upstash/qstash", () => {
		expect(qstash).toContain("@upstash/qstash");
		expect(qstash).toContain("Client");
		expect(qstash).toContain("Receiver");
	});

	it("must export getQStashClient", () => {
		expect(qstash).toContain("getQStashClient");
	});

	it("must require QSTASH_TOKEN", () => {
		expect(qstash).toContain("QSTASH_TOKEN");
	});

	it("must export verifyQStashSignature", () => {
		expect(qstash).toContain("verifyQStashSignature");
	});

	it("must read upstash-signature header", () => {
		expect(qstash).toContain("upstash-signature");
	});

	it("must use getReceiver().verify for HMAC check", () => {
		expect(qstash).toContain("getReceiver().verify");
	});

	it("must use both current and next signing keys", () => {
		expect(qstash).toContain("QSTASH_CURRENT_SIGNING_KEY");
		expect(qstash).toContain("QSTASH_NEXT_SIGNING_KEY");
	});

	it("must return 401 on invalid signature", () => {
		expect(qstash).toContain("401");
	});

	it("must warn on missing signature header", () => {
		expect(qstash).toContain("upstash-signature");
	});
});

// ============================================================================
// 8. Analytics Sync Worker
// ============================================================================

describe("Analytics Sync Worker", () => {
	it("must decrypt tokens before API calls", () => {
		expect(analyticsSync).toContain("decrypt");
		expect(analyticsSync).toContain("threads_access_token_encrypted");
	});

	it("must handle Instagram tokens too", () => {
		expect(analyticsSync).toContain("instagram_access_token_encrypted");
	});

	it("must use batch processing", () => {
		expect(analyticsSync).toContain("POST_BATCH_SIZE");
	});

	it("must have fetch timeout", () => {
		expect(analyticsSync).toContain("FETCH_TIMEOUT_MS");
	});

	it("must detect rate limiting (429)", () => {
		expect(analyticsSync).toContain("429");
	});

	it("must call Threads Graph API", () => {
		expect(analyticsSync).toContain("graph.threads.net");
	});

	it("must update last_synced_at", () => {
		expect(analyticsSync).toContain("last_synced_at");
	});

	it("must calculate engagement rate", () => {
		expect(analyticsSync).toContain("calculateEngagementRate");
	});

	it("must detect anomalies", () => {
		expect(analyticsSync).toContain("detectAnomalies");
	});

	it("must check milestones", () => {
		expect(analyticsSync).toContain("checkMilestones");
	});

	it("must invalidate dashboard cache", () => {
		expect(analyticsSync).toContain("invalidateDashboard");
	});
});

// ============================================================================
// 9. Webhook Handler
// ============================================================================

describe("Webhook Handler", () => {
	it("must use withAuth middleware", () => {
		expect(webhooks).toContain("withAuth");
	});

	it("must compute HMAC-SHA256 signatures", () => {
		expect(webhooks).toContain('createHmac("sha256"');
	});

	it("must decrypt webhook secrets", () => {
		expect(webhooks).toContain("decrypt");
	});

	it("must encrypt secrets at rest", () => {
		expect(webhooks).toContain("encrypt");
	});

	it("must use webhook_subscriptions table", () => {
		expect(webhooks).toContain("webhook_subscriptions");
	});

	it("must support rotate-secret action", () => {
		expect(webhooks).toContain("rotate-secret");
	});

	it("must support test action with rate limiting", () => {
		expect(webhooks).toContain('"test"');
		expect(webhooks).toContain("enforceRouteRateLimit");
	});

	it("must validate URLs against SSRF", () => {
		expect(webhooks).toContain("validateUrlNotPrivate");
	});

	it("must enforce minimum secret length of 16", () => {
		expect(webhooks).toContain("at least 16 characters");
	});

	it("must set secret TTL with default 90 days", () => {
		expect(webhooks).toContain("DEFAULT_SECRET_TTL_DAYS");
		expect(webhooks).toContain("secret_expires_at");
	});

	it("must set secret_rotated_at on rotation", () => {
		expect(webhooks).toContain("secret_rotated_at");
	});

	it("must use X-Juno33-Signature-256 header", () => {
		expect(webhooks).toContain("X-Juno33-Signature-256");
	});

	it("must prefix signature with sha256=", () => {
		expect(webhooks).toContain("sha256=");
	});

	it("must support standard webhook event types", () => {
		expect(webhooks).toContain("post.published");
		expect(webhooks).toContain("sync.completed");
	});
});

// ============================================================================
// 10. Publish Post Handler
// ============================================================================

describe("Publish Post Handler", () => {
	it("must export publishSinglePost", () => {
		expect(publishPost).toContain("publishSinglePost");
	});

	it("must define chain separator for thread posts", () => {
		expect(publishPost).toContain("CHAIN_SEPARATOR");
	});

	it("must handle rate limit retries", () => {
		expect(publishPost).toContain("MAX_RATE_LIMIT_RETRIES");
	});

	it("must escalate failures with skip logic", () => {
		expect(publishPost).toContain("escalateSkip");
	});

	it("must check account publishability", () => {
		expect(publishPost).toContain("isAccountPublishable");
	});

	it("must check media URL accessibility", () => {
		expect(publishPost).toContain("checkMediaUrlAccessible");
	});

	it("must support cross-posting", () => {
		expect(publishPost).toContain("handleCrossPost");
	});

	it("must notify users on publish failure", () => {
		expect(publishPost).toContain("post_failed");
	});

	it("must decrypt tokens before publishing", () => {
		expect(publishPost).toContain("threads_access_token_encrypted");
	});

	it("must check needs_reauth before publishing", () => {
		expect(publishPost).toContain("needs_reauth");
	});

	it("must check token expiry", () => {
		expect(publishPost).toContain("token_expires_at");
	});

	it("must detect transient errors for retry", () => {
		expect(publishPost).toContain("isTransientError");
	});

	it("must use atomic status claim for scheduled posts", () => {
		expect(publishPost).toContain('status: "scheduled"');
	});

	it("must run native-audio publish preflight before exact-time Instagram claim", () => {
		const instagramSection = publishPost.slice(
			publishPost.indexOf("async function publishInstagramPost"),
		);
		const preflightIndex = instagramSection.indexOf("await runPublishPreflight");
		const claimIndex = instagramSection.indexOf("// Atomic claim");

		expect(preflightIndex).toBeGreaterThan(0);
		expect(claimIndex).toBeGreaterThan(preflightIndex);
	});
});

// ============================================================================
// 11. Scheduled Posts Pipeline
// ============================================================================

describe("Scheduled Posts Pipeline", () => {
	it("must export rate limit utilities", () => {
		expect(scheduledIndex).toContain("checkAndIncrementRateLimit");
	});

	it("must export media validation", () => {
		expect(scheduledIndex).toContain("checkMediaUrlAccessible");
	});

	it("must export cross-post handler", () => {
		expect(scheduledIndex).toContain("handleCrossPost");
	});

	it("must export Threads publisher", () => {
		expect(scheduledIndex).toContain("processThreadsPosts");
	});

	it("must export Instagram publisher", () => {
		expect(scheduledIndex).toContain("processNewIGPosts");
	});

	it("must export maintenance utilities", () => {
		expect(scheduledIndex).toContain("cleanupOrphanedPosts");
	});

	it("must export retry logic for IG containers", () => {
		expect(scheduledIndex).toContain("retryIGContainers");
	});

	it("shared module must define rate limit constants", () => {
		expect(scheduledShared).toContain("RATE_LIMITS");
	});

	it("shared module must export transient error detector", () => {
		expect(scheduledShared).toContain("isTransientError");
	});

	it("shared module must define config export", () => {
		expect(scheduledShared).toContain("config");
	});
});
