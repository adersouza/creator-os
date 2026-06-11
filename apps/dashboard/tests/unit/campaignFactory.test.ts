import { describe, expect, it } from "vitest";
import {
	campaignFactoryDraftUpdate,
	campaignFactoryCanExport,
	campaignFactoryPublishabilityFailureReasons,
	explainPublishability,
	computeCampaignFactoryReuseCounts,
	filterCampaignFactoryPosts,
	hasActiveCampaignFactoryFilters,
	getCampaignFactoryDailyProductionRows,
	getCampaignFactoryDetailRows,
	getCampaignFactoryLongDetailRows,
	formatCampaignFactoryReuseLabels,
	formatCampaignFactoryScheduleMode,
	formatCampaignFactorySurface,
	getCampaignFactoryMetadata,
	getCampaignFactoryPerformancePayload,
	getCampaignFactoryPerformanceLineage,
	isCampaignFactoryDraft,
	sortCampaignFactoryDraftQueue,
	validateCampaignFactoryHandoffManifest,
} from "@/lib/campaignFactory";

const cf = (overrides: Record<string, unknown> = {}) => ({
	campaign_factory: {
		campaign_id: "downloads_test",
		asset_state: "publishable_candidate",
		approved: true,
		captioned_render_present: true,
		visible_caption_verification: "pass",
		expected_visual_verification: "pass",
		content_fingerprint: "content-fp-1",
		readiness_checks_pass: true,
		source_asset_id: "src_1",
		rendered_asset_id: "asset_1",
		content_hash: "sha256-content",
		rendered_hash: "sha256-rendered",
		source_content_hash: "sha256-source",
		caption_hash: "sha256-caption",
		captionOutcomeContext: {
			schema: "campaign_factory.caption_outcome_context.v1",
			caption_hash: "sha256-caption",
		},
		handoff_manifest: {
			manifest_version: 1,
			asset_id: "asset_1",
			render_file_id: "render_file_1",
			content_fingerprint: "content-fp-1",
			caption_hash: "sha256-caption",
			captionOutcomeContext: {
				schema: "campaign_factory.caption_outcome_context.v1",
				caption_hash: "sha256-caption",
			},
			visual_verification_id: "visual_verify_1",
			caption_verification_id: "caption_verify_1",
			audio_id: "ig_audio_1",
			distribution_plan_id: "dist_1",
			exported_by_system: "campaign_factory",
			exported_at: "2026-06-04T12:05:00Z",
		},
		audio_intent: {
			schema: "pipeline.audio_intent.v1",
			mode: "native_platform_audio",
			required: true,
			status: "selected",
			platform: "instagram",
			recommendations: [],
			operator_selection: {
				platform_audio_id: "ig_audio_1",
				selected_at: "2026-06-04T12:00:00Z",
			},
			gates: { allow_draft_export: true, allow_publish: false },
		},
		recipe: "v06_zoom",
		export_id: "tdexp_1",
		audit_status: "needs_review",
		readiness_status: "warning",
		model_id: "model_slug",
		model_slug: "stacey",
		distribution_surface: "trial_reel",
		distribution_plan_id: "dist_1",
		paired_rendered_asset_id: "asset_pair",
		distribution_reason_code: "test_uncertain_winner",
		smart_link: "https://example.com/stacey",
		cta_text: "new post is up",
		trial_reel: true,
		schedule_mode: "preview",
		content_pillar: "lifestyle",
		cta_type: "profile_visit",
		language: "en",
		contentforge_run_id: "cfrun_1",
		contentforge_report_id: "cfreport_1",
		planned_account_handle: "@larissa",
		planned_window_start: "2026-05-15T10:00:00-04:00",
		planned_window_end: "2026-05-15T12:00:00-04:00",
		assignment_notes: "morning review batch",
		caption_generation: {
			generationId: "capgen_1",
			model: "llama3.2:3b",
		},
		reference_pattern: {
			clusterKey: "mirror_selfie::relationship",
			visualFormat: "mirror_selfie",
		},
		source_prompt: {
			schema: "campaign_factory.finished_video_intake.v1",
			formatType: "mirror_selfie",
			promptId: "prompt_1",
		},
		generated_asset_lineage: {
			schema: "campaign_factory.generated_asset_lineage.v1",
			source: {
				referenceId: "ref_1",
				patternCardId: "pattern_1",
				promptId: "prompt_1",
				formatType: "mirror_selfie",
			},
			generation: {
				tool: "higgsfield_kling_manual",
				modelProfile: "soul_main",
			},
			review: {
				humanReviewRequired: true,
				status: "draft",
			},
		},
		daily_production: {
			schema: "campaign_factory.daily_production_counters.v1",
			targetBaseVideos: 10,
			promptReady: 3,
			generated: 2,
			sentToPipeline: 16,
			reviewed: 9,
			postedOrScheduled: 4,
			remainingBaseVideos: 8,
			primaryMetric: "views_reach",
		},
		...overrides,
	},
});

describe("Campaign Factory helpers", () => {
	it("reads Campaign Factory metadata without requiring normal posts to have it", () => {
		expect(getCampaignFactoryMetadata({ metadata: cf() })).toMatchObject({
			campaign_id: "downloads_test",
			recipe: "v06_zoom",
			audit_status: "needs_review",
			distribution_surface: "trial_reel",
			smart_link: "https://example.com/stacey",
			planned_window_start: "2026-05-15T10:00:00-04:00",
			caption_generation: {
				generationId: "capgen_1",
				model: "llama3.2:3b",
			},
			generated_asset_lineage: {
				source: {
					referenceId: "ref_1",
					patternCardId: "pattern_1",
					promptId: "prompt_1",
					formatType: "mirror_selfie",
				},
				generation: {
					tool: "higgsfield_kling_manual",
					modelProfile: "soul_main",
				},
			},
			daily_production: {
				targetBaseVideos: 10,
				promptReady: 3,
				generated: 2,
				sentToPipeline: 16,
				reviewed: 9,
				postedOrScheduled: 4,
				remainingBaseVideos: 8,
				primaryMetric: "views_reach",
			},
		});
		expect(getCampaignFactoryMetadata({ metadata: { composerDraft: {} } })).toBeNull();
	});

	it("formats daily production counters for the post detail panel", () => {
		const metadata = getCampaignFactoryMetadata({ metadata: cf() });
		const rows = metadata ? getCampaignFactoryDailyProductionRows(metadata) : [];

		expect(rows).toContainEqual({ label: "Generated", value: 2 });
		expect(rows).toContainEqual({ label: "Sent to pipeline", value: 16 });
		expect(rows).toContainEqual({ label: "Metric", value: "views_reach" });
	});

	it("formats prompt and pattern lineage for the post detail panel", () => {
		const metadata = getCampaignFactoryMetadata({ metadata: cf() });
		const detailRows = metadata ? getCampaignFactoryDetailRows(metadata) : [];
		const longRows = metadata ? getCampaignFactoryLongDetailRows(metadata) : [];

		expect(detailRows).toContainEqual({ label: "Format", value: "mirror_selfie" });
		expect(detailRows).toContainEqual({ label: "Pattern", value: "pattern_1", kind: "id" });
		expect(detailRows).toContainEqual({ label: "Prompt", value: "prompt_1", kind: "id" });
		expect(detailRows).toContainEqual({ label: "Generator", value: "higgsfield_kling_manual" });
		expect(longRows).toContainEqual({ label: "reference_id", value: "ref_1" });
		expect(longRows).toContainEqual({ label: "generation_model", value: "soul_main" });
	});

	it("parses generated Higgsfield/Kling lineage from Campaign Factory drafts", () => {
		const metadata = getCampaignFactoryMetadata({
			metadata: cf({
				generated_asset_lineage: {
					schema: "campaign_factory.generated_asset_lineage.v1",
					source: {
						referenceId: "ref_d67ed607bf9554fd",
						patternCardId: "pattern_mirror_selfie",
						promptId: "prompt_outfit",
						formatType: "mirror_selfie",
						promptSchemaVersion: "imageat_higgsfield.v1",
					},
					generation: {
						tool: "higgsfield_kling_cli",
						modelProfile: "Stacey",
						soulId: "5828d958-91dd-4d6d-8909-934503f47644",
						imageModel: "text2image_soul_v2",
						videoModel: "kling3_0",
						imageCandidates: [
							{ candidateIndex: 1, selected: true, localPath: "/tmp/still_1.png" },
							{ candidateIndex: 2, selected: false, localPath: "/tmp/still_2.png" },
							{ candidateIndex: 3, selected: false, localPath: "/tmp/still_3.png" },
						],
						selectedCandidateIndex: 1,
						selectedImagePath: "/tmp/still_1.png",
						variationGrid: {
							provider: "grok_image",
							status: "generated",
							path: "/tmp/variation_grid.png",
						},
						assetPath: "/tmp/kling_video.mp4",
						videoJobId: "fa5f94d4-a46f-4a94-a7ee-9036a4907f64",
						cost: { estimatedCredits: 8.36, currency: "higgsfield_credits" },
					},
					review: { humanReviewRequired: true, status: "draft" },
					quality: {
						promptScore: {
							schema: "reference_factory.prompt_quality_score.v1",
							score: 100,
							status: "pass",
						},
					},
				},
			}),
		});

		expect(metadata?.generated_asset_lineage?.source).toMatchObject({
			referenceId: "ref_d67ed607bf9554fd",
			promptSchemaVersion: "imageat_higgsfield.v1",
		});
		expect(metadata?.generated_asset_lineage?.generation).toMatchObject({
			tool: "higgsfield_kling_cli",
			modelProfile: "Stacey",
			videoModel: "kling3_0",
			variationGrid: { provider: "grok_image", status: "generated" },
		});
		expect(metadata?.generated_asset_lineage?.quality).toMatchObject({
			promptScore: { score: 100, status: "pass" },
		});
	});

	it("filters by campaign ID, audit status, content pillar, CTA, language, and recipe", () => {
		const posts = [
			{ id: "p1", platform: "instagram", status: "draft", instagram_account_id: "ig_1", metadata: cf() },
			{
				id: "p2",
				platform: "instagram",
				status: "draft",
				instagram_account_id: "ig_2",
				metadata: cf({
					campaign_id: "other",
					model_id: "other_model",
					source_asset_id: "src_other",
					rendered_asset_id: "asset_other",
					audit_status: "pending",
					content_pillar: "education",
					cta_type: "comments",
					language: "es",
					recipe: "v01_static",
				}),
			},
			{ id: "p3", platform: "threads", status: "draft", metadata: {} },
		];

		expect(
			filterCampaignFactoryPosts(posts, {
				only: true,
				campaignId: "downloads",
				modelId: "stacey",
				sourceAssetId: "src_1",
				renderedAssetId: "asset_1",
				auditStatus: "needs_review",
				contentPillar: "life",
				ctaType: "profile",
				language: "en",
				recipe: "zoom",
				instagramAccountId: "ig_1",
				status: "draft",
			}).map((post) => post.id),
		).toEqual(["p1"]);
		expect(hasActiveCampaignFactoryFilters({ auditStatus: "all", status: "all" })).toBe(false);
	});

	it("computes non-blocking reuse counts across draft, scheduled, and published posts", () => {
		const target = { id: "target", platform: "instagram", status: "draft", metadata: cf() };
		const counts = computeCampaignFactoryReuseCounts(
			[
				target,
				{ id: "render", status: "scheduled", metadata: cf({ caption_hash: "different-caption" }) },
				{ id: "source", status: "published", metadata: cf({ rendered_asset_id: "asset_2" }) },
				{ id: "caption", status: "draft", metadata: cf({ rendered_asset_id: "asset_3", source_content_hash: "source-2" }) },
				{ id: "failed", status: "failed", metadata: cf() },
				{ id: "plain", status: "draft", metadata: {} },
			],
			target,
		);

		expect(counts).toEqual({
			renderedAsset: 1,
			sourceAsset: 3,
			contentHash: 3,
			sourceContentHash: 2,
			captionHash: 2,
			recipe: 3,
		});
		expect(formatCampaignFactoryReuseLabels(counts)).toContain("same render used 1 time");
		expect(formatCampaignFactoryReuseLabels(counts)).toContain("same source asset used 3 times");
		expect(formatCampaignFactoryReuseLabels(counts)).toContain("same caption used 2 times");
		expect(formatCampaignFactoryReuseLabels(counts)).toContain("same recipe used 3 times");
	});

	it("identifies Instagram draft review rows and keeps updates as draft-only", () => {
		const post = { platform: "instagram", status: "draft", metadata: cf() };
		expect(isCampaignFactoryDraft(post)).toBe(true);
		expect(campaignFactoryDraftUpdate("new caption")).toEqual({
			content: "new caption",
			status: "draft",
			scheduledDate: null,
		});
		expect(campaignFactoryDraftUpdate("new caption")).not.toHaveProperty("publishedAt");
	});

	it("distinguishes approved proofs from publishable candidates", () => {
		const publishable = getCampaignFactoryMetadata({ metadata: cf() });
		expect(campaignFactoryCanExport(publishable)).toBe(true);
		expect(campaignFactoryPublishabilityFailureReasons(publishable)).toEqual([]);
		expect(validateCampaignFactoryHandoffManifest(publishable)).toEqual([]);
		expect(explainPublishability("asset_1", [{ metadata: cf() }])).toMatchObject({
			decision: "pass",
			state: "publishable_candidate",
			checks: {
				creative_approved: true,
				captioned_render_present: true,
				visible_caption_verification: true,
				expected_visual_verification: true,
				content_fingerprint_present: true,
				caption_hash_present: true,
				captionOutcomeContext_present: true,
				audio_assigned: true,
				readiness_checks_pass: true,
				quarantine_clear: true,
			},
		});

		const approvedButInvalid = getCampaignFactoryMetadata({
			metadata: cf({
				asset_state: "approved_but_not_publishable",
				captioned_render_present: false,
				visible_caption_verification: "fail",
				expected_visual_verification: "pass",
				content_fingerprint: undefined,
				caption_hash: undefined,
				captionOutcomeContext: undefined,
				handoff_manifest: undefined,
				audio_intent: {
					schema: "pipeline.audio_intent.v1",
					mode: "native_platform_audio",
					required: true,
					status: "recommended",
					platform: "instagram",
					recommendations: [],
					gates: { allow_draft_export: false, allow_publish: false },
				},
				readiness_checks_pass: false,
			}),
		});

		expect(campaignFactoryCanExport(approvedButInvalid)).toBe(false);
		expect(validateCampaignFactoryHandoffManifest(approvedButInvalid)).toContain(
			"handoff_manifest is required",
		);
		expect(campaignFactoryPublishabilityFailureReasons(approvedButInvalid)).toEqual(
			expect.arrayContaining([
				"missing_burned_captions",
				"missing_caption_hash",
				"missing_caption_outcome_context",
				"missing_content_fingerprint",
				"missing_audio",
				"readiness_failed",
			]),
		);
	});

	it("rejects handoff manifests that do not match Campaign Factory metadata", () => {
		const metadata = getCampaignFactoryMetadata({
			metadata: cf({
				handoff_manifest: {
					manifest_version: 1,
					asset_id: "wrong_asset",
					render_file_id: "render_file_1",
					content_fingerprint: "wrong-fp",
					caption_hash: "wrong-caption",
					captionOutcomeContext: {
						schema: "campaign_factory.caption_outcome_context.v1",
						caption_hash: "wrong-caption",
					},
					visual_verification_id: "visual_verify_1",
					caption_verification_id: "caption_verify_1",
					audio_id: "ig_audio_1",
					distribution_plan_id: "dist_1",
					exported_by_system: "campaign_factory",
					exported_at: "2026-06-04T12:05:00Z",
				},
			}),
		});

		expect(validateCampaignFactoryHandoffManifest(metadata)).toEqual(
			expect.arrayContaining([
				"handoff_manifest.asset_id mismatch",
				"handoff_manifest.content_fingerprint mismatch",
				"handoff_manifest.caption_hash mismatch",
				"handoff_manifest.captionOutcomeContext.caption_hash mismatch",
			]),
		);
		expect(campaignFactoryCanExport(metadata)).toBe(false);
	});

	it("exposes read-only performance lineage keys", () => {
		expect(getCampaignFactoryPerformanceLineage({ metadata: cf() })).toEqual({
			rendered_asset_id: "asset_1",
			source_asset_id: "src_1",
			campaign_id: "downloads_test",
			content_hash: "sha256-content",
			caption_hash: "sha256-caption",
		});
	});

	it("returns detail rows with short metadata separate from long hashes", () => {
		const metadata = getCampaignFactoryMetadata({ metadata: cf() });
		expect(metadata).toBeTruthy();
		const detailRows = getCampaignFactoryDetailRows(metadata!);
		const longRows = getCampaignFactoryLongDetailRows(metadata!);

		expect(detailRows).toEqual(
			expect.arrayContaining([
				expect.objectContaining({ label: "Campaign", value: "downloads_test" }),
				expect.objectContaining({ label: "Surface", value: "Trial" }),
				expect.objectContaining({ label: "Smart link", value: "https://example.com/stacey" }),
				expect.objectContaining({ label: "ContentForge run", value: "cfrun_1" }),
				expect.objectContaining({ label: "Planned account", value: "@larissa" }),
			]),
		);
		expect(longRows).toEqual(
			expect.arrayContaining([
				expect.objectContaining({ label: "source_asset_id", value: "src_1" }),
				expect.objectContaining({ label: "distribution_plan_id", value: "dist_1" }),
				expect.objectContaining({ label: "rendered_hash", value: "sha256-rendered" }),
			]),
		);
		expect(formatCampaignFactorySurface(metadata)).toBe("Trial");
		expect(formatCampaignFactorySurface({ distribution_surface: "story_cta" })).toBe("Story CTA");
		expect(formatCampaignFactoryScheduleMode(metadata)).toBe("Preview");
		expect(formatCampaignFactoryScheduleMode({ schedule_mode: "LIVE" })).toBe("Live");
	});

	it("sorts the Campaign Factory draft queue newest first with readiness grouping fallback", () => {
		const posts = [
			{ id: "ready", platform: "instagram", status: "draft", createdAt: "2026-05-14T10:00:00Z", instagramAccountId: "ig_b", metadata: cf({ readiness_status: "ready", campaign_id: "b" }) },
			{ id: "blocked", platform: "instagram", status: "draft", createdAt: "2026-05-14T10:00:00Z", instagramAccountId: "ig_a", metadata: cf({ readiness_status: "blocked", campaign_id: "a" }) },
			{ id: "newest", platform: "instagram", status: "draft", createdAt: "2026-05-14T11:00:00Z", metadata: cf({ readiness_status: "ready" }) },
		];

		expect(sortCampaignFactoryDraftQueue(posts).map((post) => post.id)).toEqual([
			"newest",
			"blocked",
			"ready",
		]);
	});

	it("normalizes Campaign Factory performance payload metrics when fields are missing or null", () => {
		const payload = getCampaignFactoryPerformancePayload({
			id: "post_1",
			status: "published",
			instagram_account_id: "ig_1",
			media_urls: ["https://cdn.example/reel.mp4"],
			published_at: "2026-05-14T12:00:00Z",
			permalink: "https://instagram.com/reel/abc",
			ig_views: 12,
			likes_count: null,
			ig_comment_count: 3,
			ig_shares: 2,
			metadata: cf(),
		});

		expect(payload).toMatchObject({
			post_id: "post_1",
			status: "published",
			views: 12,
			likes: 0,
			comments: 3,
			replies: 3,
			shares: 2,
			saves: 0,
			reach: 0,
			published_at: "2026-05-14T12:00:00Z",
			permalink: "https://instagram.com/reel/abc",
			instagram_account_id: "ig_1",
			media_urls: ["https://cdn.example/reel.mp4"],
		});
		expect(payload.campaign_factory?.campaign_id).toBe("downloads_test");
	});
});
