/**
 * Tests for acquireSyncLock — per-account Redis lock preventing
 * concurrent QStash syncs from racing on the same account.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

// Mock Redis before importing the module under test
const mockSet = vi.fn();
const mockDel = vi.fn();

vi.mock("../../api/_lib/redis.js", () => ({
	getRedis: () => ({
		set: mockSet,
		del: mockDel,
	}),
}));

vi.mock("../../api/_lib/logger.js", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

const { acquireSyncLock } = await import("../../api/_lib/syncLock.js");

describe("acquireSyncLock", () => {
	afterEach(() => {
		vi.clearAllMocks();
	});

	it("acquires lock when Redis SET NX succeeds", async () => {
		mockSet.mockResolvedValue("OK");

		const lock = await acquireSyncLock("acc-123");
		expect(lock.acquired).toBe(true);
		expect(mockSet).toHaveBeenCalledWith(
			"sync-lock:acc-123",
			expect.any(String),
			{ nx: true, ex: 55 },
		);
	});

	it("skips when lock is already held", async () => {
		mockSet.mockResolvedValue(null);

		const lock = await acquireSyncLock("acc-123");
		expect(lock.acquired).toBe(false);
	});

	it("release calls DEL on the lock key", async () => {
		mockSet.mockResolvedValue("OK");
		mockDel.mockResolvedValue(1);

		const lock = await acquireSyncLock("acc-456");
		await lock.release();
		expect(mockDel).toHaveBeenCalledWith("sync-lock:acc-456");
	});

	it("release is safe to call even if DEL fails", async () => {
		mockSet.mockResolvedValue("OK");
		mockDel.mockRejectedValue(new Error("Redis down"));

		const lock = await acquireSyncLock("acc-789");
		// Should not throw
		await expect(lock.release()).resolves.toBeUndefined();
	});

	it("fails closed when Redis is unavailable", async () => {
		mockSet.mockRejectedValue(new Error("Connection refused"));

		const lock = await acquireSyncLock("acc-000");
		expect(lock.acquired).toBe(false); // fail-closed
	});

	it("accepts custom TTL", async () => {
		mockSet.mockResolvedValue("OK");

		await acquireSyncLock("acc-ttl", 30);
		expect(mockSet).toHaveBeenCalledWith(
			"sync-lock:acc-ttl",
			expect.any(String),
			{ nx: true, ex: 30 },
		);
	});
});
