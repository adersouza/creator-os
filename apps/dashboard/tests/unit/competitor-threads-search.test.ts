import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

/**
 * Unit tests for POST /api/competitors?action=search
 *
 * Tests the Threads profile search handler which looks up a user profile
 * via the Meta profile_lookup endpoint using fallback tokens.
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
	CompetitorSearchSchema: { parse: vi.fn() },
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

vi.mock("../../api/_lib/handlers/competitors/shared", () => ({
	getAllAccessTokens: (...args: unknown[]) => mockGetAllAccessTokens(...args),
	tryWithFallbackTokens: (...args: unknown[]) =>
		mockTryWithFallbackTokens(...args),
}));

// Import module under test AFTER mocks
const { handleSearch } = await import(
	"../../api/_lib/handlers/competitors/threads/search"
);
const invokeHandleSearch = handleSearch as unknown as (req: any, res: any) => Promise<void>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeReq(body: Record<string, unknown> = {}) {
	return {
		method: "POST",
		query: { action: "search" },
		body,
		headers: { authorization: "Bearer test-token" },
	} as any;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("competitor threads search handler", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetAuthUserOrError.mockResolvedValue({ id: "user-1" });
		mockParseBodyOrError.mockImplementation((_res: any, _schema: any, body: any) => body);
	});

	it("returns 401 when user is not authenticated", async () => {
		mockGetAuthUserOrError.mockResolvedValue(null);
		const res = mockRes();
		await invokeHandleSearch(makeReq({ query: "testuser" }), res);
		// withAuthAndBody calls getAuthUserOrError and short-circuits
		expect(mockGetAuthUserOrError).toHaveBeenCalled();
	});

	it("returns 400 when no connected account tokens", async () => {
		mockGetAllAccessTokens.mockResolvedValue([]);
		const res = mockRes();
		await invokeHandleSearch(makeReq({ query: "testuser" }), res);
		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "No connected account" }),
		);
	});

	it("returns 400 when body validation fails", async () => {
		mockParseBodyOrError.mockReturnValue(null);
		const res = mockRes();
		await invokeHandleSearch(makeReq({}), res);
		// parseBodyOrError returning null means handler short-circuits
		expect(mockGetAllAccessTokens).not.toHaveBeenCalled();
	});

	it("strips @ prefix from username before searching", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: {
				id: "123",
				username: "testuser",
				name: "Test User",
				profile_picture_url: "https://example.com/pic.jpg",
				biography: "bio text",
				is_verified: true,
				follower_count: 5000,
			},
			tokenIndex: 0,
		});

		const res = mockRes();
		await invokeHandleSearch(makeReq({ query: "@testuser" }), res);
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				success: true,
				profile: expect.objectContaining({
					username: "testuser",
				}),
			}),
		);
	});

	it("returns profile data on successful search", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: {
				id: "456",
				username: "founduser",
				name: "Found User",
				profile_picture_url: "https://example.com/avatar.jpg",
				biography: "Hello world",
				is_verified: false,
				follower_count: 1234,
			},
			tokenIndex: 0,
		});

		const res = mockRes();
		await invokeHandleSearch(makeReq({ query: "founduser" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				success: true,
				profile: {
					id: "456",
					username: "founduser",
					displayName: "Found User",
					avatarUrl: "https://example.com/avatar.jpg",
					bio: "Hello world",
					isVerified: false,
					followerCount: 1234,
				},
			}),
		);
	});

	it("falls back to username as displayName when name is missing", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: {
				id: "789",
				username: "noname",
				// name intentionally missing
				profile_picture_url: "",
				biography: "",
				is_verified: false,
				follower_count: 0,
			},
			tokenIndex: 0,
		});

		const res = mockRes();
		await invokeHandleSearch(makeReq({ query: "noname" }), res);

		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				profile: expect.objectContaining({
					displayName: "noname",
					avatarUrl: "",
					bio: "",
					followerCount: 0,
				}),
			}),
		);
	});

	it("returns 404 when all tokens fail", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1", "token-2"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: null,
			error: "User not found",
			tokenIndex: -1,
		});

		const res = mockRes();
		await invokeHandleSearch(makeReq({ query: "ghostuser" }), res);

		expect(res.status).toHaveBeenCalledWith(404);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: "User not found",
			}),
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
		await invokeHandleSearch(makeReq({ query: "ghostuser" }), res);

		expect(res.status).toHaveBeenCalledWith(404);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: expect.stringContaining("@ghostuser not found"),
			}),
		);
	});

	it("uses query as fallback id when profile.id missing", async () => {
		mockGetAllAccessTokens.mockResolvedValue(["token-1"]);
		mockTryWithFallbackTokens.mockResolvedValue({
			data: {
				// id intentionally missing
				username: "testuser",
				name: "Test",
			},
			tokenIndex: 0,
		});

		const res = mockRes();
		await invokeHandleSearch(makeReq({ query: "testuser" }), res);

		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				profile: expect.objectContaining({
					id: "testuser",
				}),
			}),
		);
	});
});
