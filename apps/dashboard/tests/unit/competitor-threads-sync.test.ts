import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

/**
 * Unit tests for POST /api/competitors?action=sync | queue-sync-all
 *
 * Tests:
 * - handleSync: single competitor sync (profile update + snapshot + posts)
 * - handleQueueSyncAll: queuing a bulk sync job for all competitors
 */

// ---------------------------------------------------------------------------
// Mocks — set up before module import
// ---------------------------------------------------------------------------

const mockGetAuthUserOrError = vi.fn();
const mockParseBodyOrError = vi.fn();

vi.mock("../../api/_lib/apiResponse", () => ({
	apiError: (res: any, status: number, message: string, opts?: any) =>
		res.status(status).json({ success: false, error: message, ...opts }),
	apiSuccess: (res: any, data: Record<string, unknown>) =>
		res.status(200).json({ success: true, ...data }),
	getAuthUserOrError: (...args: unknown[]) => mockGetAuthUserOrError(...args),
}));

vi.mock("../../api/_lib/validation", () => ({
	CompetitorSyncSchema: { parse: vi.fn() },
	parseBodyOrError: (...args: unknown[]) => mockParseBodyOrError(...args),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

vi.mock("../../api/_lib/rateLimiter", () => ({
	checkRateLimit: vi.fn().mockResolvedValue({ allowed: true, remaining: 99 }),
}));

const mockGetAllAccessTokens = vi.fn();
const mockTryWithFallbackTokens = vi.fn();
const mockFetchAndStorePosts = vi.fn();
const mockVerifyCompetitorOwnership = vi.fn();
const mockGetUserCurrentCompetitorJob = vi.fn();
const mockQueueCompetitorSyncJob = vi.fn();
const mockDbFrom = vi.fn();

vi.mock("../../api/_lib/handlers/competitors/shared", () => ({
	getAllAccessTokens: (...args: unknown[]) => mockGetAllAccessTokens(...args),
	tryWithFallbackTokens: (...args: unknown[]) =>
		mockTryWithFallbackTokens(...args),
	fetchAndStorePosts: (...args: unknown[]) =>
		mockFetchAndStorePosts(...args),
	verifyCompetitorOwnership: (...args: unknown[]) =>
		mockVerifyCompetitorOwnership(...args),
	getUserCurrentCompetitorJob: (...args: unknown[]) =>
		mockGetUserCurrentCompetitorJob(...args),
	queueCompetitorSyncJob: (...args: unknown[]) =>
		mockQueueCompetitorSyncJob(...args),
	db: () => ({ from: (...args: unknown[]) => mockDbFrom(...args) }),
}));

const mockGetRedis = vi.fn();
vi.mock("../../api/_lib/redis", () => ({
	getRedis: () => mockGetRedis(),
}));

// Import module under test AFTER mocks
const { handleSync, handleQueueSyncAll } = await import(
	"../../api/_lib/handlers/competitors/threads/sync"
);
const invokeHandleSync = handleSync as unknown as (req: any, res: any) => Promise<void>;
const invokeHandleQueueSyncAll = handleQueueSyncAll as unknown as (req: any, res: any) => Promise<void>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeReq(body: Record<string, unknown> = {}) {
	return {
		method: "POST",
		query: { action: "sync" },
		body,
		headers: { authorization: "Bearer test-token" },
	} as any;
}

function setupDbChain() {
	// Chain for update + upsert operations
	const chain: any = {};
	chain.update = vi.fn().mockReturnValue(chain);
	chain.upsert = vi.fn().mockResolvedValue({ error: null });
	chain.eq = vi.fn().mockReturnValue(chain);
	chain.select = vi.fn().mockReturnValue(chain);
	chain.order = vi.fn().mockReturnValue(chain);
	chain.limit = vi.fn().mockResolvedValue({ data: [], error: null });
	chain.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });

	mockDbFrom.mockReturnValue(chain);
	return chain;
}

const SYNC_PROFILE_DATA = {
	username: "competitor1",
	name: "Competitor One",
	profile_picture_url: "https://example.com/pic.jpg",
	biography: "bio",
	follower_count: 5000,
	is_verified: false,
	likes_count: 100,
	quotes_count: 10,
	replies_count: 20,
	reposts_count: 30,
	views_count: 3000,
};

// ---------------------------------------------------------------------------
// Tests — handleSync
// ---------------------------------------------------------------------------

describe("competitor threads sync handler (handleSync)", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetAuthUserOrError.mockResolvedValue({ id: "user-1" });
		mockParseBodyOrError.mockImplementation((_res: any, _schema: any, body: any) => body);
		mockFetchAndStorePosts.mockResolvedValue({ postsCount: 15 });
	});

	it("short-circuits when user is not authenticated", async () => {
		mockGetAuthUserOrError.mockResolvedValue(null);
		const res = mockRes();
		await invokeHandleSync(makeReq({ competitorId: "comp-1" }), res);
		expect(mockGetAuthUserOrError).toHaveBeenCalled();
	});

	it("short-circuits when body validation fails", async () => {
		mockParseBodyOrError.mockReturnValue(null);
		const res = mockRes();
		await invokeHandleSync(makeReq({}), res);
		expect(mockVerifyCompetitorOwnership).not.toHaveBeenCalled();
	});

	it("returns early when competitor ownership verification fails", async () => {
		mockVerifyCompetitorOwnership.mockResolvedValue(null);
		const res = mockRes();
		await invokeHandleSync(makeReq({ competitorId: "comp-1" }), res);
		expect(mockVerifyCompetitorOwnership).toHaveBeenCalledWith(
			res,
			"comp-1",
			"user-1",
			"*",
		);
		expect(mockGetAllAccessTokens).not.toHaveBeenCalled();
	});

	it("returns 400 when no tokens available", async () => {
		mockVerifyCompetitorOwnership.mockResolvedValue({
			id: "comp-1",
			username: "competitor1",
		});
		mockGetAllAccessTokens.mockResolvedValue([]);

		const res = mockRes();
		await invokeHandleSync(makeReq({ competitorId: "comp-1" }), res);
		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "No connected account" }),
		);
	});

	it("returns 500 when all token attempts fail", async () => {
		mockVerifyCompetitorOwnership.mockResolvedValue({
			id: "comp-1",
			username: "competitor1",
		});
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: null,
			error: "API rate limited",
			tokenIndex: -1,
		});

		const res = mockRes();
		await invokeHandleSync(makeReq({ competitorId: "comp-1" }), res);
		expect(res.status).toHaveBeenCalledWith(500);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "API rate limited" }),
		);
	});

	it("updates competitor, creates snapshot, and fetches posts on success", async () => {
		mockVerifyCompetitorOwnership.mockResolvedValue({
			id: "comp-1",
			username: "competitor1",
		});
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: SYNC_PROFILE_DATA,
			tokenIndex: 0,
		});

		setupDbChain();

		const res = mockRes();
		await invokeHandleSync(makeReq({ competitorId: "comp-1" }), res);

		// Should update competitors table
		expect(mockDbFrom).toHaveBeenCalledWith("competitors");
		// Should upsert snapshot
		expect(mockDbFrom).toHaveBeenCalledWith("competitor_snapshots");
		// Should call fetchAndStorePosts
		expect(mockFetchAndStorePosts).toHaveBeenCalledWith(
			"comp-1",
			"competitor1",
			"token-1",
			"user-1",
		);
		// Should return postsCount
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ success: true, postsCount: 15 }),
		);
	});

	it("uses correct working token from token index", async () => {
		mockVerifyCompetitorOwnership.mockResolvedValue({
			id: "comp-1",
			username: "competitor1",
		});
		mockGetAllAccessTokens.mockResolvedValue(["bad-token", "good-token"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: SYNC_PROFILE_DATA,
			tokenIndex: 1,
		});
		setupDbChain();

		const res = mockRes();
		await invokeHandleSync(makeReq({ competitorId: "comp-1" }), res);

		expect(mockFetchAndStorePosts).toHaveBeenCalledWith(
			"comp-1",
			"competitor1",
			"good-token", // second token
			"user-1",
		);
	});
});

// ---------------------------------------------------------------------------
// Tests — handleQueueSyncAll
// ---------------------------------------------------------------------------

describe("competitor threads queue-sync-all handler", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetAuthUserOrError.mockResolvedValue({ id: "user-1" });
	});

	it("returns 401 when user is not authenticated", async () => {
		mockGetAuthUserOrError.mockResolvedValue(null);
		const res = mockRes();
		await invokeHandleQueueSyncAll(makeReq(), res);
		expect(mockGetAuthUserOrError).toHaveBeenCalled();
	});

	it("returns 503 when Redis is not configured", async () => {
		mockGetRedis.mockReturnValue(null);
		const res = mockRes();
		await invokeHandleQueueSyncAll(makeReq(), res);
		expect(res.status).toHaveBeenCalledWith(503);
	});

	it("returns existing job when one is already queued", async () => {
		mockGetRedis.mockReturnValue({});
		const existingJob = {
			id: "job-1",
			status: "queued",
			competitorIds: ["comp-1"],
		};
		mockGetUserCurrentCompetitorJob.mockResolvedValue(existingJob);

		const res = mockRes();
		await invokeHandleQueueSyncAll(makeReq(), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				queued: false,
				existingJob: true,
			}),
		);
	});

	it("returns existing job when one is processing", async () => {
		mockGetRedis.mockReturnValue({});
		const existingJob = {
			id: "job-1",
			status: "processing",
		};
		mockGetUserCurrentCompetitorJob.mockResolvedValue(existingJob);

		const res = mockRes();
		await invokeHandleQueueSyncAll(makeReq(), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ queued: false, existingJob: true }),
		);
	});

	it("returns no-competitors message when user has none", async () => {
		mockGetRedis.mockReturnValue({});
		mockGetUserCurrentCompetitorJob.mockResolvedValue(null);
		mockDbFrom.mockReturnValue({
			select: vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					or: vi.fn().mockReturnValue({
						order: vi.fn().mockResolvedValue({ data: [] }),
					}),
				}),
			}),
		});

		const res = mockRes();
		await invokeHandleQueueSyncAll(makeReq(), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				queued: false,
				message: "No competitors to sync",
			}),
		);
	});

	it("queues job successfully for all competitors", async () => {
		mockGetRedis.mockReturnValue({});
		mockGetUserCurrentCompetitorJob.mockResolvedValue(null);

		const competitors = [
			{ id: "comp-1", follower_count: 10000 },
			{ id: "comp-2", follower_count: 5000 },
		];
		mockDbFrom.mockImplementation((table: string) => {
			if (table === "competitors") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							or: vi.fn().mockReturnValue({
								order: vi.fn().mockResolvedValue({ data: competitors }),
							}),
						}),
					}),
				};
			}
			if (table === "sync_jobs") {
				return {
					upsert: vi.fn().mockResolvedValue({ error: null }),
				};
			}
			return {};
		});

		const queuedJob = {
			id: "job-new",
			status: "queued",
			createdAt: Date.now(),
		};
		mockQueueCompetitorSyncJob.mockResolvedValue(queuedJob);

		const res = mockRes();
		await invokeHandleQueueSyncAll(makeReq(), res);

		expect(mockQueueCompetitorSyncJob).toHaveBeenCalledWith("user-1", [
			"comp-1",
			"comp-2",
		]);
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				queued: true,
				job: expect.objectContaining({
					id: "job-new",
					competitorCount: 2,
				}),
			}),
		);
	});

	it("proceeds when completed job already exists (not blocking)", async () => {
		mockGetRedis.mockReturnValue({});
		const completedJob = { id: "job-old", status: "completed" };
		mockGetUserCurrentCompetitorJob.mockResolvedValue(completedJob);

		// Should proceed past the existing job check since it's completed
		mockDbFrom.mockReturnValue({
			select: vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					or: vi.fn().mockReturnValue({
						order: vi.fn().mockResolvedValue({ data: [] }),
					}),
				}),
			}),
		});

		const res = mockRes();
		await invokeHandleQueueSyncAll(makeReq(), res);

		// Should not short-circuit with existingJob: true
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				queued: false,
				message: "No competitors to sync",
			}),
		);
	});

	it("returns 500 on unexpected error", async () => {
		mockGetRedis.mockReturnValue({});
		mockGetUserCurrentCompetitorJob.mockRejectedValue(new Error("redis down"));

		const res = mockRes();
		await invokeHandleQueueSyncAll(makeReq(), res);

		expect(res.status).toHaveBeenCalledWith(500);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Internal server error" }),
		);
	});
});
