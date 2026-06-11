/**
 * Enterprise Gaps Hardening Tests
 *
 * Validates all 5 audit gap fixes:
 * 1. Webhook secret rotation with TTL
 * 2. Cursor-based pagination for v1 API
 * 3. Auth attempt lockout via Redis
 * 4. Enhanced Redis health monitoring
 * 5. Preview deployment cron protection
 */

import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

const WEBHOOKS = join(__dirname, "../../api/webhooks.ts");
const V1_POSTS = join(__dirname, "../../api/_lib/handlers/v1/posts.ts");
const AUTH_LOCKOUT = join(__dirname, "../../api/_lib/authLockout.ts");
const API_RESPONSE = join(__dirname, "../../api/_lib/apiResponse.ts");
const HEALTH_MONITOR = join(__dirname, "../../api/cron/health-monitor.ts");
const MIDDLEWARE = join(__dirname, "../../api/_lib/middleware.ts");
const MIGRATION = join(
	__dirname,
	"../../supabase/migrations/20260407300000_enterprise_hardening_gaps.sql",
);

const webhooksCode = readFileSync(WEBHOOKS, "utf-8");
const v1PostsCode = readFileSync(V1_POSTS, "utf-8");
const authLockoutCode = readFileSync(AUTH_LOCKOUT, "utf-8");
const apiResponseCode = readFileSync(API_RESPONSE, "utf-8");
const healthMonitorCode = readFileSync(HEALTH_MONITOR, "utf-8");
const middlewareCode = readFileSync(MIDDLEWARE, "utf-8");
const migrationCode = readFileSync(MIGRATION, "utf-8");

// ============================================================================
// Gap #1: Webhook Secret Rotation
// ============================================================================

describe("Gap #1 — Webhook Secret Rotation", () => {
	it("must have rotate-secret action in webhook handler", () => {
		expect(webhooksCode).toContain('action === "rotate-secret"');
	});

	it("must encrypt new secret during rotation", () => {
		expect(webhooksCode).toContain("encrypt(newSecret)");
	});

	it("must set secret_rotated_at on rotation", () => {
		expect(webhooksCode).toContain("secret_rotated_at");
	});

	it("must set secret_expires_at on rotation", () => {
		expect(webhooksCode).toContain("secret_expires_at");
	});

	it("must have configurable TTL with default 90 days", () => {
		expect(webhooksCode).toContain("DEFAULT_SECRET_TTL_DAYS");
		expect(webhooksCode).toMatch(/90/);
	});

	it("must set TTL on new webhook creation too", () => {
		// secret_expires_at must appear in both rotation and creation code paths
		const expiresOccurrences = webhooksCode.match(/secret_expires_at/g) || [];
		expect(expiresOccurrences.length).toBeGreaterThanOrEqual(2);
		// Verify it's in the insert block (not just rotation)
		const insertIdx = webhooksCode.indexOf(".insert({");
		const afterInsert = webhooksCode.slice(insertIdx, insertIdx + 400);
		expect(afterInsert).toContain("secret_expires_at");
	});

	it("migration must add rotation columns", () => {
		expect(migrationCode).toContain("secret_rotated_at TIMESTAMPTZ");
		expect(migrationCode).toContain("secret_expires_at TIMESTAMPTZ");
	});

	it("migration must index expiring secrets for cron lookup", () => {
		expect(migrationCode).toContain("idx_webhook_subs_secret_expires");
	});

	it("must validate new secret minimum length", () => {
		expect(webhooksCode).toContain("at least 16 characters");
	});
});

// ============================================================================
// Gap #2: Cursor-Based Pagination
// ============================================================================

describe("Gap #2 — Cursor-Based Pagination", () => {
	it("must accept cursor query param", () => {
		expect(v1PostsCode).toContain("req.query.cursor");
	});

	it("must validate cursor format", () => {
		expect(v1PostsCode).toContain("Invalid cursor format");
	});

	it("must fetch cursor row to get sort value", () => {
		expect(v1PostsCode).toContain("cursorRow");
		expect(v1PostsCode).toContain("cursorValue");
	});

	it("must return nextCursor in response", () => {
		expect(v1PostsCode).toContain("nextCursor");
	});

	it("must fetch limit+1 to detect hasMore", () => {
		expect(v1PostsCode).toContain("limit + 1");
	});

	it("must use correct comparator based on sort order", () => {
		expect(v1PostsCode).toContain('"gt"');
		expect(v1PostsCode).toContain('"lt"');
	});

	it("must still support offset pagination", () => {
		expect(v1PostsCode).toContain(".range(offset, offset + limit - 1)");
	});

	it("must validate cursor ownership (user_id check)", () => {
		expect(v1PostsCode).toContain('.eq("user_id", user.id)');
	});
});

// ============================================================================
// Gap #3: Auth Attempt Lockout
// ============================================================================

describe("Gap #3 — Auth Attempt Lockout", () => {
	it("must export checkAuthLockout function", () => {
		expect(authLockoutCode).toContain("export async function checkAuthLockout");
	});

	it("must export recordAuthFailure function", () => {
		expect(authLockoutCode).toContain("export async function recordAuthFailure");
	});

	it("must export resetAuthFailures function", () => {
		expect(authLockoutCode).toContain("export async function resetAuthFailures");
	});

	it("must have tiered lockout thresholds", () => {
		expect(authLockoutCode).toContain("LOCKOUT_TIERS");
		expect(authLockoutCode).toContain("threshold: 10");
		expect(authLockoutCode).toContain("threshold: 20");
		expect(authLockoutCode).toContain("threshold: 30");
	});

	it("must use atomic Redis INCR for counters", () => {
		expect(authLockoutCode).toContain("redis.incr(key)");
	});

	it("must fail-open when Redis is down", () => {
		// checkAuthLockout catch block should return null (allow)
		const checkFn = authLockoutCode.slice(
			authLockoutCode.indexOf("export async function checkAuthLockout"),
			authLockoutCode.indexOf("export async function recordAuthFailure"),
		);
		expect(checkFn).toContain("return null");
	});

	it("must extract identifier from X-Forwarded-For", () => {
		expect(authLockoutCode).toContain("x-forwarded-for");
	});

	it("apiResponse must call checkAuthLockout before auth", () => {
		expect(apiResponseCode).toContain("checkAuthLockout");
		// checkAuthLockout must appear before getUser
		const lockoutIdx = apiResponseCode.indexOf("checkAuthLockout");
		const getUserIdx = apiResponseCode.indexOf("auth.getUser(token)");
		expect(lockoutIdx).toBeLessThan(getUserIdx);
	});

	it("apiResponse must call recordAuthFailure on failed auth", () => {
		expect(apiResponseCode).toContain("recordAuthFailure");
	});

	it("apiResponse must call resetAuthFailures on successful auth", () => {
		expect(apiResponseCode).toContain("resetAuthFailures");
	});

	it("must set Retry-After header on lockout", () => {
		expect(apiResponseCode).toContain("Retry-After");
	});

	it("migration must create auth_lockout_log table", () => {
		expect(migrationCode).toContain("CREATE TABLE IF NOT EXISTS auth_lockout_log");
	});

	it("migration must enable RLS on lockout table", () => {
		expect(migrationCode).toContain(
			"ALTER TABLE auth_lockout_log ENABLE ROW LEVEL SECURITY",
		);
	});
});

// ============================================================================
// Gap #4: Enhanced Redis Health Monitoring
// ============================================================================

describe("Gap #4 — Enhanced Redis Health Monitoring", () => {
	it("must perform write/read probe (not just PING)", () => {
		expect(healthMonitorCode).toContain("health-probe:canary");
	});

	it("must verify data integrity on read-back", () => {
		expect(healthMonitorCode).toContain("dataIntegrity");
	});

	it("must check latency thresholds", () => {
		expect(healthMonitorCode).toContain("highLatency");
		expect(healthMonitorCode).toContain("pingLatency");
		expect(healthMonitorCode).toContain("rwLatency");
	});

	it("must report both PING and R/W latency", () => {
		expect(healthMonitorCode).toContain("PING < 500ms");
		expect(healthMonitorCode).toContain("R/W < 1000ms");
	});

	it("must flag unhealthy on data integrity failure", () => {
		const integrityBlock = healthMonitorCode.slice(
			healthMonitorCode.indexOf("dataIntegrity"),
			healthMonitorCode.indexOf("dataIntegrity") + 300,
		);
		expect(integrityBlock).toContain("healthy: false");
	});
});

// ============================================================================
// Gap #5: Preview Deployment Cron Protection
// ============================================================================

describe("Gap #5 — Preview Deployment Protection", () => {
	it("withCron must check VERCEL_ENV", () => {
		expect(middlewareCode).toContain("VERCEL_ENV");
	});

	it("withCron must skip crons in non-production environments", () => {
		const cronSection = middlewareCode.slice(
			middlewareCode.indexOf("export function withCron"),
			middlewareCode.indexOf("export function withCron") + 800,
		);
		expect(cronSection).toContain('!== "production"');
		expect(cronSection).toContain("Crons disabled in");
	});

	it("must return 200 (not error) when skipping in preview", () => {
		const cronSection = middlewareCode.slice(
			middlewareCode.indexOf("export function withCron"),
			middlewareCode.indexOf("export function withCron") + 800,
		);
		expect(cronSection).toContain("status(200)");
		expect(cronSection).toContain("skipped: true");
	});
});
