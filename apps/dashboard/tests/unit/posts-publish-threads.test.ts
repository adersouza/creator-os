import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
	mockRes,
	mockPublishReq,
	createPublishSupabaseMock,
	createTestThreadsAccount,
	type PublishSupabaseOverrides,
} from "../helpers/mockFactories";
import { mediaUrlFingerprint } from "../../api/_lib/originalitySignals.js";

/**
 * Unit tests for Threads publish handler.
 *
 * Tests the handlePublish function for Threads-specific paths:
 * - Valid text post → success
 * - Missing accountId → 400
 * - Account not found → 404
 * - Account not connected → 400
 * - Daily post limit exceeded → 403
 * - Rate limit exceeded → 429 with headers
 * - Text post with hashtags → extracts and stores
 */

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

let currentSupabase: ReturnType<typeof createPublishSupabaseMock>;

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => currentSupabase,
	getSupabaseAny: () => currentSupabase,
}));

vi.mock("@/api/_lib/logger.js", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
	apiError: (res: any, status: number, msg: string, extra?: any) =>
		res.status(status).json({ error: msg, ...extra }),
	apiSuccess: (res: any, data: unknown) =>
		res.status(200).json({ data }),
}));

vi.mock("@/api/_lib/sanitize.js", () => ({
	sanitizeHtml: (s: string) => s,
}));

vi.mock("@/api/_lib/encryption.js", () => ({
	decrypt: (s: string) => `decrypted-${s}`,
}));

vi.mock("@/api/_lib/webhookDispatcher.js", () => ({
	dispatchWebhook: vi.fn(),
}));

const mockPostToThreads = vi.fn();
vi.mock("@/api/_lib/threadsApi.js", () => ({
	postToThreads: (...args: unknown[]) => mockPostToThreads(...args),
}));

vi.mock("@/api/_lib/validation.js", () => ({
	PublishPostSchema: {
		safeParse: (body: unknown) => {
			if (!body || typeof body !== "object") {
				return { success: false, error: { issues: [{ path: [], message: "Invalid body" }] } };
			}
			const b = body as Record<string, unknown>;
			if (!b.content || (typeof b.content === "string" && b.content.trim() === "")) {
				return { success: false, error: { issues: [{ path: ["content"], message: "content is required" }] } };
			}
			return { success: true, data: body };
		},
	},
	parseBodyOrError: (res: any, schema: any, body: unknown) => {
		const result = schema.safeParse(body);
		if (!result.success) {
			const messages = result.error.issues
				.map((i: any) => `${i.path.join(".")}: ${i.message}`)
				.join("; ");
			res.status(400).json({ error: messages });
			return null;
		}
		return result.data;
	},
}));

vi.mock("@/api/_lib/dailyCap.js", () => ({
	checkDailyCap: vi.fn().mockResolvedValue({ allowed: true, used: 1, limit: 8 }),
}));

vi.mock("@/api/_lib/billing.js", () => ({
	getAccountLimit: vi.fn().mockReturnValue(5),
}));

vi.mock("@/api/_lib/qstash.js", () => ({
	getQStashClient: () => ({
		publishJSON: vi.fn().mockResolvedValue({}),
	}),
}));

vi.mock("@/api/_lib/ssrfProtection.js", () => ({
	validateUrlNotPrivate: vi.fn().mockResolvedValue(null),
}));

vi.mock("@/api/_lib/cron/scheduled-posts/mediaValidation.js", () => ({
	checkMediaUrlAccessible: vi.fn().mockResolvedValue(null),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DEFAULT_ACCOUNT = createTestThreadsAccount();

/** Sets up `currentSupabase` with overrides for publish-handler tests. */
function setupSupabase(overrides: PublishSupabaseOverrides) {
	currentSupabase = createPublishSupabaseMock(overrides);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Threads publish handler", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		process.env.APP_URL = "https://juno33.com";
	});

	afterEach(() => {
		delete process.env.APP_URL;
		vi.restoreAllMocks();
	});

	it("publishes a valid text post successfully", async () => {
		setupSupabase({
			profile: { subscription_tier: "pro" },
			account: DEFAULT_ACCOUNT,
			rateLimit: [{ allowed: true, daily_limit: 250, daily_used: 5 }],
			postInsert: { id: "post-123" },
			postCount: 2,
		});

		mockPostToThreads.mockResolvedValue({
			success: true,
			threadId: "thread-abc",
		});

		// Mock fetch for permalink retrieval
		global.fetch = vi.fn().mockResolvedValue({
			json: vi.fn().mockResolvedValue({ permalink: "https://threads.net/@user/post/123" }),
		}) as any;

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			accountId: "acc-1",
			content: "Hello world!",
			platform: "threads",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				data: expect.objectContaining({
					postId: "post-123",
					threadId: "thread-abc",
				}),
			}),
		);
	});

	it("requires confirmation before manual Threads publish reuses media from another account", async () => {
		const mediaUrl = "https://example.com/thread-photo.jpg";
		setupSupabase({
			profile: { subscription_tier: "pro" },
			account: DEFAULT_ACCOUNT,
			rateLimit: [{ allowed: true, daily_limit: 250, daily_used: 5 }],
			postInsert: { id: "post-dup" },
			postCount: 2,
			postOriginalitySignals: [{
				post_id: "previous-thread-post",
				account_id: "acc-2",
				instagram_account_id: null,
				platform: "threads",
				captured_at: new Date().toISOString(),
				media_url_hashes: [mediaUrlFingerprint(mediaUrl)],
				perceptual_hashes: [],
			}],
		});

		mockPostToThreads.mockResolvedValue({
			success: true,
			threadId: "thread-dup",
		});

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			accountId: "acc-1",
			content: "Manual reuse",
			media: [{ type: "image", url: mediaUrl }],
			platform: "threads",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(409);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				code: "MANUAL_MEDIA_REUSE_CONFIRMATION_REQUIRED",
				extra: expect.objectContaining({
					preflight: expect.objectContaining({
						ok: true,
						issues: expect.arrayContaining([
							expect.objectContaining({
								code: "cross_account_media_reuse_warning",
								details: expect.objectContaining({
									overrideToken: expect.any(String),
									matchedAccountId: "acc-2",
								}),
							}),
						]),
					}),
				}),
			}),
		);
		expect(mockPostToThreads).not.toHaveBeenCalled();
	});

	it("returns 400 when accountId is missing for Threads", async () => {
		setupSupabase({
			profile: { subscription_tier: "pro" },
			postCount: 0,
		});

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			content: "Hello world!",
			platform: "threads",
			// No accountId
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "accountId is required" }),
		);
	});

	it("returns 404 when account is not found", async () => {
		setupSupabase({
			profile: { subscription_tier: "pro" },
			account: null,
			postCount: 0,
			threadsCount: 0,
			igCount: 0,
		});

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			accountId: "nonexistent-acc",
			content: "Hello world!",
			platform: "threads",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(404);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Account not found" }),
		);
	});

	it("returns 400 when account is not connected to Threads", async () => {
		setupSupabase({
			profile: { subscription_tier: "pro" },
			account: createTestThreadsAccount({
				threads_user_id: null,
				threads_access_token_encrypted: null,
			}),
			postCount: 0,
		});

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			accountId: "acc-1",
			content: "Hello!",
			platform: "threads",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Account is not connected to Threads" }),
		);
	});

	it("returns 403 when daily subscription post limit exceeded", async () => {
		// Free tier with 3 daily limit, already at 3.
		// We need per-table control here so we build the mock manually using
		// the shared factory as a base, then override the `from` implementation
		// for the specific tables we need fine-grained control over.
		const sb = createPublishSupabaseMock({
			profile: { subscription_tier: "free" },
			postCount: 3,
		});

		// Override from() to return free-tier profile + posts count >= 3
		sb.from = vi.fn().mockImplementation((table: string) => {
			if (table === "profiles") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({
								data: { subscription_tier: "free" },
								error: null,
							}),
						}),
					}),
				};
			}
			if (table === "posts") {
				return {
					select: vi.fn().mockImplementation((_cols: string, opts?: any) => {
						if (opts?.count === "exact") {
							const chain: any = {};
							chain.eq = vi.fn().mockReturnValue(chain);
							chain.is = vi.fn().mockReturnValue(chain);
							chain.gte = vi.fn().mockReturnValue(chain);
							chain.lt = vi.fn().mockResolvedValue({ count: 3, error: null });
							return chain;
						}
						return {
							eq: vi.fn().mockReturnThis(),
							maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
						};
					}),
					insert: vi.fn().mockReturnValue({
						select: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
						}),
					}),
				};
			}
			return {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
			};
		});

		currentSupabase = sb;

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			accountId: "acc-1",
			content: "Hello!",
			platform: "threads",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(403);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: expect.stringContaining("Daily post limit reached"),
			}),
		);
	});

	it("returns 429 with rate limit headers when rate limit exceeded", async () => {
		setupSupabase({
			profile: { subscription_tier: "pro" },
			account: DEFAULT_ACCOUNT,
			rateLimit: [{ allowed: false, daily_limit: 250, daily_used: 250 }],
			postCount: 2,
		});

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			accountId: "acc-1",
			content: "Hello!",
			platform: "threads",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(429);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Rate limit exceeded" }),
		);
		expect(res.setHeader).toHaveBeenCalledWith("X-RateLimit-Limit", "250");
		expect(res.setHeader).toHaveBeenCalledWith("X-RateLimit-Remaining", "0");
	});

	it("extracts and stores hashtags from content", async () => {
		// Need insert interception, so build mock then patch
		const sb = createPublishSupabaseMock({
			profile: { subscription_tier: "pro" },
			account: DEFAULT_ACCOUNT,
			rateLimit: [{ allowed: true, daily_limit: 250, daily_used: 5 }],
			postInsert: { id: "post-456" },
			postCount: 1,
		});

		// Override from() for fine-grained per-table control (hashtag test
		// requires capturing the insert payload AND providing correct
		// per-table mocks for accounts/instagram_accounts/posts).
		const capturedInsert: { data: any } = { data: null };
		sb.from = vi.fn().mockImplementation((table: string) => {
			if (table === "profiles") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							maybeSingle: vi.fn().mockResolvedValue({
								data: { subscription_tier: "pro" },
								error: null,
							}),
						}),
					}),
				};
			}
			if (table === "accounts") {
				return {
					select: vi.fn().mockImplementation((_cols: string, opts?: any) => {
						if (opts?.count === "exact") {
							return {
								eq: vi.fn().mockReturnValue({
									eq: vi.fn().mockResolvedValue({ count: 1, error: null }),
								}),
							};
						}
						return {
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									maybeSingle: vi.fn().mockResolvedValue({
										data: DEFAULT_ACCOUNT,
										error: null,
									}),
									order: vi.fn().mockReturnValue({
										limit: vi.fn().mockResolvedValue({ data: [{ id: "acc-1" }], error: null }),
									}),
								}),
							}),
						};
					}),
				};
			}
			if (table === "instagram_accounts") {
				return {
					select: vi.fn().mockImplementation((_cols: string, opts?: any) => {
						if (opts?.count === "exact") {
							return {
								eq: vi.fn().mockReturnValue({
									eq: vi.fn().mockResolvedValue({ count: 0, error: null }),
								}),
							};
						}
						return {
							eq: vi.fn().mockReturnValue({
								eq: vi.fn().mockReturnValue({
									order: vi.fn().mockReturnValue({
										limit: vi.fn().mockResolvedValue({ data: [], error: null }),
									}),
								}),
							}),
						};
					}),
				};
			}
			if (table === "posts") {
				return {
					select: vi.fn().mockImplementation((_cols: string, opts?: any) => {
						if (opts?.count === "exact") {
							const chain: any = {};
							chain.eq = vi.fn().mockReturnValue(chain);
							chain.is = vi.fn().mockReturnValue(chain);
							chain.gte = vi.fn().mockReturnValue(chain);
							chain.lt = vi.fn().mockResolvedValue({ count: 1, error: null });
							return chain;
						}
						return {
							eq: vi.fn().mockReturnThis(),
							maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
						};
					}),
					insert: vi.fn().mockImplementation((data: any) => {
						capturedInsert.data = data;
						return {
							select: vi.fn().mockReturnValue({
								maybeSingle: vi.fn().mockResolvedValue({
									data: { id: "post-456" },
									error: null,
								}),
							}),
						};
					}),
					update: vi.fn().mockReturnValue({
						eq: vi.fn().mockResolvedValue({ error: null }),
					}),
				};
			}
			return {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
			};
		});

		currentSupabase = sb;

		mockPostToThreads.mockResolvedValue({
			success: true,
			threadId: "thread-xyz",
		});

		global.fetch = vi.fn().mockResolvedValue({
			json: vi.fn().mockResolvedValue({ permalink: "https://threads.net/@user/post/456" }),
		}) as any;

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			accountId: "acc-1",
			content: "Check out #Travel and #Photography tips!",
			platform: "threads",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		// Verify hashtags were extracted in the insert data
		expect(capturedInsert.data).toBeTruthy();
		expect(capturedInsert.data.hashtags).toEqual(
			expect.arrayContaining(["travel", "photography"]),
		);
	});
});
