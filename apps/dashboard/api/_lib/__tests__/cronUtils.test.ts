import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TypedSupabaseClient } from "../supabase.js";

/**
 * Tests for cron job utilities — distributed locking and health tracking.
 */

// Mock crypto before importing
vi.mock("crypto", () => ({
	randomUUID: vi.fn().mockReturnValue("test-uuid-1234"),
}));

// Mock logger
vi.mock("../logger.js", () => ({
	logger: {
		debug: vi.fn(),
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
	},
}));

// Helper: create a mock Supabase client
function createMockSupabase(overrides: Record<string, unknown> = {}) {
	const mockFrom = {
		insert: vi.fn().mockReturnValue(Promise.resolve({ error: null })),
		update: vi.fn().mockReturnThis(),
		eq: vi.fn().mockReturnValue(Promise.resolve({ error: null })),
	};

	return {
		rpc: vi.fn().mockResolvedValue({ data: true }),
		from: vi.fn().mockReturnValue(mockFrom),
		_mockFrom: mockFrom,
		...overrides,
	};
}

describe("withCronLock", () => {
	beforeEach(() => {
		vi.resetModules();
	});

	it("executes callback when lock is acquired", async () => {
		const { withCronLock } = await import("../cronUtils.js");
		const supabase = createMockSupabase();
		supabase.rpc.mockResolvedValue({ data: true });

		const callback = vi.fn().mockResolvedValue("result-data");
		const result = await withCronLock(
			supabase as unknown as TypedSupabaseClient,
			"test-job",
			callback,
		);

		expect(result).toEqual({ skipped: false, result: "result-data" });
		expect(callback).toHaveBeenCalledOnce();
		expect(supabase.rpc).toHaveBeenCalledWith("acquire_cron_lock", {
			p_job_name: "test-job",
			p_locked_by: expect.any(String),
			p_ttl_seconds: 55,
		});
	});

	it("skips execution when lock is not acquired", async () => {
		const { withCronLock } = await import("../cronUtils.js");
		const supabase = createMockSupabase();
		supabase.rpc.mockResolvedValue({ data: false });

		const callback = vi.fn();
		const result = await withCronLock(
			supabase as unknown as TypedSupabaseClient,
			"test-job",
			callback,
		);

		expect(result).toEqual({ skipped: true });
		expect(callback).not.toHaveBeenCalled();
	});

	it("releases lock even when callback throws", async () => {
		const { withCronLock } = await import("../cronUtils.js");
		const supabase = createMockSupabase();
		supabase.rpc
			.mockResolvedValueOnce({ data: true }) // acquire
			.mockResolvedValueOnce({ data: true }); // release

		const callback = vi.fn().mockRejectedValue(new Error("callback failed"));

		await expect(
			withCronLock(
				supabase as unknown as TypedSupabaseClient,
				"test-job",
				callback,
			),
		).rejects.toThrow("callback failed");

		// Verify release_cron_lock was called
		expect(supabase.rpc).toHaveBeenCalledTimes(2);
		expect(supabase.rpc).toHaveBeenLastCalledWith("release_cron_lock", {
			p_job_name: "test-job",
			p_locked_by: expect.any(String),
		});
	});

	it("releases lock on success", async () => {
		const { withCronLock } = await import("../cronUtils.js");
		const supabase = createMockSupabase();
		supabase.rpc
			.mockResolvedValueOnce({ data: true })
			.mockResolvedValueOnce({ data: true });

		await withCronLock(
			supabase as unknown as TypedSupabaseClient,
			"test-job",
			async () => "done",
		);

		expect(supabase.rpc).toHaveBeenCalledTimes(2);
		expect(supabase.rpc).toHaveBeenLastCalledWith(
			"release_cron_lock",
			expect.any(Object),
		);
	});
});

describe("trackCronRun", () => {
	beforeEach(() => {
		vi.resetModules();
	});

	it("records success on normal execution", async () => {
		const { trackCronRun } = await import("../cronUtils.js");
		const mockFrom = {
			insert: vi.fn().mockReturnValue(Promise.resolve({ error: null })),
			update: vi.fn().mockReturnThis(),
			eq: vi.fn().mockReturnValue(Promise.resolve({ error: null })),
		};
		const supabase = { from: vi.fn().mockReturnValue(mockFrom) };

		const result = await trackCronRun(
			supabase as unknown as TypedSupabaseClient,
			"test-job",
			async () => ({
				itemsProcessed: 5,
			}),
		);

		expect(result).toEqual({ itemsProcessed: 5 });

		// Should insert a "running" record
		expect(supabase.from).toHaveBeenCalledWith("cron_runs");
		expect(mockFrom.insert).toHaveBeenCalledWith(
			expect.objectContaining({ job_name: "test-job", status: "running" }),
		);

		// Should update to "success"
		expect(mockFrom.update).toHaveBeenCalledWith(
			expect.objectContaining({ status: "success", items_processed: 5 }),
		);
	});

	it("records failure when callback throws", async () => {
		const { trackCronRun } = await import("../cronUtils.js");
		const mockFrom = {
			insert: vi.fn().mockReturnValue(Promise.resolve({ error: null })),
			update: vi.fn().mockReturnThis(),
			eq: vi.fn().mockReturnValue(Promise.resolve({ error: null })),
		};
		const supabase = { from: vi.fn().mockReturnValue(mockFrom) };

		await expect(
			trackCronRun(
				supabase as unknown as TypedSupabaseClient,
				"test-job",
				async () => {
					throw new Error("job failed");
				},
			),
		).rejects.toThrow("job failed");

		// Should update to "failed" with error message
		expect(mockFrom.update).toHaveBeenCalledWith(
			expect.objectContaining({ status: "failed", error: "job failed" }),
		);
	});

	it("re-throws the original error", async () => {
		const { trackCronRun } = await import("../cronUtils.js");
		const mockFrom = {
			insert: vi.fn().mockReturnValue(Promise.resolve({ error: null })),
			update: vi.fn().mockReturnThis(),
			eq: vi.fn().mockReturnValue(Promise.resolve({ error: null })),
		};
		const supabase = { from: vi.fn().mockReturnValue(mockFrom) };

		const originalError = new Error("original");
		await expect(
			trackCronRun(
				supabase as unknown as TypedSupabaseClient,
				"test-job",
				async () => {
					throw originalError;
				},
			),
		).rejects.toBe(originalError);
	});

	it("passes metadata to the success update", async () => {
		const { trackCronRun } = await import("../cronUtils.js");
		const mockFrom = {
			insert: vi.fn().mockReturnValue(Promise.resolve({ error: null })),
			update: vi.fn().mockReturnThis(),
			eq: vi.fn().mockReturnValue(Promise.resolve({ error: null })),
		};
		const supabase = { from: vi.fn().mockReturnValue(mockFrom) };

		await trackCronRun(
			supabase as unknown as TypedSupabaseClient,
			"test-job",
			async () => ({
				itemsProcessed: 3,
				metadata: { workspacesChecked: 10 },
			}),
		);

		expect(mockFrom.update).toHaveBeenCalledWith(
			expect.objectContaining({
				status: "success",
				items_processed: 3,
				metadata: { workspacesChecked: 10 },
			}),
		);
	});
});
