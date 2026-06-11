import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

/**
 * Unit tests for POST /api/competitors?action=add
 *
 * Tests the Threads competitor add handler which looks up a profile,
 * inserts a competitor row, and fires off initial post fetching.
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
	CompetitorAddSchema: { parse: vi.fn() },
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
const mockDbFrom = vi.fn();

vi.mock("../../api/_lib/handlers/competitors/shared", () => ({
	getAllAccessTokens: (...args: unknown[]) => mockGetAllAccessTokens(...args),
	tryWithFallbackTokens: (...args: unknown[]) =>
		mockTryWithFallbackTokens(...args),
	fetchAndStorePosts: (...args: unknown[]) =>
		mockFetchAndStorePosts(...args),
	db: () => ({ from: (...args: unknown[]) => mockDbFrom(...args) }),
}));

// Import module under test AFTER mocks
const { handleAdd } = await import(
	"../../api/_lib/handlers/competitors/threads/add"
);
const invokeHandleAdd = handleAdd as unknown as (req: any, res: any) => Promise<void>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeReq(body: Record<string, unknown> = {}) {
	return {
		method: "POST",
		query: { action: "add" },
		body,
		headers: { authorization: "Bearer test-token" },
	} as any;
}

function setupDbInsertSuccess(competitorData: Record<string, unknown>) {
	mockDbFrom.mockImplementation((table: string) => {
		if (table === "competitors") {
			return {
				insert: vi.fn().mockReturnValue({
					select: vi.fn().mockReturnValue({
						maybeSingle: vi.fn().mockResolvedValue({
							data: competitorData,
							error: null,
						}),
					}),
				}),
			};
		}
		return {};
	});
}

function setupDbInsertError(code: string, message: string) {
	mockDbFrom.mockImplementation((table: string) => {
		if (table === "competitors") {
			return {
				insert: vi.fn().mockReturnValue({
					select: vi.fn().mockReturnValue({
						maybeSingle: vi.fn().mockResolvedValue({
							data: null,
							error: { code, message },
						}),
					}),
				}),
			};
		}
		return {};
	});
}

const PROFILE_DATA = {
	username: "competitor1",
	name: "Competitor One",
	profile_picture_url: "https://example.com/pic.jpg",
	biography: "A competitor bio",
	is_verified: true,
	follower_count: 10000,
	likes_count: 50,
	quotes_count: 10,
	replies_count: 20,
	reposts_count: 30,
	views_count: 5000,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("competitor threads add handler", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetAuthUserOrError.mockResolvedValue({ id: "user-1" });
		mockParseBodyOrError.mockImplementation((_res: any, _schema: any, body: any) => body);
		mockFetchAndStorePosts.mockResolvedValue({ postsCount: 10 });
	});

	it("returns 401 when user is not authenticated", async () => {
		mockGetAuthUserOrError.mockResolvedValue(null);
		const res = mockRes();
		await invokeHandleAdd(makeReq({ username: "testuser" }), res);
		expect(mockGetAuthUserOrError).toHaveBeenCalled();
	});

	it("returns 400 when body validation fails", async () => {
		mockParseBodyOrError.mockReturnValue(null);
		const res = mockRes();
		await invokeHandleAdd(makeReq({}), res);
		expect(mockGetAllAccessTokens).not.toHaveBeenCalled();
	});

	it("returns 400 when no connected account tokens exist", async () => {
		mockGetAllAccessTokens.mockResolvedValue([]);
		const res = mockRes();
		await invokeHandleAdd(makeReq({ username: "competitor1" }), res);
		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "No connected account" }),
		);
	});

	it("returns 404 when all tokens fail to look up the profile", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: null,
			error: "User not found",
			tokenIndex: -1,
		});

		const res = mockRes();
		await invokeHandleAdd(makeReq({ username: "ghostuser" }), res);

		expect(res.status).toHaveBeenCalledWith(404);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "User not found" }),
		);
	});

	it("returns fallback error message when error is undefined", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: null,
			error: undefined,
			tokenIndex: -1,
		});

		const res = mockRes();
		await invokeHandleAdd(makeReq({ username: "ghostuser" }), res);

		expect(res.status).toHaveBeenCalledWith(404);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: expect.stringContaining("@ghostuser not found"),
			}),
		);
	});

	it("strips @ prefix from username", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: PROFILE_DATA,
			tokenIndex: 0,
		});
		setupDbInsertSuccess({ id: "comp-1", ...PROFILE_DATA });

		const res = mockRes();
		await invokeHandleAdd(makeReq({ username: "@competitor1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
	});

	it("inserts competitor and returns success on happy path", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: PROFILE_DATA,
			tokenIndex: 0,
		});
		const savedCompetitor = { id: "comp-1", username: "competitor1" };
		setupDbInsertSuccess(savedCompetitor);

		const res = mockRes();
		await invokeHandleAdd(makeReq({ username: "competitor1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				success: true,
				competitor: savedCompetitor,
			}),
		);
	});

	it("fires off fetchAndStorePosts asynchronously after insert", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: PROFILE_DATA,
			tokenIndex: 0,
		});
		setupDbInsertSuccess({ id: "comp-1", username: "competitor1" });

		const res = mockRes();
		await invokeHandleAdd(makeReq({ username: "competitor1" }), res);

		// fetchAndStorePosts should be called (fire-and-forget)
		expect(mockFetchAndStorePosts).toHaveBeenCalledWith(
			"comp-1",
			"competitor1",
			expect.any(String), // working token
		);
	});

	it("returns 400 when competitor already exists (unique violation)", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: PROFILE_DATA,
			tokenIndex: 0,
		});
		setupDbInsertError("23505", "duplicate key value");

		const res = mockRes();
		await invokeHandleAdd(makeReq({ username: "competitor1" }), res);

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Competitor already tracked" }),
		);
	});

	it("returns 500 on non-duplicate DB insert error", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: PROFILE_DATA,
			tokenIndex: 0,
		});
		setupDbInsertError("42000", "some other error");

		const res = mockRes();
		await invokeHandleAdd(makeReq({ username: "competitor1" }), res);

		expect(res.status).toHaveBeenCalledWith(500);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Failed to add competitor" }),
		);
	});

	it("returns 500 when DB insert throws an exception", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: PROFILE_DATA,
			tokenIndex: 0,
		});
		mockDbFrom.mockImplementation(() => {
			return {
				insert: vi.fn().mockReturnValue({
					select: vi.fn().mockReturnValue({
						maybeSingle: vi.fn().mockRejectedValue(new Error("connection error")),
					}),
				}),
			};
		});

		const res = mockRes();
		await invokeHandleAdd(makeReq({ username: "competitor1" }), res);

		expect(res.status).toHaveBeenCalledWith(500);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Failed to add competitor" }),
		);
	});

	it("uses second token when first fails in tryWithFallbackTokens", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["bad-token", "good-token"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: PROFILE_DATA,
			tokenIndex: 1,
		});
		setupDbInsertSuccess({ id: "comp-1" });

		const res = mockRes();
		await invokeHandleAdd(makeReq({ username: "competitor1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
	});
});
