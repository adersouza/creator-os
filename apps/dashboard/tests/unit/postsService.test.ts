import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFrom = vi.fn();
const mockGetSession = vi.fn();
const mockChannel = vi.fn();
const mockSubscribe = vi.fn();
const mockMapPostRow = vi.fn((row: any) => ({ id: row.id, content: row.content, mapped: true }));
const mockGetUserIdAsync = vi.fn();
const mockDetectMediaType = vi.fn((url: string) => url.endsWith(".mp4") ? "video" : "image");
const mockSafeJsonParse = vi.fn((response: Response) => response.json());

vi.mock("@/services/realtimeManager", () => ({
	subscribe: (...args: unknown[]) => mockSubscribe(...args),
}));

vi.mock("@/lib/mappers", () => ({
	mapPostRow: (...args: unknown[]) => mockMapPostRow(...args),
}));

vi.mock("@/utils/sanitize", () => ({
	sanitizeMediaURLs: (urls: string[]) => urls.filter(Boolean),
	sanitizeText: (content: string) => content.trim(),
	validatePostContent: (content: string) => content.trim(),
}));

vi.mock("@/lib/apiUrl", () => ({
	apiUrl: (path: string) => path,
}));

vi.mock("@/services/api/shared", () => ({
	detectMediaType: (...args: unknown[]) => mockDetectMediaType(...args),
	getUserIdAsync: () => mockGetUserIdAsync(),
	logger: { error: vi.fn(), warn: vi.fn(), debug: vi.fn(), log: vi.fn() },
	safeJsonParse: (...args: [Response]) => mockSafeJsonParse(...args),
	supabase: {
		auth: { getSession: () => mockGetSession() },
		from: (...args: unknown[]) => mockFrom(...args),
		channel: (...args: unknown[]) => mockChannel(...args),
	},
}));

import {
	cleanupDuplicatePosts,
	createPost,
	deletePost,
	duplicatePost,
	fetchConversation,
	fetchCampaignFactoryAudioEvents,
	fetchGhostPosts,
	formatCampaignFactoryAudioEventLine,
	getPost,
	getPosts,
	getQueuedPostsForCalendar,
	lookupPostByUrl,
	publishPostNow,
	refreshPostMetrics,
	repostPost,
	resumePendingPublishJobs,
	sendReply,
	subscribeToPostsRealtime,
	parseCampaignFactoryAudioEvent,
	updateCampaignFactoryAudioState,
	updatePost,
} from "@/services/api/posts";

function query(result: any = { data: null, error: null }) {
	const q: any = {
		select: vi.fn(() => q),
		eq: vi.fn(() => q),
		or: vi.fn(() => q),
		in: vi.fn(() => q),
		not: vi.fn(() => q),
		ilike: vi.fn(() => q),
		order: vi.fn(() => q),
		range: vi.fn(() => q),
		limit: vi.fn(() => q),
		insert: vi.fn(() => q),
		update: vi.fn(() => q),
		delete: vi.fn(() => q),
		maybeSingle: vi.fn().mockResolvedValue(result),
		then: (resolve: (value: any) => unknown) => Promise.resolve(result).then(resolve),
	};
	if ("count" in result) q.count = result.count;
	return q;
}

function jsonResponse(body: unknown, ok = true, status = ok ? 200 : 500): Response {
	return {
		ok,
		status,
		headers: new Headers({ "content-type": "application/json" }),
		json: vi.fn().mockResolvedValue(body),
	} as unknown as Response;
}

beforeEach(() => {
	vi.clearAllMocks();
	window.localStorage.clear();
	mockGetUserIdAsync.mockResolvedValue("user-1");
	mockGetSession.mockResolvedValue({
		data: { session: { access_token: "token-1", user: { id: "user-1" } } },
	});
	global.fetch = vi.fn().mockResolvedValue(jsonResponse({ ok: true })) as any;
});

describe("posts API service", () => {
	it("fetches paginated posts with count and platform/account filters", async () => {
		const countQuery = query({ data: null, error: null, count: 12 });
		const dataQuery = query({ data: [{ id: "p1", content: "hello" }], error: null });
		mockFrom.mockReturnValueOnce(countQuery).mockReturnValueOnce(dataQuery);

		const result = await getPosts("ig-1", 2, 10, "instagram", "2026-05-01T00:00:00Z", "scheduled");

		expect(result).toEqual({ posts: [{ id: "p1", content: "hello", mapped: true }], total: 12 });
		expect(countQuery.eq).toHaveBeenCalledWith("instagram_account_id", "ig-1");
		expect(countQuery.eq).toHaveBeenCalledWith("platform", "instagram");
		expect(countQuery.eq).toHaveBeenCalledWith("status", "scheduled");
		expect(dataQuery.range).toHaveBeenCalledWith(10, 19);
		expect(dataQuery.order).toHaveBeenCalledWith("scheduled_for", {
			ascending: true,
			nullsFirst: false,
		});
	});

	it("maps pending auto-post queue items into calendar posts", async () => {
		mockFrom
			.mockReturnValueOnce(query({ data: { workspace_id: "workspace-1" }, error: null }))
			.mockReturnValueOnce(query({
				data: [{
					id: "q1",
					content: "queued",
					scheduled_for: "2026-05-06T12:00:00Z",
					created_at: "2026-05-05T12:00:00Z",
					media_urls: ["img.jpg"],
					group_id: "group-1",
					topic_tag: "Dating",
				}],
				error: null,
			}));

		const posts = await getQueuedPostsForCalendar();

		expect(posts).toHaveLength(1);
		expect(posts[0]).toMatchObject({
			id: "queue-q1",
			content: "queued",
			status: "scheduled",
			source: "auto-poster",
			metadata: { isQueueItem: true, topicTag: "Dating", groupId: "group-1" },
		});
	});

	it("publishes immediately through the backend API with sanitized media", async () => {
		const onPublishStage = vi.fn();
		(global.fetch as any)
			.mockResolvedValueOnce(jsonResponse({ ok: true, issues: [], summary: { errors: 0, warnings: 0, infos: 0 } }))
			.mockResolvedValueOnce(jsonResponse({ id: "published-1" }));

		const result = await createPost({
			status: "published",
			platform: "threads",
			accountId: "acct-1",
			content: "  publish me  ",
			mediaUrls: ["image.jpg", ""],
			topics: ["dating"],
			settings: { allowReplies: true, whoCanReply: "followers" },
			idempotencyKey: "composer:submit:acct-1:0",
			onPublishStage,
		});

		expect(result).toEqual({ id: "published-1" });
		const [, init] = (global.fetch as any).mock.calls[1];
		expect(init.body).toContain('"content":"publish me"');
		expect(init.body).toContain('"accountId":"acct-1"');
		expect(init.body).toContain('"media":[{"type":"image","url":"image.jpg"}]');
		expect(init.headers).toEqual(
			expect.objectContaining({
				"Idempotency-Key": "composer:submit:acct-1:0",
			}),
		);
		expect(onPublishStage).toHaveBeenCalledWith("preflight");
		expect(onPublishStage).toHaveBeenCalledWith("publishing");
		expect(onPublishStage).toHaveBeenCalledWith("published");
	});

	it("schedules through the backend API so exact dispatch is registered", async () => {
		const onPublishStage = vi.fn();
		(global.fetch as any)
			.mockResolvedValueOnce(jsonResponse({ ok: true, issues: [], summary: { errors: 0, warnings: 0, infos: 0 } }))
			.mockResolvedValueOnce(jsonResponse({
				postId: "scheduled-1",
				scheduledFor: "2026-05-14T12:00:00.000Z",
				qstashMessageId: "msg-1",
				exactDispatchScheduled: true,
			}));

		const result = await createPost({
			status: "scheduled",
			platform: "threads",
			accountId: "acct-1",
			content: "  schedule me  ",
			scheduledDate: "2026-05-14T12:00:00.000Z",
			mediaUrls: ["image.jpg", ""],
			mediaAltTexts: ["alt"],
			pollAttachment: { options: ["A", "B"] },
			metadata: {
				campaign_factory: {
					audio_intent: {
						schema: "pipeline.audio_intent.v1",
						required: true,
						status: "attached",
					},
				},
			},
			settings: { allowReplies: true, whoCanReply: "followers" },
			idempotencyKey: "composer:schedule:acct-1:0",
			onPublishStage,
		});

		expect(result).toMatchObject({
			id: "scheduled-1",
			content: "schedule me",
			mediaUrls: ["image.jpg"],
			exactDispatchScheduled: true,
		});
		expect(mockFrom).not.toHaveBeenCalledWith("posts");
		expect((global.fetch as any).mock.calls[1][0]).toBe("/api/posts?action=schedule");
		const [, init] = (global.fetch as any).mock.calls[1];
		const body = JSON.parse(init.body);
		expect(body).toMatchObject({
			accountId: "acct-1",
			content: "schedule me",
			scheduledFor: "2026-05-14T12:00:00.000Z",
			pollOptions: ["A", "B"],
			media: [{ type: "image", url: "image.jpg", altText: "alt" }],
			metadata: {
				campaign_factory: {
					audio_intent: {
						schema: "pipeline.audio_intent.v1",
						required: true,
						status: "attached",
					},
				},
			},
		});
		expect(init.headers).toEqual(
			expect.objectContaining({
				"Idempotency-Key": "composer:schedule:acct-1:0",
			}),
		);
		expect(onPublishStage).toHaveBeenCalledWith("preflight");
		expect(onPublishStage).toHaveBeenCalledWith("scheduling");
		expect(onPublishStage).toHaveBeenCalledWith("queued");
	});

	it("updates Campaign Factory audio through the server endpoint", async () => {
		(global.fetch as any).mockResolvedValueOnce(jsonResponse({
			success: true,
			posts: [{ id: "post-1", metadata: { campaign_factory: { audio_intent: { status: "selected" } } } }],
			eventsWritten: 1,
			skipped: [],
		}));

		const result = await updateCampaignFactoryAudioState(
			["post-1"],
			"apply_first_recommendation",
			{
				nowIso: "2026-05-22T12:00:00.000Z",
				proofUrl: "https://instagram.com/p/proof",
				proofType: "native_post_link",
				proofNote: "checked",
			},
		);

		expect(result.eventsWritten).toBe(1);
		expect(result.posts[0]?.id).toBe("post-1");
		expect((global.fetch as any).mock.calls[0][0]).toBe("/api/posts?action=campaign-factory-audio");
		expect(JSON.parse((global.fetch as any).mock.calls[0][1].body)).toEqual({
			postIds: ["post-1"],
			action: "apply_first_recommendation",
			proofUrl: "https://instagram.com/p/proof",
			proofType: "native_post_link",
			proofNote: "checked",
			nowIso: "2026-05-22T12:00:00.000Z",
		});
	});

	it("fetches and parses Campaign Factory audio event history", async () => {
		(global.fetch as any).mockResolvedValueOnce(jsonResponse({
			success: true,
			events: [
				{
					id: "event-1",
					post_id: "post-1",
					campaign_id: "campaign-1",
					rendered_asset_id: "asset-1",
					action: "verified",
					previous_status: "attached",
					next_status: "verified",
					platform_audio_id: "ig_audio_1",
					proof_complete: true,
					reason: "manual_check",
					created_at: "2026-05-22T12:10:00.000Z",
				},
			],
		}));

		const result = await fetchCampaignFactoryAudioEvents({
			postId: "post-1",
			campaignId: "campaign-1",
			renderedAssetId: "asset-1",
			limit: 5,
		});

		expect((global.fetch as any).mock.calls[0][0]).toBe(
			"/api/posts?action=campaign-factory-audio-events&postId=post-1&campaignId=campaign-1&renderedAssetId=asset-1&limit=5",
		);
		expect(result).toEqual([
			expect.objectContaining({
				id: "event-1",
				postId: "post-1",
				campaignId: "campaign-1",
				renderedAssetId: "asset-1",
				action: "verified",
				previousStatus: "attached",
				nextStatus: "verified",
				proofComplete: true,
				nativeAudioLocator: "ig_audio_1",
				reason: "manual_check",
				timestamp: "2026-05-22T12:10:00.000Z",
			}),
		]);
	});

	it("formats Campaign Factory audio event lines for display", () => {
		const event = parseCampaignFactoryAudioEvent({
			action: "apply_first_recommendation",
			previousStatus: "recommended",
			nextStatus: "selected",
			platformUrl: "https://instagram.com/reels/audio/ig_audio_1",
			proofComplete: false,
		});

		expect(event.nativeAudioLocator).toBe("https://instagram.com/reels/audio/ig_audio_1");
		expect(formatCampaignFactoryAudioEventLine(event)).toBe(
			"Apply First Recommendation: Recommended -> Selected",
		);
	});

	it("opts into async publish jobs and polls until published", async () => {
		const onPublishStage = vi.fn();
		const originalSetTimeout = globalThis.setTimeout;
		vi.spyOn(globalThis, "setTimeout").mockImplementation((callback: TimerHandler) => {
			if (typeof callback === "function") callback();
			return 1 as unknown as ReturnType<typeof setTimeout>;
		});
		(global.fetch as any)
			.mockResolvedValueOnce(jsonResponse({ ok: true, issues: [], summary: { errors: 0, warnings: 0, infos: 0 } }))
			.mockResolvedValueOnce(jsonResponse({ jobId: "job-1", status: "queued", stage: "queued", requestId: "req-1" }, true, 202))
			.mockResolvedValueOnce(jsonResponse({
				jobId: "job-1",
				status: "published",
				stage: "published",
				result: { postId: "post-1", threadId: "thread-1" },
				requestId: "req-1",
			}));

		const result = await createPost({
			status: "published",
			platform: "threads",
			accountId: "acct-1",
			content: "publish me",
			asyncPublish: true,
			idempotencyKey: "composer:submit:acct-1:0",
			onPublishStage,
		});

		expect(result).toEqual({ postId: "post-1", threadId: "thread-1" });
		const [, publishInit] = (global.fetch as any).mock.calls[1];
		expect(publishInit.headers).toEqual(expect.objectContaining({ Prefer: "respond-async" }));
		expect((global.fetch as any).mock.calls[2][0]).toContain("/api/jobs?action=publish-status&id=job-1");
		expect(onPublishStage).toHaveBeenCalledWith("queued");
		expect(onPublishStage).toHaveBeenCalledWith("published");
		vi.mocked(globalThis.setTimeout).mockRestore();
		globalThis.setTimeout = originalSetTimeout;
	});

	it("resumes pending publish jobs from local storage", async () => {
		const onPublishStage = vi.fn();
		const originalSetTimeout = globalThis.setTimeout;
		vi.spyOn(globalThis, "setTimeout").mockImplementation((callback: TimerHandler) => {
			if (typeof callback === "function") callback();
			return 1 as unknown as ReturnType<typeof setTimeout>;
		});
		window.localStorage.setItem("juno33.pendingPublishJobs", JSON.stringify(["job-1"]));
		(global.fetch as any).mockResolvedValueOnce(jsonResponse({
			jobId: "job-1",
			status: "published",
			stage: "published",
			result: { postId: "post-1" },
			requestId: "req-1",
		}));

		const result = await resumePendingPublishJobs(onPublishStage);

		expect(result).toHaveLength(1);
		expect(result[0]).toMatchObject({ status: "fulfilled" });
		expect((global.fetch as any).mock.calls[0][0]).toContain("/api/jobs?action=publish-status&id=job-1");
		expect(window.localStorage.getItem("juno33.pendingPublishJobs")).toBeNull();
		expect(onPublishStage).toHaveBeenCalledWith("published");
		vi.mocked(globalThis.setTimeout).mockRestore();
		globalThis.setTimeout = originalSetTimeout;
	});

	it("creates an instagram draft row with normalized media metadata", async () => {
		const insertQuery = query({ data: { id: "draft-1" }, error: null });
		mockFrom.mockReturnValueOnce(insertQuery);

		const result = await createPost({
			status: "draft",
			platform: "instagram",
			instagramAccountId: "ig-1",
			content: " draft ",
			mediaUrls: ["clip.mp4"],
			igMediaType: "REELS",
			altText: "alt",
			collaborators: ["friend"],
			shareToFeed: false,
		});

		expect(result).toMatchObject({ id: "draft-1", content: "draft" });
		expect(insertQuery.insert).toHaveBeenCalledWith(
			expect.objectContaining({
				user_id: "user-1",
				content: "draft",
				platform: "instagram",
				instagram_account_id: "ig-1",
				account_id: null,
				media_type: "reel",
				ig_media_type: "REELS",
				alt_text: "alt",
				collaborators: ["friend"],
				share_to_feed: false,
			}),
		);
	});

	it("updates, duplicates, and deletes local draft rows through Supabase", async () => {
		const updateQuery = query({ data: null, error: null });
		const fetchQuery = query({ data: { threads_post_id: null }, error: null });
		const deleteQuery = query({ data: null, error: null });
		const originalQuery = query({
			data: {
				id: "p1",
				account_id: "acct-1",
				content: "original",
				media_urls: ["a.jpg"],
			},
			error: null,
		});
		const duplicateQuery = query({ data: { id: "copy-1" }, error: null });
		mockFrom
			.mockReturnValueOnce(updateQuery)
			.mockReturnValueOnce(fetchQuery)
			.mockReturnValueOnce(deleteQuery)
			.mockReturnValueOnce(originalQuery)
			.mockReturnValueOnce(duplicateQuery);

		await expect(updatePost("p1", { content: "new", mediaUrls: ["new.mp4"] })).resolves.toMatchObject({
			id: "p1",
			content: "new",
		});
		await expect(deletePost("p1")).resolves.toBeUndefined();
		await expect(duplicatePost("p1")).resolves.toEqual({ id: "copy-1" });

		expect(updateQuery.update).toHaveBeenCalledWith(
			expect.objectContaining({ content: "new", media_urls: ["new.mp4"], media_type: "video" }),
		);
		expect(deleteQuery.delete).toHaveBeenCalled();
		expect(duplicateQuery.insert).toHaveBeenCalledWith(
			expect.objectContaining({ status: "draft", threads_post_id: null, published_at: null }),
		);
	});

	it("deletes published posts through the backend delete endpoint", async () => {
		mockFrom.mockReturnValueOnce(query({ data: { threads_post_id: "th-1" }, error: null }));
		(global.fetch as any).mockResolvedValueOnce(jsonResponse({ ok: true }));

		await deletePost("p1");

		expect(global.fetch).toHaveBeenCalledWith(
			"/api/posts?action=delete",
			expect.objectContaining({
				method: "POST",
				body: JSON.stringify({ postId: "p1" }),
			}),
		);
	});

	it("wraps reply send failures instead of throwing", async () => {
		mockGetSession.mockResolvedValueOnce({ data: { session: null } });
		await expect(sendReply({
			platform: "threads",
			accountId: "acct-1",
			replyToId: "post-1",
			content: "hi",
			kind: "reply",
		})).resolves.toEqual({ ok: false, error: "Not signed in" });

		(global.fetch as any).mockResolvedValueOnce(jsonResponse({ error: "bad" }, false, 400));
		await expect(sendReply({
			platform: "instagram",
			accountId: "ig-1",
			replyToId: "comment-1",
			content: "hi",
			kind: "comment",
		})).resolves.toEqual({ ok: false, error: "bad" });
	});

	it("sends manual inbox replies with an idempotency header", async () => {
		(global.fetch as any).mockResolvedValueOnce(jsonResponse({ replyId: "reply-1" }));

		await expect(sendReply({
			platform: "threads",
			accountId: "acct-1",
			replyToId: "post-1",
			content: "hi",
			kind: "reply",
			idempotencyKey: "inbox-reply:c1:key-1",
		})).resolves.toEqual({ ok: true, replyId: "reply-1" });

		expect(global.fetch).toHaveBeenCalledWith(
			"/api/replies?action=send",
			expect.objectContaining({
				headers: expect.objectContaining({
					"Idempotency-Key": "inbox-reply:c1:key-1",
				}),
			}),
		);
	});

	it("calls small backend helpers and normalizes their responses", async () => {
		(global.fetch as any)
			.mockResolvedValueOnce(jsonResponse({ success: true, repostId: "r1" }))
			.mockResolvedValueOnce(jsonResponse({ posts: [{ id: "ghost" }] }))
			.mockResolvedValueOnce(jsonResponse({ thread: ["a"] }))
			.mockResolvedValueOnce(jsonResponse({ ok: true, id: "pub" }))
			.mockResolvedValueOnce(jsonResponse({ updated: 3 }))
			.mockResolvedValueOnce(jsonResponse({ success: true, post: { id: "p", text: "t", username: "u" } }));

		await expect(repostPost("acct-1", "media-1")).resolves.toEqual({ success: true, repostId: "r1" });
		await expect(fetchGhostPosts("acct-1")).resolves.toEqual([{ id: "ghost" }]);
		await expect(fetchConversation("acct-1", "media-1", true)).resolves.toEqual({ thread: ["a"] });
		await expect(publishPostNow("p1")).resolves.toEqual({ ok: true, id: "pub" });
		await expect(refreshPostMetrics("acct-1")).resolves.toEqual({ updated: 3 });
		await expect(lookupPostByUrl("https://threads.net/@u/post/1")).resolves.toMatchObject({ success: true });
	});

	it("gets a single post and cleans up duplicate thread rows", async () => {
		mockFrom
			.mockReturnValueOnce(query({ data: { id: "p1", content: "one" }, error: null }))
			.mockReturnValueOnce(query({
				data: [
					{ id: "keep", threads_post_id: "th-1", created_at: "2026-05-01" },
					{ id: "dupe", threads_post_id: "th-1", created_at: "2026-05-02" },
					{ id: "other", threads_post_id: "th-2", created_at: "2026-05-03" },
				],
				error: null,
			}))
			.mockReturnValueOnce(query({ data: null, error: null }));

		await expect(getPost("p1")).resolves.toEqual({ id: "p1", content: "one", mapped: true });
		await expect(cleanupDuplicatePosts()).resolves.toEqual({ removed: 1 });
		expect(mockFrom.mock.results[2].value.delete).toHaveBeenCalled();
		expect(mockFrom.mock.results[2].value.in).toHaveBeenCalledWith("id", ["dupe"]);
	});

	it("wires realtime subscription cleanup through realtimeManager", () => {
		const unsubscribe = vi.fn();
		mockSubscribe.mockReturnValue(unsubscribe);
		const onUpdate = vi.fn();

		const stop = subscribeToPostsRealtime("ALL", onUpdate, "threads");
		stop();

		expect(mockSubscribe).toHaveBeenCalledWith(
			"posts:ALL",
			expect.any(Function),
			expect.any(Function),
		);
		expect(unsubscribe).toHaveBeenCalled();
	});
});
