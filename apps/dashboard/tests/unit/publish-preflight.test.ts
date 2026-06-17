import { describe, expect, it } from "vitest";
import { runPublishPreflight } from "../../api/_lib/publishPreflight";

const healthyAccount = {
	found: true,
	isActive: true,
	needsReauth: false,
	status: "active",
	hasAccessToken: true,
	hasPlatformUserId: true,
};

function validStoryCampaignFactory(extraManifest: Record<string, unknown> = {}) {
	return {
		content_surface: "story",
		ig_media_type: "STORIES",
		asset_state: "exportable",
		publishability_failure_reasons: [],
		instagram_post_caption: "",
		handoff_manifest: {
			manifest_version: 2,
			asset_id: "asset_story_1",
			render_file_id: "render_story_1",
			content_fingerprint: "hash_story_1",
			caption_hash: "caption_hash_story_1",
			captionOutcomeContext: {},
			visual_verification_id: "visual_story_1",
			caption_verification_id: "caption_story_1",
			audio_id: "audio_not_required",
			distribution_plan_id: "dist_story_1",
			exported_by_system: "campaign_factory",
			exported_at: "2026-06-08T00:00:00+00:00",
			content_surface: "story",
			ig_media_type: "STORIES",
			mediaItems: [{ type: "image", url: "https://cdn.example.com/story.jpg" }],
			storyQualityGatePassed: true,
			storySourceNative: true,
			storyNoTextRequired: false,
			storyNoTextPassed: true,
			storyStyleApproved: true,
			sourceLineageBlockers: [],
			visualQualityStatus: "passed",
			surfaceReadiness: { canHandoff: true, blockingReasons: [] },
			...extraManifest,
		},
	};
}

describe("publish preflight", () => {
	it("blocks invalid Instagram Trial Reels before publishing", async () => {
		const result = await runPublishPreflight(
			{
				platform: "instagram",
				instagramAccountId: "ig-1",
				content: "Trying this",
				igMediaType: "REELS",
				isTrialReel: true,
				instagramTrialReels: true,
				trialGraduationStrategy: "MANUAL",
				collaborators: ["partner"],
				media: [{ type: "video", url: "https://cdn.example.com/reel.webm" }],
			},
			{ account: healthyAccount },
		);

		expect(result.ok).toBe(false);
		expect(result.issues.map((issue) => issue.code)).toEqual(
			expect.arrayContaining([
				"ig_trial_reel_collaborators",
				"ig_video_format",
				"ig_trial_reel_format",
			]),
		);
	});

	it("blocks Instagram caption, hashtag, collaborator, and sponsor limit drift", async () => {
		const hashtags = Array.from({ length: 31 }, (_, index) => `#tag${index}`).join(" ");
		const result = await runPublishPreflight(
			{
				platform: "instagram",
				instagramAccountId: "ig-1",
				content: hashtags,
				igMediaType: "IMAGE",
				collaborators: ["a", "b", "c", "d"],
				brandedContentSponsorIds: ["1", "2", "3"],
				media: [{ type: "image", url: "https://cdn.example.com/image.jpg" }],
			},
			{ account: healthyAccount },
		);

		expect(result.ok).toBe(false);
		expect(result.issues.map((issue) => issue.code)).toEqual(
			expect.arrayContaining([
				"ig_too_many_hashtags",
				"ig_collaborator_limit",
				"ig_sponsor_limit",
			]),
		);
	});

	it("blocks Instagram Reels that mention DMs, links, bio links, or off-platform contact", async () => {
		const result = await runPublishPreflight(
			{
				platform: "instagram",
				instagramAccountId: "ig-1",
				content: "DM me for the link in bio and subscribe here",
				igMediaType: "REELS",
				media: [{ type: "video", url: "https://cdn.example.com/reel.mp4" }],
			},
			{ account: healthyAccount },
		);

		expect(result.ok).toBe(false);
		expect(result.issues.map((issue) => issue.code)).toContain(
			"ig_reel_caption_link_or_dm_reference",
		);
	});

	it("does not apply Reels discoverability blocking to Instagram Feed or Stories", async () => {
		for (const igMediaType of ["IMAGE", "STORIES"] as const) {
			const result = await runPublishPreflight(
				{
					platform: "instagram",
					instagramAccountId: "ig-1",
					content: "DM me for the link in bio and subscribe here",
					igMediaType,
					media: [{ type: "image", url: "https://cdn.example.com/post.jpg" }],
				},
				{ account: healthyAccount },
			);

			expect(result.issues.map((issue) => issue.code)).not.toContain(
				"ig_reel_caption_link_or_dm_reference",
			);
		}
	});

	it("does not block harmless captions that use the normal word of", async () => {
		const result = await runPublishPreflight(
			{
				platform: "instagram",
				instagramAccountId: "ig-1",
				content: "photo of the day",
				igMediaType: "REELS",
				media: [{ type: "video", url: "https://cdn.example.com/reel.mp4" }],
			},
			{ account: healthyAccount },
		);

		expect(result.issues.map((issue) => issue.code)).not.toContain(
			"ig_reel_caption_link_or_dm_reference",
		);
	});

	it("blocks Campaign Factory Reels when burned caption metadata contains linkout language", async () => {
		const result = await runPublishPreflight(
			{
				platform: "instagram",
				instagramAccountId: "ig-1",
				content: "clean platform caption",
				igMediaType: "REELS",
				media: [{ type: "video", url: "https://cdn.example.com/reel.mp4" }],
				metadata: {
					campaign_factory: {
						content_surface: "reel",
						ig_media_type: "REELS",
						asset_state: "exportable",
						publishability_failure_reasons: [],
						captionOutcomeContext: {
							caption_text: "check my Snapchat",
						},
						handoff_manifest: {
							manifest_version: 1,
							asset_id: "asset_1",
							render_file_id: "render_1",
							content_fingerprint: "hash_1",
							caption_hash: "caption_hash_1",
							captionOutcomeContext: { caption_hash: "caption_hash_1" },
							instagram_post_caption: "clean platform caption",
							instagram_post_caption_hash: "post_caption_hash_1",
							visual_verification_id: "visual_1",
							caption_verification_id: "caption_1",
							audio_id: "audio_1",
							distribution_plan_id: "dist_1",
							exported_by_system: "campaign_factory",
							exported_at: "2026-06-08T00:00:00+00:00",
						},
					},
				},
			},
			{ account: healthyAccount },
		);

		expect(result.ok).toBe(false);
		expect(result.issues.map((issue) => issue.code)).toContain(
			"ig_reel_caption_link_or_dm_reference",
		);
	});

	it("blocks Campaign Factory Stories rejected by visual quality metadata", async () => {
		const result = await runPublishPreflight(
			{
				platform: "instagram",
				instagramAccountId: "ig-1",
				content: "",
				igMediaType: "STORIES",
				media: [{ type: "image", url: "https://cdn.example.com/story.jpg" }],
				metadata: {
					campaign_factory: validStoryCampaignFactory({
						visualQualityStatus: "rejected",
						storyQualityGatePassed: false,
					}),
				},
			},
			{ account: healthyAccount },
		);

		expect(result.ok).toBe(false);
		expect(result.issues.map((issue) => issue.code)).toEqual(
			expect.arrayContaining([
				"campaign_factory_story_quality_failed",
				"campaign_factory_visual_quality_rejected",
			]),
		);
	});

	it("allows valid Campaign Factory Stories without requiring a post caption", async () => {
		const result = await runPublishPreflight(
			{
				platform: "instagram",
				instagramAccountId: "ig-1",
				content: "",
				igMediaType: "STORIES",
				media: [{ type: "image", url: "https://cdn.example.com/story.jpg" }],
				metadata: {
					campaign_factory: validStoryCampaignFactory(),
				},
			},
			{ account: healthyAccount },
		);

		expect(result.issues.map((issue) => issue.code)).not.toContain(
			"campaign_factory_instagram_post_caption_missing",
		);
		expect(result.issues.map((issue) => issue.code)).not.toContain(
			"campaign_factory_story_quality_failed",
		);
	});

	it("blocks Threads-only attachment combinations and expired tokens", async () => {
		const result = await runPublishPreflight(
			{
				platform: "threads",
				accountId: "threads-1",
				content: "Post with media",
				media: [{ type: "image", url: "https://cdn.example.com/post.webp" }],
				linkUrl: "https://example.com",
				pollAttachment: { options: ["yes"] },
			},
			{
				account: {
					...healthyAccount,
					tokenExpiresAt: "2020-01-01T00:00:00.000Z",
				},
			},
		);

		expect(result.ok).toBe(false);
		expect(result.issues.map((issue) => issue.code)).toEqual(
			expect.arrayContaining([
				"token_expired",
				"threads_link_text_only",
				"threads_poll_text_only",
				"threads_poll_options",
				"threads_image_format",
			]),
		);
	});

	it("downgrades Instagram Notify Me token blockers to warnings", async () => {
		const result = await runPublishPreflight(
			{
				platform: "instagram",
				mode: "native-handoff",
				instagramAccountId: "ig-1",
				content: "Manual handoff",
				igMediaType: "REELS",
				media: [{ type: "video", url: "https://cdn.example.com/reel.mov" }],
			},
			{
				account: {
					...healthyAccount,
					needsReauth: true,
					status: "needs_reauth",
					hasAccessToken: false,
					tokenExpiresAt: "2020-01-01T00:00:00.000Z",
				},
			},
		);

		expect(result.ok).toBe(true);
		expect(result.summary.errors).toBe(0);
		expect(result.issues.map((issue) => issue.code)).toEqual(
			expect.arrayContaining([
				"account_needs_reauth",
				"account_missing_token",
				"token_expired",
			]),
		);
		expect(result.issues.every((issue) => issue.severity === "warning")).toBe(
			true,
		);
	});

	it("allows Instagram media-only posts through preflight", async () => {
		const result = await runPublishPreflight(
			{
				platform: "instagram",
				instagramAccountId: "ig-1",
				content: "",
				igMediaType: "REELS",
				media: [{ type: "video", url: "https://cdn.example.com/reel.mov" }],
			},
			{ account: healthyAccount },
		);

		expect(result.ok).toBe(true);
		expect(result.issues.map((issue) => issue.code)).not.toContain(
			"content_required",
		);
	});

	it("passes a valid Threads text post with a cross-share flag", async () => {
		const result = await runPublishPreflight(
			{
				platform: "threads",
				accountId: "threads-1",
				content: "A clean text post",
				crossreshareToIg: true,
			},
			{ account: healthyAccount },
		);

		expect(result.ok).toBe(true);
		expect(result.summary.errors).toBe(0);
	});

	it("counts Threads text as UTF-8 bytes and caps carousels at 20 items", async () => {
		const result = await runPublishPreflight(
			{
				platform: "threads",
				accountId: "threads-1",
				content: "😀".repeat(126),
				media: Array.from({ length: 21 }, (_, index) => ({
					type: "image",
					url: `https://cdn.example.com/post-${index}.jpg`,
				})),
			},
			{ account: healthyAccount },
		);

		expect(result.ok).toBe(false);
		expect(result.issues.map((issue) => issue.code)).toEqual(
			expect.arrayContaining([
				"threads_caption_too_long",
				"threads_carousel_count",
			]),
		);
	});
});
