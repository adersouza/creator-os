/**
 * Validates required environment variables on first import (cold start).
 * Throws immediately if any critical vars are missing — surfaces misconfig
 * at deploy time rather than when a user hits the affected route.
 *
 * Two tiers:
 *   CRITICAL — app cannot function without these. Missing = throw.
 *   EXPECTED — most routes need these. Missing = console.warn at cold start.
 *              Individual routes should still guard before use.
 */

const CRITICAL_VARS = ["SUPABASE_URL", "ENCRYPTION_KEY"] as const;

const EXPECTED_VARS = [
	"CRON_SECRET",
	"UPSTASH_REDIS_REST_URL",
	"UPSTASH_REDIS_REST_TOKEN",
	"STRIPE_SECRET_KEY",
	"STRIPE_WEBHOOK_SECRET",
	"THREADS_CLIENT_ID",
	"THREADS_CLIENT_SECRET",
	"THREADS_APP_SECRET",
	"INSTAGRAM_CLIENT_ID",
	"INSTAGRAM_CLIENT_SECRET",
	"FACEBOOK_APP_ID",
	"FACEBOOK_APP_SECRET",
	"META_APP_SECRET",
	"QSTASH_TOKEN",
	"QSTASH_CURRENT_SIGNING_KEY",
	"QSTASH_NEXT_SIGNING_KEY",
] as const;

// Skip validation in test environment
if (process.env.NODE_ENV !== "test" && !process.env.VITEST) {
	const missingCritical: string[] = CRITICAL_VARS.filter((v) => !process.env[v]);
	if (
		!process.env.SUPABASE_SERVICE_ROLE_KEY &&
		!process.env.SUPABASE_SERVICE_KEY
	) {
		missingCritical.push("SUPABASE_SERVICE_ROLE_KEY");
	}
	if (missingCritical.length > 0) {
		throw new Error(
			`[envCheck] Missing CRITICAL environment variables: ${missingCritical.join(", ")}`,
		);
	}

	const missingExpected = EXPECTED_VARS.filter((v) => !process.env[v]);
	if (missingExpected.length > 0) {
		// biome-ignore lint/suspicious/noConsole: cold-start env validation
		console.warn(
			`[envCheck] Missing expected environment variables (features will degrade): ${missingExpected.join(", ")}`,
		);
	}
}

/**
 * Runtime guard for route-specific env vars. Call at handler entry, not module top level.
 * Returns the value or throws a descriptive error.
 *
 * @example
 *   const key = requireEnv("STRIPE_SECRET_KEY");
 */
export function requireEnv(name: string): string {
	const val = process.env[name];
	if (!val) {
		throw new Error(
			`[envCheck] Required environment variable ${name} is not set`,
		);
	}
	return val;
}

export const envChecked = true;
