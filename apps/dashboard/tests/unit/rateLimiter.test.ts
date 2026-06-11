import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock Redis with in-memory state to verify atomic behavior
const store: Record<string, { value: number; ttl: number | null }> = {};

const mockRedis = {
	eval: vi.fn(
		async (
			_script: string,
			keys: string[],
			args: string[],
		): Promise<[number, number]> => {
			const key = keys[0];
			const window = parseInt(args[0], 10);

			// Simulate the Lua script behavior
			if (!store[key]) {
				store[key] = { value: 0, ttl: null };
			}
			store[key].value += 1;
			const current = store[key].value;

			// TTL < 0 means no TTL set (new key or orphaned)
			if (store[key].ttl === null || store[key].ttl! < 0) {
				store[key].ttl = window;
			}

			return [current, store[key].ttl!];
		},
	),
};

vi.mock("../../api/_lib/redis.js", () => ({
	getRedis: () => mockRedis,
}));

vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		warn: vi.fn(),
		error: vi.fn(),
		info: vi.fn(),
	},
}));

describe("rateLimiter", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		Object.keys(store).forEach((k) => delete store[k]);
	});

	it("allows requests within the limit", async () => {
		const { checkRateLimit } = await import("../../api/_lib/rateLimiter.js");

		const result = await checkRateLimit({
			key: "test:action:user1",
			limit: 5,
			windowSeconds: 60,
			failMode: "open",
		});

		expect(result.allowed).toBe(true);
		expect(result.remaining).toBe(4);
	});

	it("blocks requests exceeding the limit", async () => {
		const { checkRateLimit } = await import("../../api/_lib/rateLimiter.js");

		// Fill up the limit
		for (let i = 0; i < 5; i++) {
			await checkRateLimit({
				key: "test:action:user2",
				limit: 5,
				windowSeconds: 60,
				failMode: "open",
			});
		}

		// 6th request should be blocked
		const result = await checkRateLimit({
			key: "test:action:user2",
			limit: 5,
			windowSeconds: 60,
			failMode: "open",
		});

		expect(result.allowed).toBe(false);
		expect(result.remaining).toBe(0);
		expect(result.reason).toBe("exceeded");
		expect(result.retryAfterSeconds).toBeGreaterThan(0);
	});

	it("uses atomic Lua eval instead of separate INCR + EXPIRE", async () => {
		const { checkRateLimit } = await import("../../api/_lib/rateLimiter.js");

		await checkRateLimit({
			key: "test:action:user3",
			limit: 10,
			windowSeconds: 60,
			failMode: "open",
		});

		// Should use eval (atomic), not separate incr + expire
		expect(mockRedis.eval).toHaveBeenCalledTimes(1);
		const [script, keys, args] = mockRedis.eval.mock.calls[0];
		expect(script).toContain("INCR");
		expect(script).toContain("EXPIRE");
		expect(keys).toEqual(["rl:test:action:user3"]);
		expect(args).toEqual(["60"]);
	});

	it("TTL is always set (prevents orphaned keys)", async () => {
		const { checkRateLimit } = await import("../../api/_lib/rateLimiter.js");

		await checkRateLimit({
			key: "test:action:user4",
			limit: 10,
			windowSeconds: 30,
			failMode: "open",
		});

		const entry = store["rl:test:action:user4"];
		expect(entry).toBeDefined();
		expect(entry.ttl).toBe(30);
	});

	it("fails closed when Redis is unavailable and failMode is closed", async () => {
		// Override eval to throw
		mockRedis.eval.mockRejectedValueOnce(new Error("Connection refused"));

		const { checkRateLimit } = await import("../../api/_lib/rateLimiter.js");

		const result = await checkRateLimit({
			key: "test:action:user5",
			limit: 10,
			windowSeconds: 60,
			failMode: "closed",
		});

		expect(result.allowed).toBe(false);
		expect(result.reason).toBe("redis_unavailable");
	});

	it("fails open when Redis is unavailable and failMode is open", async () => {
		mockRedis.eval.mockRejectedValueOnce(new Error("Connection refused"));

		const { checkRateLimit } = await import("../../api/_lib/rateLimiter.js");

		const result = await checkRateLimit({
			key: "test:action:user6",
			limit: 10,
			windowSeconds: 60,
			failMode: "open",
		});

		expect(result.allowed).toBe(true);
	});

	it("different keys are independent", async () => {
		const { checkRateLimit } = await import("../../api/_lib/rateLimiter.js");

		// Fill key A
		for (let i = 0; i < 3; i++) {
			await checkRateLimit({
				key: "replies:sync:userX",
				limit: 3,
				windowSeconds: 60,
				failMode: "open",
			});
		}

		// Key A should be at limit
		const resultA = await checkRateLimit({
			key: "replies:sync:userX",
			limit: 3,
			windowSeconds: 60,
			failMode: "open",
		});
		expect(resultA.allowed).toBe(false);

		// Key B should still have capacity
		const resultB = await checkRateLimit({
			key: "replies:fetch-mentions:userX",
			limit: 3,
			windowSeconds: 60,
			failMode: "open",
		});
		expect(resultB.allowed).toBe(true);
	});
});
