import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { requireEnv, validateEnv } from "../envValidation.js";

describe("validateEnv", () => {
	let savedEnv: Record<string, string | undefined>;

	beforeEach(() => {
		// Save current env vars that might be checked
		savedEnv = {
			SUPABASE_URL: process.env.SUPABASE_URL,
			SUPABASE_SERVICE_ROLE_KEY: process.env.SUPABASE_SERVICE_ROLE_KEY,
			ENCRYPTION_KEY: process.env.ENCRYPTION_KEY,
			THREADS_CLIENT_ID: process.env.THREADS_CLIENT_ID,
			THREADS_CLIENT_SECRET: process.env.THREADS_CLIENT_SECRET,
			INSTAGRAM_CLIENT_ID: process.env.INSTAGRAM_CLIENT_ID,
			INSTAGRAM_CLIENT_SECRET: process.env.INSTAGRAM_CLIENT_SECRET,
			STRIPE_SECRET_KEY: process.env.STRIPE_SECRET_KEY,
			THREADS_APP_SECRET: process.env.THREADS_APP_SECRET,
			META_APP_SECRET: process.env.META_APP_SECRET,
			CRON_SECRET: process.env.CRON_SECRET,
			UPSTASH_REDIS_REST_URL: process.env.UPSTASH_REDIS_REST_URL,
			UPSTASH_REDIS_REST_TOKEN: process.env.UPSTASH_REDIS_REST_TOKEN,
			QSTASH_TOKEN: process.env.QSTASH_TOKEN,
			QSTASH_CURRENT_SIGNING_KEY: process.env.QSTASH_CURRENT_SIGNING_KEY,
			QSTASH_NEXT_SIGNING_KEY: process.env.QSTASH_NEXT_SIGNING_KEY,
			RESEND_API_KEY: process.env.RESEND_API_KEY,
			STRIPE_PRICE_PRO_MONTHLY: process.env.STRIPE_PRICE_PRO_MONTHLY,
			STRIPE_PRICE_PRO_YEARLY: process.env.STRIPE_PRICE_PRO_YEARLY,
			STRIPE_PRICE_EMPIRE_MONTHLY: process.env.STRIPE_PRICE_EMPIRE_MONTHLY,
			STRIPE_PRICE_EMPIRE_YEARLY: process.env.STRIPE_PRICE_EMPIRE_YEARLY,
		};
	});

	afterEach(() => {
		// Restore all saved env vars
		for (const [key, value] of Object.entries(savedEnv)) {
			if (value !== undefined) {
				process.env[key] = value;
			} else {
				delete process.env[key];
			}
		}
	});

	describe("core group", () => {
		it("returns empty array when all core vars are set", () => {
			process.env.SUPABASE_URL = "https://test.supabase.co";
			process.env.SUPABASE_SERVICE_ROLE_KEY = "test-key";
			process.env.ENCRYPTION_KEY = "test-encryption-key";
			expect(validateEnv("core")).toEqual([]);
		});

		it("reports missing SUPABASE_URL", () => {
			delete process.env.SUPABASE_URL;
			process.env.SUPABASE_SERVICE_ROLE_KEY = "test";
			process.env.ENCRYPTION_KEY = "test";
			const missing = validateEnv("core");
			expect(missing).toContain("SUPABASE_URL");
		});

		it("reports missing ENCRYPTION_KEY", () => {
			process.env.SUPABASE_URL = "test";
			process.env.SUPABASE_SERVICE_ROLE_KEY = "test";
			delete process.env.ENCRYPTION_KEY;
			const missing = validateEnv("core");
			expect(missing).toContain("ENCRYPTION_KEY");
		});

		it("reports all missing core vars", () => {
			delete process.env.SUPABASE_URL;
			delete process.env.SUPABASE_SERVICE_ROLE_KEY;
			delete process.env.ENCRYPTION_KEY;
			const missing = validateEnv("core");
			expect(missing).toHaveLength(3);
			expect(missing).toContain("SUPABASE_URL");
			expect(missing).toContain("SUPABASE_SERVICE_ROLE_KEY");
			expect(missing).toContain("ENCRYPTION_KEY");
		});
	});

	describe("no-args uses full Zod validation", () => {
		it("throws when env vars are missing or invalid", () => {
			delete process.env.SUPABASE_URL;
			process.env.SUPABASE_SERVICE_ROLE_KEY = "test";
			process.env.ENCRYPTION_KEY = "test";
			expect(() => validateEnv()).toThrow("Missing or invalid variables");
		});
	});

	describe("threads group", () => {
		it("returns empty when threads vars are set", () => {
			process.env.THREADS_CLIENT_ID = "test-id";
			process.env.THREADS_CLIENT_SECRET = "test-secret";
			expect(validateEnv("threads")).toEqual([]);
		});

		it("reports missing threads vars", () => {
			delete process.env.THREADS_CLIENT_ID;
			delete process.env.THREADS_CLIENT_SECRET;
			const missing = validateEnv("threads");
			expect(missing).toContain("THREADS_CLIENT_ID");
			expect(missing).toContain("THREADS_CLIENT_SECRET");
		});
	});

	describe("instagram group", () => {
		it("returns empty when instagram vars are set", () => {
			process.env.INSTAGRAM_CLIENT_ID = "test-id";
			process.env.INSTAGRAM_CLIENT_SECRET = "test-secret";
			expect(validateEnv("instagram")).toEqual([]);
		});

		it("reports missing instagram vars", () => {
			delete process.env.INSTAGRAM_CLIENT_ID;
			delete process.env.INSTAGRAM_CLIENT_SECRET;
			const missing = validateEnv("instagram");
			expect(missing).toContain("INSTAGRAM_CLIENT_ID");
			expect(missing).toContain("INSTAGRAM_CLIENT_SECRET");
		});
	});

	describe("multiple groups", () => {
		it("checks multiple groups at once", () => {
			delete process.env.SUPABASE_URL;
			process.env.SUPABASE_SERVICE_ROLE_KEY = "test";
			process.env.ENCRYPTION_KEY = "test";
			delete process.env.THREADS_CLIENT_ID;
			process.env.THREADS_CLIENT_SECRET = "test";
			const missing = validateEnv("core", "threads");
			expect(missing).toContain("SUPABASE_URL");
			expect(missing).toContain("THREADS_CLIENT_ID");
			expect(missing).toHaveLength(2);
		});

		it("returns empty array when all groups are satisfied", () => {
			process.env.SUPABASE_URL = "test";
			process.env.SUPABASE_SERVICE_ROLE_KEY = "test";
			process.env.ENCRYPTION_KEY = "test";
			process.env.STRIPE_SECRET_KEY = "test";
			expect(validateEnv("core", "stripe")).toEqual([]);
		});
	});

	describe("unknown group", () => {
		it("ignores unknown group names without error", () => {
			const missing = validateEnv("nonexistent_group");
			expect(missing).toEqual([]);
		});
	});

	describe("stripe_pricing group", () => {
		it("reports missing Stripe price vars", () => {
			delete process.env.STRIPE_PRICE_PRO_MONTHLY;
			delete process.env.STRIPE_PRICE_PRO_YEARLY;
			delete process.env.STRIPE_PRICE_EMPIRE_MONTHLY;
			delete process.env.STRIPE_PRICE_EMPIRE_YEARLY;
			const missing = validateEnv("stripe_pricing");
			expect(missing).toHaveLength(4);
		});
	});

	describe("webhooks group", () => {
		it("checks THREADS_APP_SECRET and META_APP_SECRET", () => {
			delete process.env.THREADS_APP_SECRET;
			delete process.env.META_APP_SECRET;
			const missing = validateEnv("webhooks");
			expect(missing).toContain("THREADS_APP_SECRET");
			expect(missing).toContain("META_APP_SECRET");
		});
	});

	describe("redis group", () => {
		it("checks UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN", () => {
			delete process.env.UPSTASH_REDIS_REST_URL;
			delete process.env.UPSTASH_REDIS_REST_TOKEN;
			const missing = validateEnv("redis");
			expect(missing).toContain("UPSTASH_REDIS_REST_URL");
			expect(missing).toContain("UPSTASH_REDIS_REST_TOKEN");
		});
	});

	describe("qstash group", () => {
		it("checks QStash token and signing keys", () => {
			delete process.env.QSTASH_TOKEN;
			delete process.env.QSTASH_CURRENT_SIGNING_KEY;
			delete process.env.QSTASH_NEXT_SIGNING_KEY;
			const missing = validateEnv("qstash");
			expect(missing).toContain("QSTASH_TOKEN");
			expect(missing).toContain("QSTASH_CURRENT_SIGNING_KEY");
			expect(missing).toContain("QSTASH_NEXT_SIGNING_KEY");
		});
	});
});

describe("requireEnv", () => {
	let savedEnv: Record<string, string | undefined>;

	beforeEach(() => {
		savedEnv = {
			SUPABASE_URL: process.env.SUPABASE_URL,
			SUPABASE_SERVICE_ROLE_KEY: process.env.SUPABASE_SERVICE_ROLE_KEY,
			ENCRYPTION_KEY: process.env.ENCRYPTION_KEY,
		};
	});

	afterEach(() => {
		for (const [key, value] of Object.entries(savedEnv)) {
			if (value !== undefined) {
				process.env[key] = value;
			} else {
				delete process.env[key];
			}
		}
	});

	it("does not throw when all required vars are present", () => {
		process.env.SUPABASE_URL = "test";
		process.env.SUPABASE_SERVICE_ROLE_KEY = "test";
		process.env.ENCRYPTION_KEY = "test";
		expect(() => requireEnv("core")).not.toThrow();
	});

	it("throws with descriptive message when vars are missing", () => {
		delete process.env.SUPABASE_URL;
		delete process.env.ENCRYPTION_KEY;
		process.env.SUPABASE_SERVICE_ROLE_KEY = "test";
		expect(() => requireEnv("core")).toThrow("Missing required env vars");
		expect(() => requireEnv("core")).toThrow("SUPABASE_URL");
		expect(() => requireEnv("core")).toThrow("ENCRYPTION_KEY");
	});

	it("lists all missing vars in the error message", () => {
		delete process.env.SUPABASE_URL;
		delete process.env.SUPABASE_SERVICE_ROLE_KEY;
		delete process.env.ENCRYPTION_KEY;
		try {
			requireEnv("core");
			expect.fail("should have thrown");
		} catch (err: unknown) {
			expect((err as Error).message).toContain("SUPABASE_URL");
			expect((err as Error).message).toContain("SUPABASE_SERVICE_ROLE_KEY");
			expect((err as Error).message).toContain("ENCRYPTION_KEY");
		}
	});

	it("does not throw for unknown groups (no vars to check)", () => {
		expect(() => requireEnv("nonexistent")).not.toThrow();
	});
});
