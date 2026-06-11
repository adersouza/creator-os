/**
 * Agent Circuit Breaker — Unit Tests
 *
 * Tests the trip logic, hash computation, and status reporting
 * without hitting Redis (mocked).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Mock Redis
// ---------------------------------------------------------------------------

const mockRedis = {
	incr: vi.fn(),
	expire: vi.fn(),
	del: vi.fn(),
	get: vi.fn(),
	set: vi.fn(),
};

vi.mock("../../api/_lib/redis.js", () => ({
	getRedis: () => mockRedis,
}));

// Mock Supabase
const mockUpdate = vi.fn().mockReturnValue({ eq: vi.fn() });
vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabase: () => ({
		from: () => ({
			update: mockUpdate,
		}),
	}),
}));

// Mock createNotification
vi.mock("../../api/_lib/createNotification.js", () => ({
	createNotification: vi.fn(),
}));

// Mock alerting
vi.mock("../../api/_lib/alerting.js", () => ({
	alert: vi.fn(),
	AlertLevel: { CRITICAL: "critical" },
}));

import {
	checkAndRecord,
	checkSessionCallLimit,
	getStatus,
	reset,
	computeParamsHash,
} from "../../api/_lib/agentCircuitBreaker.js";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("agentCircuitBreaker", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockRedis.incr.mockResolvedValue(1);
		mockRedis.expire.mockResolvedValue(true);
		mockRedis.del.mockResolvedValue(1);
		mockRedis.get.mockResolvedValue(null);
		mockRedis.set.mockResolvedValue("OK");
	});

	describe("checkAndRecord", () => {
		it("returns null when all counters are within limits", async () => {
			mockRedis.incr.mockResolvedValue(5); // Low count
			const result = await checkAndRecord(
				"user-1",
				"get_posts",
				"hash-1",
				true,
			);
			expect(result).toBeNull();
		});

		it("trips on hourly call limit exceeded", async () => {
			mockRedis.incr.mockResolvedValueOnce(251); // Hourly > 250
			const result = await checkAndRecord(
				"user-1",
				"get_posts",
				"hash-1",
				true,
			);
			expect(result).not.toBeNull();
			expect(result!.condition).toBe("hourly_limit");
			expect(result!.actual).toBe(251);
		});

		it("trips on consecutive publish failures", async () => {
			// First incr for hourly (under limit)
			mockRedis.incr.mockResolvedValueOnce(5);
			// Second incr for fail streak
			mockRedis.incr.mockResolvedValueOnce(4); // > 3

			const result = await checkAndRecord(
				"user-1",
				"publish_post",
				"hash-1",
				false, // failure
			);
			expect(result).not.toBeNull();
			expect(result!.condition).toBe("consecutive_failures");
			expect(result!.actual).toBe(4);
		});

		it("resets fail streak on publish success", async () => {
			mockRedis.incr.mockResolvedValue(5); // Under all limits

			await checkAndRecord(
				"user-1",
				"publish_post",
				"hash-1",
				true, // success
			);

			// Should have called del on the fail streak key
			expect(mockRedis.del).toHaveBeenCalledWith(
				expect.stringContaining("fail-streak"),
			);
		});

		it("does not track fail streak for non-publish tools", async () => {
			mockRedis.incr.mockResolvedValue(1);

			await checkAndRecord(
				"user-1",
				"get_posts",
				"hash-1",
				false,
			);

			// Should NOT have called del on fail streak
			expect(mockRedis.del).not.toHaveBeenCalled();
		});

		it("trips on dedup loop detected", async () => {
			// First incr: hourly (under limit)
			mockRedis.incr.mockResolvedValueOnce(5);
			// Second incr: dedup count > 25
			mockRedis.incr.mockResolvedValueOnce(26);

			const result = await checkAndRecord(
				"user-1",
				"get_posts",
				"hash-1",
				true,
			);
			expect(result).not.toBeNull();
			expect(result!.condition).toBe("dedup_loop");
			expect(result!.actual).toBe(26);
		});

		it("fails open when Redis is unavailable", async () => {
			mockRedis.incr.mockRejectedValue(new Error("Redis down"));

			const result = await checkAndRecord(
				"user-1",
				"publish_post",
				"hash-1",
				true,
			);
			expect(result).toBeNull(); // Fail open
		});

		it("tracks schedule_post as a publish tool", async () => {
			mockRedis.incr.mockResolvedValueOnce(5); // hourly
			mockRedis.incr.mockResolvedValueOnce(4); // fail streak > 3

			const result = await checkAndRecord(
				"user-1",
				"schedule_post",
				"hash-1",
				false,
			);
			expect(result).not.toBeNull();
			expect(result!.condition).toBe("consecutive_failures");
		});

		it("tracks bulk_schedule as a publish tool", async () => {
			mockRedis.incr.mockResolvedValueOnce(5);
			mockRedis.incr.mockResolvedValueOnce(4);

			const result = await checkAndRecord(
				"user-1",
				"bulk_schedule",
				"hash-1",
				false,
			);
			expect(result!.condition).toBe("consecutive_failures");
		});
	});

	describe("computeParamsHash", () => {
		it("produces consistent hashes for same input", () => {
			const h1 = computeParamsHash("publish_post", "/api/posts", "POST");
			const h2 = computeParamsHash("publish_post", "/api/posts", "POST");
			expect(h1).toBe(h2);
		});

		it("produces different hashes for different inputs", () => {
			const h1 = computeParamsHash("publish_post", "/api/posts", "POST");
			const h2 = computeParamsHash("get_posts", "/api/posts", "GET");
			expect(h1).not.toBe(h2);
		});

		it("returns a base-36 string", () => {
			const h = computeParamsHash("test", "/test", "GET");
			expect(h).toMatch(/^-?[0-9a-z]+$/);
		});
	});

	describe("getStatus", () => {
		it("returns default status when no data in Redis", async () => {
			mockRedis.get.mockResolvedValue(null);
			const status = await getStatus("user-1");
			expect(status.tripped).toBe(false);
			expect(status.counters.hourlyCalls).toBe(0);
			expect(status.counters.consecutiveFailures).toBe(0);
			expect(status.counters.hourlyLimit).toBe(250);
			expect(status.counters.failLimit).toBe(3);
		});

		it("returns tripped status with reason", async () => {
			const tripData = {
				reason: {
					condition: "hourly_limit",
					detail: "101 calls",
					threshold: 100,
					actual: 101,
				},
				trippedAt: "2026-03-08T12:00:00Z",
			};

			mockRedis.get
				.mockResolvedValueOnce("42") // hourly calls
				.mockResolvedValueOnce("0") // fail streak
				.mockResolvedValueOnce(JSON.stringify(tripData)); // trip data

			const status = await getStatus("user-1");
			expect(status.tripped).toBe(true);
			expect(status.reason!.condition).toBe("hourly_limit");
			expect(status.trippedAt).toBe("2026-03-08T12:00:00Z");
			expect(status.counters.hourlyCalls).toBe(42);
		});

		it("handles Redis failure gracefully", async () => {
			mockRedis.get.mockRejectedValue(new Error("Redis down"));
			const status = await getStatus("user-1");
			expect(status.tripped).toBe(false);
			expect(status.counters.hourlyCalls).toBe(0);
		});
	});

	describe("checkSessionCallLimit", () => {
		it("allows calls under the session limit", async () => {
			mockRedis.incr.mockResolvedValue(50);
			const result = await checkSessionCallLimit("user-1", "session-abc");
			expect(result.allowed).toBe(true);
			expect(result.count).toBe(50);
			expect(result.limit).toBe(200);
		});

		it("blocks calls over the session limit", async () => {
			mockRedis.incr.mockResolvedValue(201);
			const result = await checkSessionCallLimit("user-1", "session-abc");
			expect(result.allowed).toBe(false);
			expect(result.count).toBe(201);
		});

		it("sets TTL on first call", async () => {
			mockRedis.incr.mockResolvedValue(1);
			await checkSessionCallLimit("user-1", "session-abc");
			expect(mockRedis.expire).toHaveBeenCalledWith(
				expect.stringContaining("session:user-1:session-abc"),
				14400,
			);
		});

		it("fails open when Redis is unavailable", async () => {
			mockRedis.incr.mockRejectedValue(new Error("Redis down"));
			const result = await checkSessionCallLimit("user-1", "session-abc");
			expect(result.allowed).toBe(true);
			expect(result.count).toBe(0);
		});
	});

	describe("reset", () => {
		it("deletes all circuit breaker keys", async () => {
			await reset("user-1");
			expect(mockRedis.del).toHaveBeenCalledTimes(3);
			expect(mockRedis.del).toHaveBeenCalledWith(
				expect.stringContaining("tripped"),
			);
			expect(mockRedis.del).toHaveBeenCalledWith(
				expect.stringContaining("hourly"),
			);
			expect(mockRedis.del).toHaveBeenCalledWith(
				expect.stringContaining("fail-streak"),
			);
		});

		it("handles Redis failure gracefully", async () => {
			mockRedis.del.mockRejectedValue(new Error("Redis down"));
			// Should not throw
			await expect(reset("user-1")).resolves.toBeUndefined();
		});
	});
});
