import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

/**
 * Unit tests for competitor top posts handlers:
 * - handleFetchTopPosts (POST /api/competitors?action=fetch-top-posts)
 * - handleGetTopPosts   (GET  /api/competitors?action=top-posts)
 * - handleAggregatedTopPosts (GET /api/competitors?action=aggregated-top-posts)
 */

// ---------------------------------------------------------------------------
// Mocks — set up before module import
// ---------------------------------------------------------------------------

const mockGetAuthUserOrError = vi.fn();
const mockParseBodyOrError = vi.fn();

vi.mock("../../api/_lib/apiResponse", () => ({
	apiError: (res: any, status: number, message: string) =>
		res.status(status).json({ success: false, error: message }),
	apiSuccess: (res: any, data: Record<string, unknown>) =>
		res.status(200).json({ success: true, ...data }),
	getAuthUserOrError: (...args: unknown[]) => mockGetAuthUserOrError(...args),
}));

vi.mock("../../api/_lib/validation", () => ({
	CompetitorFetchTopPostsSchema: { parse: vi.fn() },
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

const mockFetchAndStorePosts = vi.fn();
const mockGetAccessToken = vi.fn();
const mockDbFrom = vi.fn();

vi.mock("../../api/_lib/handlers/competitors/shared", () => ({
	fetchAndStorePosts: (...args: unknown[]) =>
		mockFetchAndStorePosts(...args),
	getAccessToken: (...args: unknown[]) => mockGetAccessToken(...args),
	db: () => ({ from: (...args: unknown[]) => mockDbFrom(...args) }),
}));

const mockVerifyCompetitorOwnership = vi.fn();
vi.mock("../../api/_lib/handlers/helpers/verifyOwnership", () => ({
	verifyCompetitorOwnership: (...args: unknown[]) =>
		mockVerifyCompetitorOwnership(...args),
}));

// Mock redisCache - cached() should just call the factory fn directly
vi.mock("../../api/_lib/redisCache", () => ({
	cached: async (_key: string, _ttl: number, fn: () => Promise<unknown>) =>
		fn(),
}));

// Import module under test AFTER mocks
const { handleFetchTopPosts, handleGetTopPosts, handleAggregatedTopPosts } =
	await import("../../api/_lib/handlers/competitors/threads/posts");
const invokeHandleFetchTopPosts = handleFetchTopPosts as unknown as (req: any, res: any) => Promise<void>;
const invokeHandleGetTopPosts = handleGetTopPosts as unknown as (req: any, res: any) => Promise<void>;
const invokeHandleAggregatedTopPosts = handleAggregatedTopPosts as unknown as (req: any, res: any) => Promise<void>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeReq(
	overrides: { method?: string; query?: Record<string, string>; body?: Record<string, unknown> } = {},
) {
	return {
		method: overrides.method || "POST",
		query: overrides.query || {},
		body: overrides.body || {},
		headers: { authorization: "Bearer test-token" },
	} as any;
}

// ---------------------------------------------------------------------------
// Tests — handleFetchTopPosts
// ---------------------------------------------------------------------------

describe("handleFetchTopPosts", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetAuthUserOrError.mockResolvedValue({ id: "user-1" });
		mockParseBodyOrError.mockImplementation((_res: any, _schema: any, body: any) => body);
	});

	it("returns 401 when user is not authenticated", async () => {
		mockGetAuthUserOrError.mockResolvedValue(null);
		const res = mockRes();
		await invokeHandleFetchTopPosts(makeReq({ body: { competitorId: "c-1", username: "u" } }), res);
		expect(mockGetAuthUserOrError).toHaveBeenCalled();
	});

	it("returns early when body validation fails", async () => {
		mockParseBodyOrError.mockReturnValue(null);
		const res = mockRes();
		await invokeHandleFetchTopPosts(makeReq({ body: {} }), res);
		expect(mockVerifyCompetitorOwnership).not.toHaveBeenCalled();
	});

	it("returns early when competitor ownership fails", async () => {
		mockVerifyCompetitorOwnership.mockResolvedValue(null);
		const res = mockRes();
		await invokeHandleFetchTopPosts(
			makeReq({ body: { competitorId: "c-1", username: "user1" } }),
			res,
		);
		expect(mockGetAccessToken).not.toHaveBeenCalled();
	});

	it("returns 400 when no connected account", async () => {
		mockVerifyCompetitorOwnership.mockResolvedValue({ id: "c-1" });
		mockGetAccessToken.mockResolvedValue(null);

		const res = mockRes();
		await invokeHandleFetchTopPosts(
			makeReq({ body: { competitorId: "c-1", username: "user1" } }),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(400);
	});

	it("returns post count on success", async () => {
		mockVerifyCompetitorOwnership.mockResolvedValue({ id: "c-1" });
		mockGetAccessToken.mockResolvedValue("token-1");
		mockFetchAndStorePosts.mockResolvedValue({ postsCount: 25 });

		const res = mockRes();
		await invokeHandleFetchTopPosts(
			makeReq({ body: { competitorId: "c-1", username: "user1" } }),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ count: expect.anything() }),
		);
	});

	it("returns 502 when fetchAndStorePosts throws", async () => {
		mockVerifyCompetitorOwnership.mockResolvedValue({ id: "c-1" });
		mockGetAccessToken.mockResolvedValue("token-1");
		mockFetchAndStorePosts.mockRejectedValue(new Error("API timeout"));

		const res = mockRes();
		await invokeHandleFetchTopPosts(
			makeReq({ body: { competitorId: "c-1", username: "user1" } }),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(502);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "API timeout" }),
		);
	});
});

// ---------------------------------------------------------------------------
// Tests — handleGetTopPosts
// ---------------------------------------------------------------------------

describe("handleGetTopPosts", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetAuthUserOrError.mockResolvedValue({ id: "user-1" });
	});

	it("returns 401 when user is not authenticated", async () => {
		mockGetAuthUserOrError.mockResolvedValue(null);
		const res = mockRes();
		await invokeHandleGetTopPosts(makeReq({ method: "GET" }), res);
		expect(mockGetAuthUserOrError).toHaveBeenCalled();
	});

	it("returns 400 when competitorId is missing", async () => {
		const res = mockRes();
		await invokeHandleGetTopPosts(makeReq({ method: "GET", query: {} }), res);
		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "competitorId required" }),
		);
	});

	it("returns 403 when competitor not owned by user", async () => {
		mockDbFrom.mockReturnValue({
			select: vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue({
						maybeSingle: vi.fn().mockResolvedValue({ data: null }),
					}),
				}),
			}),
		});

		const res = mockRes();
		await invokeHandleGetTopPosts(
			makeReq({ method: "GET", query: { competitorId: "c-1" } }),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(403);
	});

	it("returns 400 for limit out of range", async () => {
		mockDbFrom.mockReturnValue({
			select: vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue({
						maybeSingle: vi.fn().mockResolvedValue({
							data: { id: "c-1", platform: "threads" },
						}),
					}),
				}),
			}),
		});

		const res = mockRes();
		await invokeHandleGetTopPosts(
			makeReq({
				method: "GET",
				query: { competitorId: "c-1", limit: "200" },
			}),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "limit must be between 1 and 100" }),
		);
	});

	it("returns enriched posts with competitor_platform on success", async () => {
		const posts = [
			{ competitor_id: "c-1", engagement_score: 100, content: "post1" },
			{ competitor_id: "c-1", engagement_score: 50, content: "post2" },
		];

		// First call: competitor lookup, second call: posts
		mockDbFrom.mockImplementation((table: string) => {
			if (table === "competitors") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								maybeSingle: vi.fn().mockResolvedValue({
									data: { id: "c-1", platform: "threads" },
								}),
							}),
						}),
					}),
				};
			}
			if (table === "competitor_top_posts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: posts }),
							}),
						}),
					}),
				};
			}
			return {};
		});

		const res = mockRes();
		await invokeHandleGetTopPosts(
			makeReq({ method: "GET", query: { competitorId: "c-1" } }),
			res,
		);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				posts: expect.arrayContaining([
					expect.objectContaining({ competitor_platform: "threads" }),
				]),
			}),
		);
	});

	it("defaults platform to threads when competitor has no platform", async () => {
		mockDbFrom.mockImplementation((table: string) => {
			if (table === "competitors") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							eq: vi.fn().mockReturnValue({
								maybeSingle: vi.fn().mockResolvedValue({
									data: { id: "c-1" }, // no platform field
								}),
							}),
						}),
					}),
				};
			}
			if (table === "competitor_top_posts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({
									data: [{ competitor_id: "c-1", engagement_score: 10 }],
								}),
							}),
						}),
					}),
				};
			}
			return {};
		});

		const res = mockRes();
		await invokeHandleGetTopPosts(
			makeReq({ method: "GET", query: { competitorId: "c-1" } }),
			res,
		);

		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				posts: [
					expect.objectContaining({ competitor_platform: "threads" }),
				],
			}),
		);
	});
});

// ---------------------------------------------------------------------------
// Tests — handleAggregatedTopPosts
// ---------------------------------------------------------------------------

describe("handleAggregatedTopPosts", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetAuthUserOrError.mockResolvedValue({ id: "user-1" });
	});

	it("returns 401 when user is not authenticated", async () => {
		mockGetAuthUserOrError.mockResolvedValue(null);
		const res = mockRes();
		await invokeHandleAggregatedTopPosts(makeReq({ method: "GET" }), res);
		expect(mockGetAuthUserOrError).toHaveBeenCalled();
	});

	it("returns 400 for limit out of range (over 100)", async () => {
		const res = mockRes();
		await invokeHandleAggregatedTopPosts(
			makeReq({ method: "GET", query: { limit: "101" } }),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(400);
	});

	it("returns 400 for negative limit", async () => {
		const res = mockRes();
		await invokeHandleAggregatedTopPosts(
			makeReq({ method: "GET", query: { limit: "-1" } }),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(400);
	});

	it("returns empty array when user has no competitors", async () => {
		mockDbFrom.mockImplementation((table: string) => {
			if (table === "competitors") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockResolvedValue({ data: [] }),
					}),
				};
			}
			return {};
		});

		const res = mockRes();
		await invokeHandleAggregatedTopPosts(makeReq({ method: "GET" }), res);
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ posts: [] }),
		);
	});

	it("enriches posts with competitor avatar and platform", async () => {
		const competitors = [
			{
				id: "c-1",
				username: "comp1",
				avatar_url: "https://example.com/a.jpg",
				platform: "instagram",
			},
			{
				id: "c-2",
				username: "comp2",
				avatar_url: "https://example.com/b.jpg",
				platform: null,
			},
		];

		const posts = [
			{ competitor_id: "c-1", engagement_score: 100, content: "post1" },
			{ competitor_id: "c-2", engagement_score: 80, content: "post2" },
			{ competitor_id: "c-1", engagement_score: 50, content: "post3" },
		];

		mockDbFrom.mockImplementation((table: string) => {
			if (table === "competitors") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockResolvedValue({ data: competitors }),
					}),
				};
			}
			if (table === "competitor_top_posts") {
				return {
					select: vi.fn().mockReturnValue({
						in: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: posts }),
							}),
						}),
					}),
				};
			}
			return {};
		});

		const res = mockRes();
		await invokeHandleAggregatedTopPosts(makeReq({ method: "GET" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		const jsonCall = res.json.mock.calls[0][0];
		expect(jsonCall.posts).toHaveLength(3);
		// First post should be c-1 (highest engagement)
		expect(jsonCall.posts[0].competitor_avatar_url).toBe(
			"https://example.com/a.jpg",
		);
		expect(jsonCall.posts[0].competitor_platform).toBe("instagram");
		// Second post (c-2) should default platform to "threads"
		expect(jsonCall.posts[1].competitor_platform).toBe("threads");
	});

	it("caps posts per competitor to ensure representation", async () => {
		const competitors = [
			{ id: "c-1", username: "comp1", avatar_url: "", platform: "threads" },
			{ id: "c-2", username: "comp2", avatar_url: "", platform: "threads" },
		];

		// 10 posts all from c-1, none from c-2
		const manyPosts = Array.from({ length: 10 }, (_, i) => ({
			competitor_id: "c-1",
			engagement_score: 100 - i,
			content: `post-${i}`,
		}));

		mockDbFrom.mockImplementation((table: string) => {
			if (table === "competitors") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockResolvedValue({ data: competitors }),
					}),
				};
			}
			if (table === "competitor_top_posts") {
				return {
					select: vi.fn().mockReturnValue({
						in: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: manyPosts }),
							}),
						}),
					}),
				};
			}
			return {};
		});

		const res = mockRes();
		// Request limit of 4 with 2 competitors => postsPerCompetitor = max(5, ceil(4/2)) = 5
		await invokeHandleAggregatedTopPosts(
			makeReq({ method: "GET", query: { limit: "4" } }),
			res,
		);

		const jsonCall = res.json.mock.calls[0][0];
		// Should be capped at limit (4)
		expect(jsonCall.posts.length).toBeLessThanOrEqual(4);
	});

	it("sorts results by engagement_score descending", async () => {
		const competitors = [
			{ id: "c-1", username: "comp1", avatar_url: "", platform: "threads" },
		];
		const posts = [
			{ competitor_id: "c-1", engagement_score: 10, metric_quality: "valid_engagement" },
			{ competitor_id: "c-1", engagement_score: 50, metric_quality: "valid_engagement" },
			{ competitor_id: "c-1", engagement_score: 30, metric_quality: "valid_engagement" },
		];

		mockDbFrom.mockImplementation((table: string) => {
			if (table === "competitors") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockResolvedValue({ data: competitors }),
					}),
				};
			}
			if (table === "competitor_top_posts") {
				return {
					select: vi.fn().mockReturnValue({
						in: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: posts }),
							}),
						}),
					}),
				};
			}
			return {};
		});

		const res = mockRes();
		await invokeHandleAggregatedTopPosts(makeReq({ method: "GET" }), res);

		const jsonCall = res.json.mock.calls[0][0];
		const scores = jsonCall.posts.map((p: any) => p.engagement_score);
		expect(scores).toEqual([50, 30, 10]);
	});
});
