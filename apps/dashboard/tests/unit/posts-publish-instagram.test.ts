import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
	mockRes,
	mockPublishReq,
	createPublishSupabaseMock,
	interceptPostsInsert,
	createTestInstagramAccount,
} from "../helpers/mockFactories";

/**
 * Unit tests for Instagram publish handler.
 *
 * Tests the handlePublish function for Instagram-specific paths:
 * - Valid image post → success
 * - Missing instagramAccountId → 400
 * - Account without token → 400
 * - Carousel validation
 * - REELS media type accepted
 * - STORIES media type accepted
 */

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

let currentSupabase: ReturnType<typeof createPublishSupabaseMock>;

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => currentSupabase,
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

vi.mock("@/api/_lib/threadsApi.js", () => ({
	postToThreads: vi.fn(),
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

const mockPostToInstagram = vi.fn();
const mockGetInstagramPostMetrics = vi.fn();

vi.mock("@/api/_lib/instagramApi.js", () => ({
	postToInstagram: (...args: unknown[]) => mockPostToInstagram(...args),
	getInstagramPostMetrics: (...args: unknown[]) => mockGetInstagramPostMetrics(...args),
}));

vi.mock("@/api/_lib/qstash.js", () => ({
	getQStashClient: () => ({
		publishJSON: vi.fn().mockResolvedValue({}),
	}),
}));

const mockOrchestrateIGPublish = vi.fn();

vi.mock("@/api/_lib/instagram/orchestrate.js", () => ({
	orchestrateIGPublish: (...args: unknown[]) => mockOrchestrateIGPublish(...args),
}));

vi.mock("@/api/_lib/qstashSchedule.js", () => ({
	schedulePostPublishSyncs: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/api/_lib/cron/scheduled-posts/mediaValidation.js", () => ({
	checkMediaUrlAccessible: vi.fn().mockResolvedValue(null),
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

const DEFAULT_IG_ACCOUNT = createTestInstagramAccount();

describe("Instagram publish handler", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		process.env.APP_URL = "https://juno33.com";
	});

	afterEach(() => {
		delete process.env.APP_URL;
		vi.restoreAllMocks();
	});

	it("publishes a valid image post successfully", async () => {
		currentSupabase = createPublishSupabaseMock({
			profile: { subscription_tier: "pro" },
			igAccount: DEFAULT_IG_ACCOUNT,
			rateLimit: [{ allowed: true, daily_limit: 25, daily_used: 2 }],
			postInsert: { id: "post-ig-1" },
		});

		mockOrchestrateIGPublish.mockResolvedValue({
			success: true,
			mediaId: "ig-media-123",
			permalink: "https://instagram.com/p/abc123",
			timestamp: new Date(),
		});

		mockGetInstagramPostMetrics.mockResolvedValue({
			success: true,
			metrics: {
				impressions: 0,
				reach: 0,
				saved: 0,
				shares: 0,
				likes: 0,
				comments: 0,
				plays: 0,
				video_views: 0,
				reels_skip_rate: 0,
				engagementRate: 0,
			},
		});

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			instagramAccountId: "ig-acc-1",
			content: "Beautiful sunset shot!",
			media: [{ type: "image", url: "https://example.com/photo.jpg" }],
			igMediaType: "IMAGE",
			platform: "instagram",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				data: expect.objectContaining({
					postId: "post-ig-1",
					mediaId: "ig-media-123",
					platform: "instagram",
				}),
			}),
		);
	});

	it("returns 400 when instagramAccountId is missing", async () => {
		currentSupabase = createPublishSupabaseMock({
			profile: { subscription_tier: "pro" },
			postCount: 0,
		});

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			content: "No account specified",
			platform: "instagram",
			// No instagramAccountId
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: "instagramAccountId is required for Instagram posts",
			}),
		);
	});

	it("returns 400 when account has no token", async () => {
		currentSupabase = createPublishSupabaseMock({
			profile: { subscription_tier: "pro" },
			igAccount: createTestInstagramAccount({
				instagram_access_token_encrypted: null,
			}),
			rateLimit: [{ allowed: true, daily_limit: 25, daily_used: 0 }],
		});

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			instagramAccountId: "ig-acc-1",
			content: "Post without auth",
			platform: "instagram",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: "Instagram account not properly connected",
			}),
		);
	});

	it("handles carousel with multiple media items", async () => {
		const sb = createPublishSupabaseMock({
			profile: { subscription_tier: "pro" },
			igAccount: DEFAULT_IG_ACCOUNT,
			rateLimit: [{ allowed: true, daily_limit: 25, daily_used: 2 }],
			postInsert: { id: "post-carousel-1" },
		});
		const capture = interceptPostsInsert(sb, "post-carousel-1");
		currentSupabase = sb;

		mockOrchestrateIGPublish.mockResolvedValue({
			success: true,
			mediaId: "ig-carousel-123",
			permalink: "https://instagram.com/p/carousel123",
			timestamp: new Date(),
		});

		mockGetInstagramPostMetrics.mockResolvedValue({
			success: false,
			metrics: null,
		});

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			instagramAccountId: "ig-acc-1",
			content: "Carousel post!",
			media: [
				{ type: "image", url: "https://example.com/photo1.jpg" },
				{ type: "image", url: "https://example.com/photo2.jpg" },
				{ type: "image", url: "https://example.com/photo3.jpg" },
			],
			igMediaType: "CAROUSEL",
			platform: "instagram",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		// Verify post was created with CAROUSEL media type
		expect(capture.data).toBeTruthy();
		expect(capture.data.ig_media_type).toBe("CAROUSEL");
		expect(capture.data.media_type).toBe("carousel");
	});

	it("accepts REELS media type", async () => {
		const sb = createPublishSupabaseMock({
			profile: { subscription_tier: "pro" },
			igAccount: DEFAULT_IG_ACCOUNT,
			rateLimit: [{ allowed: true, daily_limit: 25, daily_used: 2 }],
		});
		const capture = interceptPostsInsert(sb, "post-reel-1");
		currentSupabase = sb;

		mockOrchestrateIGPublish.mockResolvedValue({
			success: true,
			mediaId: "ig-reel-123",
			permalink: "https://instagram.com/reel/abc",
			timestamp: new Date(),
		});

		mockGetInstagramPostMetrics.mockResolvedValue({ success: false, metrics: null });

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			instagramAccountId: "ig-acc-1",
			content: "Watch this reel!",
			media: [{ type: "video", url: "https://example.com/video.mp4" }],
			igMediaType: "REELS",
			platform: "instagram",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(capture.data).toBeTruthy();
		expect(capture.data.ig_media_type).toBe("REELS");
	});

	it("canonicalizes singular reel media type", async () => {
		const sb = createPublishSupabaseMock({
			profile: { subscription_tier: "pro" },
			igAccount: DEFAULT_IG_ACCOUNT,
			rateLimit: [{ allowed: true, daily_limit: 25, daily_used: 2 }],
		});
		const capture = interceptPostsInsert(sb, "post-reel-1");
		currentSupabase = sb;

		mockOrchestrateIGPublish.mockResolvedValue({
			success: true,
			mediaId: "ig-reel-123",
			permalink: "https://instagram.com/reel/abc",
			timestamp: new Date(),
		});
		mockGetInstagramPostMetrics.mockResolvedValue({ success: false, metrics: null });

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			instagramAccountId: "ig-acc-1",
			content: "Watch this reel!",
			media: [{ type: "video", url: "https://example.com/video.mp4" }],
			mediaType: "reel",
			platform: "instagram",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(capture.data.ig_media_type).toBe("REELS");
		expect(capture.data.media_type).toBe("reel");
	});

	it("accepts STORIES media type", async () => {
		const sb = createPublishSupabaseMock({
			profile: { subscription_tier: "pro" },
			igAccount: DEFAULT_IG_ACCOUNT,
			rateLimit: [{ allowed: true, daily_limit: 25, daily_used: 2 }],
		});
		const capture = interceptPostsInsert(sb, "post-story-1");
		currentSupabase = sb;

		mockOrchestrateIGPublish.mockResolvedValue({
			success: true,
			mediaId: "ig-story-123",
			permalink: null,
			timestamp: new Date(),
		});

		mockGetInstagramPostMetrics.mockResolvedValue({ success: false, metrics: null });

		const { handlePublish } = await import("@/api/_lib/handlers/posts/publish.js");
		const res = mockRes();
		const req = mockPublishReq({
			instagramAccountId: "ig-acc-1",
			content: "Check my story!",
			media: [{ type: "image", url: "https://example.com/story.jpg" }],
			igMediaType: "STORIES",
			platform: "instagram",
		});

		await handlePublish(req as any, res as any, "user-1");

		expect(res.status).toHaveBeenCalledWith(200);
		expect(capture.data).toBeTruthy();
		expect(capture.data.ig_media_type).toBe("STORIES");
	});
});
