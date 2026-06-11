/**
 * metaAppUsageCache — cross-invocation backpressure
 *
 * Tests:
 * - checkMetaAppUsage() writes the latest maxPct to Redis (non-blocking)
 * - readCachedMetaUsage() returns null when key absent
 * - readCachedMetaUsage() returns null when entry is stale (> 5 min)
 * - readCachedMetaUsage() returns the cached value when fresh
 * - checkMetaAppUsage() does NOT write to Redis when maxPct === 0 (no header data)
 *
 * vi.mock must be at module scope (Vitest hoists it).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { checkMetaAppUsage } from "../../api/_lib/metaApiConfig";
import { readCachedMetaUsage } from "../../api/_lib/analytics/constants";

const mockSet = vi.fn().mockResolvedValue("OK");
const mockGet = vi.fn().mockResolvedValue(null);

vi.mock("../../api/_lib/redis.js", () => ({
	getRedis: () => ({ set: mockSet, get: mockGet }),
}));

function makeResponse(xAppUsage?: string): Response {
	const headers = new Headers();
	if (xAppUsage) headers.set("x-app-usage", xAppUsage);
	return new Response(null, { status: 200, headers });
}

describe("checkMetaAppUsage — Redis caching", () => {
	beforeEach(() => {
		mockSet.mockReset().mockResolvedValue("OK");
		mockGet.mockReset().mockResolvedValue(null);
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("caches maxPct in Redis when x-app-usage header is present (non-zero)", async () => {
		const res = makeResponse(
			JSON.stringify({ call_count: 45, total_cputime: 20, total_time: 15 }),
		);
		await checkMetaAppUsage(res, "test-context");

		expect(mockSet).toHaveBeenCalledOnce();
		const [key, value, opts] = mockSet.mock.calls[0];
		expect(key).toBe("meta:app-usage:latest");
		const parsed = JSON.parse(value as string);
		// maxPct = max(45, 20, 15) = 45
		expect(parsed.maxPct).toBe(45);
		expect(typeof parsed.ts).toBe("number");
		expect((opts as { ex: number }).ex).toBe(300);
	});

	it("caches the highest of call_count, total_cputime, total_time as maxPct", async () => {
		const res = makeResponse(
			JSON.stringify({ call_count: 30, total_cputime: 82, total_time: 55 }),
		);
		await checkMetaAppUsage(res, "test");

		const parsed = JSON.parse(mockSet.mock.calls[0][1] as string);
		expect(parsed.maxPct).toBe(82); // total_cputime wins
	});

	it("does NOT write to Redis when maxPct === 0 (all metrics zero)", async () => {
		const res = makeResponse(
			JSON.stringify({ call_count: 0, total_cputime: 0, total_time: 0 }),
		);
		await checkMetaAppUsage(res, "test");
		expect(mockSet).not.toHaveBeenCalled();
	});

	it("does NOT write to Redis when x-app-usage header is absent", async () => {
		const res = makeResponse(); // no header
		await checkMetaAppUsage(res, "test");
		expect(mockSet).not.toHaveBeenCalled();
	});

	it("Redis write failure does not throw (non-blocking)", async () => {
		mockSet.mockRejectedValue(new Error("Redis unavailable"));
		const res = makeResponse(
			JSON.stringify({ call_count: 50, total_cputime: 0, total_time: 0 }),
		);
		await expect(checkMetaAppUsage(res, "test")).resolves.not.toThrow();
	});
});

describe("readCachedMetaUsage — cache read helpers", () => {
	beforeEach(() => {
		mockSet.mockReset().mockResolvedValue("OK");
		mockGet.mockReset().mockResolvedValue(null);
	});

	it("returns null when key is absent", async () => {
		mockGet.mockResolvedValue(null);
		const result = await readCachedMetaUsage();
		expect(result).toBeNull();
	});

	it("returns null when cached entry is stale (> 5 minutes old)", async () => {
		const staleTs = Date.now() - 6 * 60 * 1000; // 6 min ago
		mockGet.mockResolvedValue(
			JSON.stringify({ maxPct: 65, ts: staleTs }),
		);
		const result = await readCachedMetaUsage();
		expect(result).toBeNull();
	});

	it("returns null when Redis throws", async () => {
		mockGet.mockRejectedValue(new Error("Redis unavailable"));
		const result = await readCachedMetaUsage();
		expect(result).toBeNull();
	});

	it("returns the cached value when entry is fresh", async () => {
		const freshTs = Date.now() - 30_000; // 30 s ago
		mockGet.mockResolvedValue(
			JSON.stringify({ maxPct: 72, ts: freshTs }),
		);
		const result = await readCachedMetaUsage();
		expect(result).not.toBeNull();
		expect(result?.maxPct).toBe(72);
		expect(result?.ts).toBe(freshTs);
	});

	it("accepts pre-parsed object from Redis (non-string value)", async () => {
		const freshTs = Date.now() - 10_000;
		// Upstash Redis SDK can return already-parsed objects
		mockGet.mockResolvedValue({ maxPct: 55, ts: freshTs });
		const result = await readCachedMetaUsage();
		expect(result?.maxPct).toBe(55);
	});

	it("returns null when entry is exactly at the 5-minute boundary", async () => {
		// Exactly 5 min ago should be stale (> not >=)
		const boundaryTs = Date.now() - 5 * 60 * 1000 - 1;
		mockGet.mockResolvedValue(
			JSON.stringify({ maxPct: 40, ts: boundaryTs }),
		);
		const result = await readCachedMetaUsage();
		expect(result).toBeNull();
	});
});
