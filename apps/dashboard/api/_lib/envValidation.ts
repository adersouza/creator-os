import { z } from "./zodCompat.js";
import type { Infer } from "./zodCompat.js";

const EnvSchema = z.object({
	// Core
	SUPABASE_URL: z.string().url(),
	SUPABASE_SERVICE_ROLE_KEY: z.string().min(1).optional(),
	SUPABASE_SERVICE_KEY: z.string().min(1).optional(),
	ENCRYPTION_KEY: z
		.string()
		.min(32)
		.regex(/^[A-Za-z0-9+/]{32,}=*$/, "ENCRYPTION_KEY must be valid base64"),

	// OAuth
	THREADS_CLIENT_ID: z.string().min(1),
	THREADS_CLIENT_SECRET: z.string().min(1),
	INSTAGRAM_CLIENT_ID: z.string().min(1),
	INSTAGRAM_CLIENT_SECRET: z.string().min(1),

	// Payment
	STRIPE_SECRET_KEY: z.string().min(1),
	STRIPE_WEBHOOK_SECRET: z.string().min(1),

	// Webhooks
	THREADS_APP_SECRET: z.string().min(1),
	META_APP_SECRET: z.string().min(1),

	// Infra
	CRON_SECRET: z.string().min(1),
	UPSTASH_REDIS_REST_URL: z.string().url(),
	UPSTASH_REDIS_REST_TOKEN: z.string().min(1),
	QSTASH_TOKEN: z.string().min(1).optional(),
	QSTASH_CURRENT_SIGNING_KEY: z.string().min(1).optional(),
	QSTASH_NEXT_SIGNING_KEY: z.string().min(1).optional(),
	RESEND_API_KEY: z.string().min(1),
});

export type Env = Infer<typeof EnvSchema>;

const REQUIRED_VARS: Record<string, string[]> = {
	core: ["SUPABASE_URL", "ENCRYPTION_KEY"],
	threads: ["THREADS_CLIENT_ID", "THREADS_CLIENT_SECRET"],
	instagram: ["INSTAGRAM_CLIENT_ID", "INSTAGRAM_CLIENT_SECRET"],
	stripe: ["STRIPE_SECRET_KEY"],
	webhooks: ["THREADS_APP_SECRET", "META_APP_SECRET"],
	cron: ["CRON_SECRET"],
	redis: ["UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"],
	qstash: [
		"QSTASH_TOKEN",
		"QSTASH_CURRENT_SIGNING_KEY",
		"QSTASH_NEXT_SIGNING_KEY",
	],
	email: ["RESEND_API_KEY"],
	stripe_pricing: [
		"STRIPE_PRICE_PRO_MONTHLY",
		"STRIPE_PRICE_PRO_YEARLY",
		"STRIPE_PRICE_EMPIRE_MONTHLY",
		"STRIPE_PRICE_EMPIRE_YEARLY",
	],
};

/**
 * Validates the environment variables.
 * Legacy support: accepts groups and returns string[].
 * Modern support: if no groups, returns the validated Env object.
 */
export function validateEnv(
	...groups: string[]
): string[] | Record<string, string | undefined> {
	if (groups.length > 0) {
		const missing: string[] = [];
		for (const group of groups) {
			const vars = REQUIRED_VARS[group];
			if (!vars) continue;
			for (const v of vars) {
				if (!process.env[v]) missing.push(v);
			}
			if (
				group === "core" &&
				!process.env.SUPABASE_SERVICE_ROLE_KEY &&
				!process.env.SUPABASE_SERVICE_KEY
			) {
				missing.push("SUPABASE_SERVICE_ROLE_KEY");
			}
		}
		return missing;
	}

	const result = EnvSchema.safeParse(process.env);
	if (!result.success) {
		const missing = result.error.issues.map((i) => i.path.join(".")).join(", ");
		throw new Error(
			`[Env Validation] Missing or invalid variables: ${missing}`,
		);
	}
	if (
		!result.data.SUPABASE_SERVICE_ROLE_KEY &&
		!result.data.SUPABASE_SERVICE_KEY
	) {
		throw new Error(
			"[Env Validation] Missing or invalid variables: SUPABASE_SERVICE_ROLE_KEY",
		);
	}
	return result.data;
}

/** Legacy support - keeps existing requireEnv calls working */
export function requireEnv(...groups: string[]): void {
	const missing = validateEnv(...groups);
	if (Array.isArray(missing) && missing.length > 0) {
		throw new Error(`Missing required env vars: ${missing.join(", ")}`);
	}
}
