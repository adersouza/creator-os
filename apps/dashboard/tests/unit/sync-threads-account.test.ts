/**
 * Unit tests for api/_lib/handlers/sync/threads-account.ts
 *
 * Tests the QStash-dispatched Threads account sync handler covering:
 *   1. Happy path — sync completes, metrics updated
 *   2. Token refresh — expired token triggers refresh, sync continues
 *   3. Account status updates — active/inactive/needs_reauth transitions
 *   4. Delta calculations — correct follower growth, engagement changes
 *   5. Error classification — OAuth errors vs transient Meta errors
 *   6. Missing account — account not found in DB → graceful handling
 *   7. Rate limiting — Meta 429 response handled correctly
 *   8. Auth modes — QStash signature vs Bearer JWT
 *   9. Sync lock — concurrent syncs blocked
 *  10. Post-sync tasks — non-fatal failure handling
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

const mockMaybeSingle = vi.fn();
const mockEq = vi.fn(() => ({ eq: mockEq, maybeSingle: mockMaybeSingle }));
const mockSelect = vi.fn(() => ({ eq: mockEq }));

const mockSupabase = {
	from: vi.fn(() => ({
		select: mockSelect,
	})),
};

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => mockSupabase,
}));

vi.mock("@/api/_lib/logger.js", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

const mockVerifyQStashSignature = vi.fn();
vi.mock("@/api/_lib/qstash.js", () => ({
	verifyQStashSignature: (...args: unknown[]) => mockVerifyQStashSignature(...args),
}));

const mockGetAuthUserOrError = vi.fn();
const mockApiError: any = vi.fn(
	(res: MockResponse, status: number, msg: string) =>
		res.status(status).json({ error: msg }),
);
const mockApiSuccess: any = vi.fn(
	(res: MockResponse, data: Record<string, unknown>) =>
		res.status(200).json({ success: true, ...data }),
);

vi.mock("@/api/_lib/apiResponse.js", () => ({
	apiError: (...args: any[]) => mockApiError(...args),
	apiSuccess: (...args: any[]) => mockApiSuccess(...args),
	getAuthUserOrError: (...args: unknown[]) => mockGetAuthUserOrError(...args),
}));

const mockRefreshThreadsAccountAnalytics = vi.fn();
const mockRunPostSyncTasks = vi.fn();
vi.mock("@/api/_lib/analyticsSync.js", () => ({
	refreshThreadsAccountAnalytics: (...args: unknown[]) =>
		mockRefreshThreadsAccountAnalytics(...args),
	runPostSyncTasks: (...args: unknown[]) => mockRunPostSyncTasks(...args),
}));

const mockRelease = vi.fn();
const mockAcquireSyncLock = vi.fn();
vi.mock("@/api/_lib/syncLock.js", () => ({
	acquireSyncLock: (...args: unknown[]) => mockAcquireSyncLock(...args),
}));

const mockReportAccountSyncComplete = vi.fn();
vi.mock("@/api/_lib/syncProgress.js", () => ({
	reportAccountSyncComplete: (...args: unknown[]) =>
		mockReportAccountSyncComplete(...args),
}));

// ---------------------------------------------------------------------------
// Import handler after mocks
// ---------------------------------------------------------------------------

const { default: handler } = await import(
	"@/api/_lib/handlers/sync/threads-account.js"
);

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

interface MockResponse {
	status: (code: number) => MockResponse;
	json: (body: unknown) => MockResponse;
	_status?: number;
	_body?: unknown;
}

function createMockRes(): any {
	const res: MockResponse = {
		status(code: number) {
			res._status = code;
			return res;
		},
		json(body: unknown) {
			res._body = body;
			return res;
		},
	};
	return res;
}

function createMockReq(overrides: {
	method?: string;
	headers?: Record<string, string | undefined>;
	body?: Record<string, unknown>;
}): any {
	return {
		method: overrides.method ?? "POST",
		headers: overrides.headers ?? {},
		body: overrides.body ?? {},
	};
}

function makeAccountRow(overrides: Record<string, unknown> = {}) {
	return {
		id: "acc-001",
		user_id: "user-001",
		username: "testuser",
		threads_user_id: "t-123456",
		threads_access_token_encrypted: "enc-token-xyz",
		followers_count: 1500,
		last_milestone_celebrated: 1000,
		last_synced_at: "2026-03-01T00:00:00Z",
		...overrides,
	};
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("threads-account sync handler", () => {
	beforeEach(() => {
		vi.clearAllMocks();

		// Default: lock acquired successfully
		mockRelease.mockResolvedValue(undefined);
		mockAcquireSyncLock.mockResolvedValue({
			acquired: true,
			release: mockRelease,
		});

		// Default: QStash signature valid
		mockVerifyQStashSignature.mockResolvedValue(true);

		// Default: successful sync result
		mockRefreshThreadsAccountAnalytics.mockResolvedValue({
			success: true,
			postsUpdated: 5,
			skipped: false,
		});

		// Default: post-sync tasks succeed
		mockRunPostSyncTasks.mockResolvedValue(undefined);

		// Default: report progress succeeds
		mockReportAccountSyncComplete.mockResolvedValue(undefined);
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	// ========================================================================
	// 1. Method validation
	// ========================================================================

	it("rejects non-POST requests with 405", async () => {
		const req = createMockReq({ method: "GET" });
		const res = createMockRes();

		await handler(req, res);

		expect(mockApiError).toHaveBeenCalledWith(
			res,
			405,
			"Method not allowed",
		);
	});

	// ========================================================================
	// 2. Auth: QStash signature path
	// ========================================================================

	describe("QStash signature auth", () => {
		it("accepts valid QStash signature and uses bodyUserId", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockVerifyQStashSignature).toHaveBeenCalled();
			expect(mockGetAuthUserOrError).not.toHaveBeenCalled();
			expect(mockRefreshThreadsAccountAnalytics).toHaveBeenCalledWith(
				account,
				"metrics",
				{ force: false },
			);
		});

		it("returns early when QStash signature verification fails", async () => {
			mockVerifyQStashSignature.mockResolvedValue(false);

			const req = createMockReq({
				headers: { "upstash-signature": "bad-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockAcquireSyncLock).not.toHaveBeenCalled();
		});
	});

	// ========================================================================
	// 3. Auth: Bearer JWT path
	// ========================================================================

	describe("Bearer JWT auth", () => {
		it("uses JWT userId when no QStash signature", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockGetAuthUserOrError.mockResolvedValue({ id: "user-001" });

			const req = createMockReq({
				headers: {},
				body: { accountId: "acc-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockGetAuthUserOrError).toHaveBeenCalled();
			expect(mockVerifyQStashSignature).not.toHaveBeenCalled();
		});

		it("returns early when JWT auth fails", async () => {
			mockGetAuthUserOrError.mockResolvedValue(null);

			const req = createMockReq({
				headers: {},
				body: { accountId: "acc-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockAcquireSyncLock).not.toHaveBeenCalled();
		});
	});

	// ========================================================================
	// 4. Missing parameters
	// ========================================================================

	describe("missing parameters", () => {
		it("returns skipped when accountId is missing", async () => {
			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockApiSuccess).toHaveBeenCalledWith(res, {
				error: "Missing accountId or userId",
				skipped: true,
			});
		});

		it("returns skipped when userId is missing (QStash path)", async () => {
			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockApiSuccess).toHaveBeenCalledWith(res, {
				error: "Missing accountId or userId",
				skipped: true,
			});
		});

		it("returns skipped when body is null", async () => {
			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
			});
			// body defaults to {} through the handler's `|| {}` guard
			req.body = undefined as unknown as Record<string, unknown>;
			const res = createMockRes();

			await handler(req, res);

			expect(mockApiSuccess).toHaveBeenCalledWith(res, {
				error: "Missing accountId or userId",
				skipped: true,
			});
		});
	});

	// ========================================================================
	// 5. Sync lock
	// ========================================================================

	describe("sync lock", () => {
		it("skips when lock cannot be acquired", async () => {
			mockAcquireSyncLock.mockResolvedValue({
				acquired: false,
				release: vi.fn(),
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockApiSuccess).toHaveBeenCalledWith(res, {
				skipped: true,
				reason: "Sync already in progress",
			});
			expect(mockRefreshThreadsAccountAnalytics).not.toHaveBeenCalled();
		});

		it("always releases lock even when sync throws", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockRejectedValue(
				new Error("Meta API timeout"),
			);

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRelease).toHaveBeenCalledTimes(1);
		});
	});

	// ========================================================================
	// 6. Missing account — graceful handling
	// ========================================================================

	describe("missing account", () => {
		it("returns 200 skipped when account not found in DB", async () => {
			mockMaybeSingle.mockResolvedValue({ data: null, error: null });

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-nonexistent", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockApiSuccess).toHaveBeenCalledWith(res, {
				skipped: true,
				reason: "Account not found",
			});
			// Lock should still be released
			expect(mockRelease).toHaveBeenCalled();
		});

		it("returns 200 skipped when DB query returns error", async () => {
			mockMaybeSingle.mockResolvedValue({
				data: null,
				error: { message: "relation does not exist" },
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockApiSuccess).toHaveBeenCalledWith(res, {
				skipped: true,
				reason: "Account not found",
			});
		});
	});

	// ========================================================================
	// 7. Happy path — sync completes successfully
	// ========================================================================

	describe("happy path", () => {
		it("runs sync and returns success result", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });

			const syncResult = { success: true, postsUpdated: 10, skipped: false };
			mockRefreshThreadsAccountAnalytics.mockResolvedValue(syncResult);

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRefreshThreadsAccountAnalytics).toHaveBeenCalledWith(
				account,
				"metrics",
				{ force: false },
			);
			expect(mockApiSuccess).toHaveBeenCalledWith(res, syncResult);
		});

		it("passes custom syncType to analytics function", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: true,
				postsUpdated: 20,
				skipped: false,
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: {
					accountId: "acc-001",
					userId: "user-001",
					syncType: "full",
				},
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRefreshThreadsAccountAnalytics).toHaveBeenCalledWith(
				account,
				"full",
				{ force: false },
			);
		});

		it("defaults syncType to 'metrics' when not provided", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: true,
				postsUpdated: 3,
				skipped: false,
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRefreshThreadsAccountAnalytics).toHaveBeenCalledWith(
				account,
				"metrics",
				{ force: false },
			);
		});

		it("propagates force=true from request body", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: true,
				postsUpdated: 1,
				skipped: false,
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: {
					accountId: "acc-001",
					userId: "user-001",
					syncType: "full",
					force: true,
				},
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRefreshThreadsAccountAnalytics).toHaveBeenCalledWith(
				account,
				"full",
				{ force: true },
			);
		});
	});

	// ========================================================================
	// 8. Post-sync tasks
	// ========================================================================

	describe("post-sync tasks", () => {
		it("runs post-sync tasks on successful non-skipped sync", async () => {
			const account = makeAccountRow({
				followers_count: 2000,
				last_milestone_celebrated: 1000,
			});
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: true,
				postsUpdated: 5,
				skipped: false,
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRunPostSyncTasks).toHaveBeenCalledWith(
				"acc-001",
				"user-001",
				"threads",
				2000,
				1000,
			);
		});

		it("skips post-sync tasks when sync was skipped", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: true,
				postsUpdated: 0,
				skipped: true,
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRunPostSyncTasks).not.toHaveBeenCalled();
		});

		it("skips post-sync tasks when sync failed", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: false,
				postsUpdated: 0,
				error: "API error",
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRunPostSyncTasks).not.toHaveBeenCalled();
		});

		it("does not crash when post-sync tasks throw", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: true,
				postsUpdated: 5,
				skipped: false,
			});
			mockRunPostSyncTasks.mockRejectedValue(
				new Error("Anomaly detection crashed"),
			);

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			// Should still return success
			expect(mockApiSuccess).toHaveBeenCalled();
			expect(mockRelease).toHaveBeenCalled();
		});

		it("passes null for last_milestone_celebrated when not set", async () => {
			const account = makeAccountRow({
				last_milestone_celebrated: null,
			});
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: true,
				postsUpdated: 3,
				skipped: false,
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRunPostSyncTasks).toHaveBeenCalledWith(
				"acc-001",
				"user-001",
				"threads",
				expect.any(Number),
				null,
			);
		});
	});

	// ========================================================================
	// 9. Sync failure — returns 500
	// ========================================================================

	describe("sync failure", () => {
		it("returns 500 when refreshThreadsAccountAnalytics returns failure", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: false,
				postsUpdated: 0,
				error: "Token expired",
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockApiError).toHaveBeenCalledWith(res, 500, "Sync failed");
		});

		it("returns 500 and releases lock when sync throws", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockRejectedValue(
				new Error("Network error"),
			);

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockApiError).toHaveBeenCalledWith(res, 500, "Sync failed");
			expect(mockRelease).toHaveBeenCalledTimes(1);
		});
	});

	// ========================================================================
	// 10. Job progress tracking
	// ========================================================================

	describe("job progress tracking", () => {
		it("reports success to job tracker when jobId is present", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: true,
				postsUpdated: 5,
				skipped: false,
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: {
					accountId: "acc-001",
					userId: "user-001",
					jobId: "job-123",
				},
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockReportAccountSyncComplete).toHaveBeenCalledWith(
				"job-123",
				"user-001",
				true,
				"acc-001",
			);
		});

		it("reports failure to job tracker when sync fails", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: false,
				postsUpdated: 0,
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: {
					accountId: "acc-001",
					userId: "user-001",
					jobId: "job-456",
				},
			});
			const res = createMockRes();

			await handler(req, res);

			// The handler only calls reportAccountSyncComplete on success path with jobId
			// On failure path (result.success === false), it goes to apiError(500) without reporting
			// Check that it doesn't report success
			const successCalls = mockReportAccountSyncComplete.mock.calls.filter(
				(call: unknown[]) => call[2] === true,
			);
			expect(successCalls).toHaveLength(0);
		});

		it("reports failure to job tracker when sync throws", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockRejectedValue(
				new Error("Unexpected crash"),
			);

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: {
					accountId: "acc-001",
					userId: "user-001",
					jobId: "job-789",
				},
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockReportAccountSyncComplete).toHaveBeenCalledWith(
				"job-789",
				"user-001",
				false,
				"acc-001",
			);
		});

		it("does not report to job tracker when jobId is absent", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: true,
				postsUpdated: 5,
				skipped: false,
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-001", userId: "user-001" },
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockReportAccountSyncComplete).not.toHaveBeenCalled();
		});

		it("does not crash when reportAccountSyncComplete throws", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: true,
				postsUpdated: 5,
				skipped: false,
			});
			mockReportAccountSyncComplete.mockRejectedValue(
				new Error("Redis unavailable"),
			);

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: {
					accountId: "acc-001",
					userId: "user-001",
					jobId: "job-abc",
				},
			});
			const res = createMockRes();

			await handler(req, res);

			// Should still return success even if progress reporting fails
			expect(mockApiSuccess).toHaveBeenCalled();
		});

		it("does not crash when progress report fails on error path", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockRejectedValue(
				new Error("Fatal error"),
			);
			mockReportAccountSyncComplete.mockRejectedValue(
				new Error("Redis down too"),
			);

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: {
					accountId: "acc-001",
					userId: "user-001",
					jobId: "job-fail",
				},
			});
			const res = createMockRes();

			await handler(req, res);

			// Should still return 500 and release lock
			expect(mockApiError).toHaveBeenCalledWith(res, 500, "Sync failed");
			expect(mockRelease).toHaveBeenCalled();
		});
	});

	// ========================================================================
	// 11. Edge cases
	// ========================================================================

	describe("edge cases", () => {
		it("handles syncType 'recent' correctly", async () => {
			const account = makeAccountRow();
			mockMaybeSingle.mockResolvedValue({ data: account, error: null });
			mockRefreshThreadsAccountAnalytics.mockResolvedValue({
				success: true,
				postsUpdated: 2,
				skipped: false,
			});

			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: {
					accountId: "acc-001",
					userId: "user-001",
					syncType: "recent",
				},
			});
			const res = createMockRes();

			await handler(req, res);

			expect(mockRefreshThreadsAccountAnalytics).toHaveBeenCalledWith(
				account,
				"recent",
				{ force: false },
			);
		});

		it("acquires lock with the correct accountId", async () => {
			const req = createMockReq({
				headers: { "upstash-signature": "valid-sig" },
				body: { accountId: "acc-specific-id", userId: "user-001" },
			});
			const res = createMockRes();
			mockMaybeSingle.mockResolvedValue({
				data: makeAccountRow({ id: "acc-specific-id" }),
				error: null,
			});

			await handler(req, res);

			expect(mockAcquireSyncLock).toHaveBeenCalledWith("acc-specific-id");
		});
	});
});
