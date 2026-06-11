import { describe, expect, it } from "vitest";
import { validateCampaignSurfaceDraftPayload } from "../../api/_lib/handlers/posts/campaignSurfaceValidation.js";

function baseCampaign(surface: string, extraManifest: Record<string, unknown> = {}) {
	return {
		asset_state: "exportable",
		content_surface: surface,
		instagram_post_caption: "new post",
		handoff_manifest: {
			manifest_version: 2,
			exported_by_system: "campaign_factory",
			content_surface: surface,
			...extraManifest,
		},
	};
}

describe("validateCampaignSurfaceDraftPayload", () => {
	it("accepts feed_single image drafts with manifest v2 and post caption", () => {
		const result = validateCampaignSurfaceDraftPayload({
			content_surface: "feed_single",
			ig_media_type: "IMAGE",
			content: "feed caption",
			media_urls: ["https://cdn.example.com/stacey.jpg"],
			metadata: {
				campaign_factory: baseCampaign("feed_single"),
			},
		});

		expect(result).toMatchObject({
			ok: true,
			contentSurface: "feed_single",
			igMediaType: "IMAGE",
			mediaItemCount: 1,
			blockers: [],
			wouldWrite: false,
		});
	});

	it("accepts story drafts without requiring an Instagram post caption", () => {
		const result = validateCampaignSurfaceDraftPayload({
			content_surface: "story",
			ig_media_type: "STORIES",
			media_urls: ["https://cdn.example.com/story.mp4"],
			metadata: {
				campaign_factory: {
					asset_state: "exportable",
					content_surface: "story",
						handoff_manifest: {
							manifest_version: 2,
							exported_by_system: "campaign_factory",
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
						},
					},
				},
			});

		expect(result.ok).toBe(true);
		expect(result.blockers).not.toContain("story_instagram_post_caption_missing");
		expect(result.preservedFields.instagramPostCaption).toBe(false);
		expect(result.preservedFields.discoverabilitySafe).toBe(true);
	});

	it("blocks Campaign Story drafts when Story quality proof failed", () => {
		const result = validateCampaignSurfaceDraftPayload({
			content_surface: "story",
			ig_media_type: "STORIES",
			media_urls: ["https://cdn.example.com/story.jpg"],
			metadata: {
				campaign_factory: {
					asset_state: "exportable",
					content_surface: "story",
					handoff_manifest: {
						manifest_version: 2,
						exported_by_system: "campaign_factory",
						content_surface: "story",
						ig_media_type: "STORIES",
						mediaItems: [{ type: "image", url: "https://cdn.example.com/story.jpg" }],
						storyQualityGatePassed: false,
						storySourceNative: true,
						storyNoTextRequired: true,
						storyNoTextPassed: false,
						storyStyleApproved: true,
						sourceLineageBlockers: [],
						visualQualityStatus: "passed",
						surfaceReadiness: { canHandoff: false, blockingReasons: ["story_no_text_violation"] },
					},
				},
			},
		});

		expect(result.ok).toBe(false);
		expect(result.blockers).toEqual(
			expect.arrayContaining([
				"story_quality_gate_failed",
				"story_no_text_failed",
				"surface_readiness_blocked",
			]),
		);
	});

	it("blocks Campaign Story drafts with Reel source lineage blockers", () => {
		const result = validateCampaignSurfaceDraftPayload({
			content_surface: "story",
			ig_media_type: "STORIES",
			media_urls: ["https://cdn.example.com/story.jpg"],
			metadata: {
				campaign_factory: {
					asset_state: "exportable",
					content_surface: "story",
					handoff_manifest: {
						manifest_version: 2,
						exported_by_system: "campaign_factory",
						content_surface: "story",
						ig_media_type: "STORIES",
						mediaItems: [{ type: "image", url: "https://cdn.example.com/story.jpg" }],
						storyQualityGatePassed: true,
						storySourceNative: false,
						storyNoTextRequired: false,
						storyNoTextPassed: true,
						storyStyleApproved: true,
						sourceLineageBlockers: ["story_source_must_be_raw_not_rendered_reel_asset"],
						visualQualityStatus: "passed",
						surfaceReadiness: { canHandoff: false, blockingReasons: ["story_source_must_be_raw_not_rendered_reel_asset"] },
					},
				},
			},
		});

		expect(result.ok).toBe(false);
		expect(result.blockers).toEqual(
			expect.arrayContaining([
				"story_source_not_native",
				"story_source_lineage_blocked",
				"surface_readiness_blocked",
			]),
		);
	});

	it("accepts feed_carousel drafts only when ordered mediaItems are preserved", () => {
		const result = validateCampaignSurfaceDraftPayload({
			content_surface: "feed_carousel",
			ig_media_type: "CAROUSEL",
			content: "carousel caption",
			metadata: {
				campaign_factory: baseCampaign("feed_carousel", {
					mediaItems: [
						{ type: "image", url: "https://cdn.example.com/1.jpg" },
						{ type: "image", url: "https://cdn.example.com/2.jpg" },
					],
				}),
			},
		});

		expect(result.ok).toBe(true);
		expect(result.mediaItemCount).toBe(2);
		expect(result.preservedFields.orderedMediaItems).toBe(true);
	});

	it("blocks carousel drafts that only provide unordered media_urls", () => {
		const result = validateCampaignSurfaceDraftPayload({
			content_surface: "feed_carousel",
			ig_media_type: "CAROUSEL",
			content: "carousel caption",
			media_urls: [
				"https://cdn.example.com/1.jpg",
				"https://cdn.example.com/2.jpg",
			],
			metadata: {
				campaign_factory: baseCampaign("feed_carousel"),
			},
		});

		expect(result.ok).toBe(false);
		expect(result.blockers).toContain("feed_carousel_ordered_media_items_missing");
	});

	it("blocks surface/media-type mismatches", () => {
		const result = validateCampaignSurfaceDraftPayload({
			content_surface: "story",
			ig_media_type: "IMAGE",
			media_urls: ["https://cdn.example.com/story.jpg"],
			metadata: {
				campaign_factory: baseCampaign("story"),
			},
		});

		expect(result.ok).toBe(false);
		expect(result.blockers).toContain("ig_media_type_surface_mismatch:IMAGE:STORIES");
	});

	it("blocks Campaign surface drafts missing ig_media_type", () => {
		const result = validateCampaignSurfaceDraftPayload({
			content_surface: "feed_single",
			content: "feed caption",
			media_urls: ["https://cdn.example.com/stacey.jpg"],
			metadata: {
				campaign_factory: baseCampaign("feed_single"),
			},
		});

		expect(result.ok).toBe(false);
		expect(result.blockers).toContain("ig_media_type_unresolvable");
	});

	it("blocks manifest v1 for non-Reel surface drafts", () => {
		const result = validateCampaignSurfaceDraftPayload({
			content_surface: "feed_single",
			ig_media_type: "IMAGE",
			content: "feed caption",
			media_urls: ["https://cdn.example.com/stacey.jpg"],
			metadata: {
				campaign_factory: {
					...baseCampaign("feed_single"),
					handoff_manifest: {
						manifest_version: 1,
						exported_by_system: "campaign_factory",
						content_surface: "feed_single",
					},
				},
			},
		});

		expect(result.ok).toBe(false);
		expect(result.blockers).toContain("handoff_manifest_v2_required");
	});

	it("blocks feed surface drafts with discoverability-unsafe post captions", () => {
		const result = validateCampaignSurfaceDraftPayload({
			content_surface: "feed_single",
			ig_media_type: "IMAGE",
			content: "check the link in bio",
			media_urls: ["https://cdn.example.com/stacey.jpg"],
			metadata: {
				campaign_factory: baseCampaign("feed_single"),
			},
		});

		expect(result.ok).toBe(false);
		expect(result.blockers).toContain("discoverability_safety_failed");
		expect(result.discoverabilitySafe).toBe(false);
		expect(result.blockedReason).toBe(
			"discoverability_risk_link_dm_or_off_platform_reference",
		);
	});

	it("blocks story text and future CTA language that points users off platform", () => {
		const result = validateCampaignSurfaceDraftPayload({
			content_surface: "story",
			ig_media_type: "STORIES",
			media_urls: ["https://cdn.example.com/story.jpg"],
			metadata: {
				campaign_factory: {
					asset_state: "exportable",
					content_surface: "story",
					story_cta_text: "Snap me",
					handoff_manifest: {
						manifest_version: 2,
						exported_by_system: "campaign_factory",
						content_surface: "story",
						story_text: "new story",
					},
				},
			},
		});

		expect(result.ok).toBe(false);
		expect(result.blockers).toContain("discoverability_safety_failed");
		expect(result.blockedTerms.map((term) => term.reason)).toContain(
			"off_platform_reference",
		);
	});
});
