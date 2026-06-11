import { beforeEach, describe, expect, it, vi } from "vitest";
import {
	analyticsKey,
	cached,
	cachedWithStale,
	dlqKey,
	healthKey,
	invalidateCache,
	invalidateCachePattern,
	postMetricsKey,
} from "../redisCache.js";

// Mock Redis client
const mockRedis = {
	get: vi.fn(),
	set: vi.fn().mockResolvedValue("OK"),
	del: vi.fn().mockResolvedValue(1),
	scan: vi.fn().mockResolvedValue([0, []]),
};

vi.mock("../redis.js", () => ({
	getRedis: () => mockRedis,
}));

vi.mock("../logger.js", () => ({
	logger: {
		error: vi.fn(),
		warn: vi.fn(),
		log: vi.fn(),
		info: vi.fn(),
		debug: vi.fn(),
	},
}));

describe("cached", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("returns cached value on cache hit", async () => {
		mockRedis.get.mockResolvedValueOnce({ result: "cached" });
		const fn = vi.fn().mockResolvedValue({ result: "fresh" });
		const result = await cached("test-key", 300, fn);
		expect(result).toEqual({ result: "cached" });
		expect(fn).not.toHaveBeenCalled();
	});

	it("calls fn and caches on cache miss", async () => {
		mockRedis.get.mockResolvedValueOnce(null);
		const fn = vi.fn().mockResolvedValue({ result: "computed" });
		const result = await cached("test-key", 300, fn);
		expect(result).toEqual({ result: "computed" });
		expect(fn).toHaveBeenCalledOnce();
		expect(mockRedis.set).toHaveBeenCalledWith(
			"cache:test-key",
			JSON.stringify({ result: "computed" }),
			{ ex: 300 },
		);
	});

	it("prefixes key with 'cache:'", async () => {
		mockRedis.get.mockResolvedValueOnce(null);
		const fn = vi.fn().mockResolvedValue("value");
		await cached("my-key", 60, fn);
		expect(mockRedis.get).toHaveBeenCalledWith("cache:my-key");
	});

	it("falls through to fn when Redis is down", async () => {
		mockRedis.get.mockRejectedValueOnce(new Error("Redis connection refused"));
		const fn = vi.fn().mockResolvedValue("fallback");
		const result = await cached("test-key", 300, fn);
		expect(result).toBe("fallback");
	});

	it("treats undefined cached value as cache miss", async () => {
		mockRedis.get.mockResolvedValueOnce(undefined);
		const fn = vi.fn().mockResolvedValue("computed");
		const result = await cached("key", 300, fn);
		expect(result).toBe("computed");
		expect(fn).toHaveBeenCalled();
	});

	it("does not block on cache write failure", async () => {
		mockRedis.get.mockResolvedValueOnce(null);
		mockRedis.set.mockRejectedValueOnce(new Error("write fail"));
		const fn = vi.fn().mockResolvedValue("value");
		// Should not throw even if set fails
		const result = await cached("key", 300, fn);
		expect(result).toBe("value");
	});
});

describe("invalidateCache", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("deletes the correct key with prefix", async () => {
		await invalidateCache("my-key");
		expect(mockRedis.del).toHaveBeenCalledWith("cache:my-key");
	});

	it("does not throw on Redis error", async () => {
		mockRedis.del.mockRejectedValueOnce(new Error("fail"));
		await expect(invalidateCache("key")).resolves.not.toThrow();
	});
});

describe("invalidateCachePattern", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("scans with correct pattern prefix", async () => {
		mockRedis.scan.mockResolvedValueOnce([0, []]);
		await invalidateCachePattern("analytics:*");
		expect(mockRedis.scan).toHaveBeenCalledWith(0, {
			match: "cache:analytics:*",
			count: 100,
		});
	});

	it("deletes found keys", async () => {
		mockRedis.scan.mockResolvedValueOnce([
			0,
			["cache:analytics:a", "cache:analytics:b"],
		]);
		await invalidateCachePattern("analytics:*");
		expect(mockRedis.del).toHaveBeenCalledTimes(2);
	});

	it("handles pagination with multiple scan iterations", async () => {
		mockRedis.scan
			.mockResolvedValueOnce([42, ["cache:key1"]])
			.mockResolvedValueOnce([0, ["cache:key2"]]);
		await invalidateCachePattern("*");
		expect(mockRedis.del).toHaveBeenCalledTimes(2);
	});

	it("does not throw on Redis error", async () => {
		mockRedis.scan.mockRejectedValueOnce(new Error("fail"));
		await expect(invalidateCachePattern("*")).resolves.not.toThrow();
	});
});

describe("cachedWithStale", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("returns fresh data from primary cache", async () => {
		mockRedis.get.mockResolvedValueOnce({ data: "primary" });
		const fn = vi.fn();
		const result = await cachedWithStale("key", 60, 3600, fn);
		expect(result).toEqual({ data: { data: "primary" }, stale: false });
		expect(fn).not.toHaveBeenCalled();
	});

	it("computes and caches both primary and stale on miss", async () => {
		mockRedis.get.mockResolvedValueOnce(null);
		const fn = vi.fn().mockResolvedValue({ data: "fresh" });
		const result = await cachedWithStale("key", 60, 3600, fn);
		expect(result).toEqual({ data: { data: "fresh" }, stale: false });
		expect(mockRedis.set).toHaveBeenCalledTimes(2);
	});

	it("returns stale data when upstream fails", async () => {
		mockRedis.get
			.mockResolvedValueOnce(null) // primary miss
			.mockResolvedValueOnce({ data: "stale" }); // stale hit
		const fn = vi.fn().mockRejectedValue(new Error("upstream fail"));
		const result = await cachedWithStale("key", 60, 3600, fn);
		expect(result).toEqual({ data: { data: "stale" }, stale: true });
	});

	it("rethrows when both upstream and stale fail", async () => {
		mockRedis.get.mockResolvedValueOnce(null).mockResolvedValueOnce(null); // no stale
		const fn = vi.fn().mockRejectedValue(new Error("upstream fail"));
		// When Redis itself is working but no stale data, the upstream error is rethrown
		// However the outer catch will call fn() again which will fail, then propagate
		// Actually: the outer catch calls fn() directly, which fails again
		await expect(cachedWithStale("key", 60, 3600, fn)).rejects.toThrow(
			"upstream fail",
		);
	});

	it("falls through to direct computation when Redis is completely down", async () => {
		mockRedis.get.mockRejectedValueOnce(new Error("Redis down"));
		const fn = vi.fn().mockResolvedValue("direct");
		const result = await cachedWithStale("key", 60, 3600, fn);
		expect(result).toEqual({ data: "direct", stale: false });
	});
});

describe("cache key helpers", () => {
	it("analyticsKey formats correctly", () => {
		expect(analyticsKey("acc1", "30d")).toBe("analytics:acc1:30d");
	});

	it("postMetricsKey formats correctly", () => {
		expect(postMetricsKey("post123")).toBe("post-metrics:post123");
	});

	it("healthKey returns admin:health", () => {
		expect(healthKey()).toBe("admin:health");
	});

	it("dlqKey returns admin:dlq", () => {
		expect(dlqKey()).toBe("admin:dlq");
	});
});
