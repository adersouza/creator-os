import { describe, expect, it } from "vitest";
import { runPublishPreflight } from "../api/_lib/publishPreflight.js";

const account = {
	found: true,
	isActive: true,
	needsReauth: false,
	status: "active",
	hasAccessToken: true,
	hasPlatformUserId: true,
};

const media = [{ type: "video", url: "https://example.com/reel.mp4" }];

function inputWithAudioStatus(status: string, audioName?: string) {
	const operator_selection =
		status === "attached" || status === "verified"
			? {
					platform_audio_id: "ig_audio_1",
					selected_at: "2026-05-22T12:00:00.000Z",
					...(status === "attached"
						? { attached_at: "2026-05-22T12:05:00.000Z" }
						: { verified_at: "2026-05-22T12:10:00.000Z" }),
				}
			: undefined;
	return {
		platform: "instagram" as const,
		instagramAccountId: "ig_1",
		content: "caption",
		igMediaType: "REELS",
		media,
		audioName,
		metadata: {
			campaign_factory: {
				campaign_id: "may",
				asset_id: "asset_1",
				rendered_asset_id: "asset_1",
				asset_state: "exportable",
				approved: true,
				captioned_render_present: true,
				visible_caption_verification: "pass",
				expected_visual_verification: "pass",
				readiness_checks_pass: true,
				content_hash: "sha256-content",
				content_fingerprint: "sha256-content",
				caption_hash: "sha256-caption",
				instagram_post_caption: "caption",
				instagram_post_caption_hash: "sha256-post-caption",
				captionOutcomeContext: {
					schema: "campaign_factory.caption_outcome_context.v1",
					caption_hash: "sha256-caption",
					caption_text: "caption",
				},
				publishability_failure_reasons: [],
				quarantined: false,
				visualQcStatus: "passed",
				identityVerificationStatus: "passed",
				handoff_manifest: {
					manifest_version: 1,
					asset_id: "asset_1",
					render_file_id: "render_file_1",
					content_fingerprint: "sha256-content",
					caption_hash: "sha256-caption",
					instagram_post_caption: "caption",
					instagram_post_caption_hash: "sha256-post-caption",
					post_caption_style: "short_natural",
					captionOutcomeContext: {
						schema: "campaign_factory.caption_outcome_context.v1",
						caption_hash: "sha256-caption",
						caption_text: "caption",
					},
					visual_verification_id: "visual_verification_1",
					caption_verification_id: "caption_verification_1",
					audio_id: "ig_audio_1",
					distribution_plan_id: "dist_1",
					exported_by_system: "campaign_factory",
					exported_at: "2026-06-04T12:00:00Z",
					visualQcStatus: "passed",
					identityVerificationStatus: "passed",
					visualQc: {
						visualQcStatus: "passed",
						status: "passed",
					},
					identityVerification: {
						schema: "reel_factory.identity_verification.v1",
						status: "passed",
						score: 0.91,
					},
				},
				audio_intent: {
					schema: "pipeline.audio_intent.v1",
					required: true,
					status,
					...(operator_selection ? { operator_selection } : {}),
				},
			},
		},
	};
}

describe("publish preflight Campaign Factory gates", () => {
	it("accepts Campaign Factory feed_single handoff manifest v2", async () => {
		const input = inputWithAudioStatus("not_required");
		input.igMediaType = "IMAGE";
		input.media = [{ type: "image", url: "https://example.com/feed.png" }];
		input.metadata.campaign_factory.content_surface = "feed_single";
		input.metadata.campaign_factory.ig_media_type = "IMAGE";
		input.metadata.campaign_factory.audio_intent.required = false;
		input.metadata.campaign_factory.audio_intent.status = "not_required";
		input.metadata.campaign_factory.handoff_manifest = {
			...input.metadata.campaign_factory.handoff_manifest,
			manifest_version: 2,
			content_surface: "feed_single",
			contentSurface: "feed_single",
			ig_media_type: "IMAGE",
			igMediaType: "IMAGE",
			mediaItems: [{ type: "image", url: "https://example.com/feed.png" }],
			audio_id: "not_required",
		};

		const result = await runPublishPreflight(input, { account });

		expect(result.issues.some((issue) => issue.code === "campaign_factory_handoff_manifest_invalid")).toBe(false);
	});

	it("blocks Campaign Factory drafts without a valid handoff manifest", async () => {
		const input = inputWithAudioStatus("attached");
		delete input.metadata.campaign_factory.handoff_manifest;

		const result = await runPublishPreflight(input, { account });

		expect(result.ok).toBe(false);
		expect(result.issues.some((issue) => issue.code === "campaign_factory_handoff_manifest_invalid")).toBe(true);
	});

	it("blocks approved-only Campaign Factory assets before scheduling or publishing", async () => {
		const input = inputWithAudioStatus("attached");
		input.metadata.campaign_factory.asset_state = "approved_but_not_publishable";
		input.metadata.campaign_factory.publishability_failure_reasons = ["missing_burned_captions"];

		const result = await runPublishPreflight(input, { account });

		expect(result.ok).toBe(false);
		expect(result.issues.some((issue) => issue.code === "campaign_factory_not_exportable")).toBe(true);
		expect(result.issues.some((issue) => issue.code === "campaign_factory_publishability_failure")).toBe(true);
	});

	it("blocks quarantined Campaign Factory assets before scheduling or publishing", async () => {
		const input = inputWithAudioStatus("attached");
		input.metadata.campaign_factory.quarantined = true;

		const result = await runPublishPreflight(input, { account });

		expect(result.ok).toBe(false);
		expect(result.issues.some((issue) => issue.code === "campaign_factory_asset_quarantined")).toBe(true);
	});

	it("blocks unresolved Campaign Factory native audio", async () => {
		const result = await runPublishPreflight(inputWithAudioStatus("recommended"), { account });

		expect(result.ok).toBe(false);
		expect(result.issues.some((issue) => issue.code === "native_audio_unresolved")).toBe(true);
	});

	it("does not treat audioName as native audio verification", async () => {
		const result = await runPublishPreflight(inputWithAudioStatus("selected", "Renamed audio"), { account });

		expect(result.ok).toBe(false);
		expect(result.issues.some((issue) => issue.code === "native_audio_unresolved")).toBe(true);
		expect(result.issues.some((issue) => issue.code === "audio_name_not_native_verification")).toBe(true);
	});

	it("allows safe native audio statuses", async () => {
		for (const status of ["attached", "verified", "skipped", "not_required"]) {
			const result = await runPublishPreflight(inputWithAudioStatus(status), { account });

			expect(result.ok).toBe(true);
		}
	});

	it("blocks blank Campaign Factory Instagram post captions by default", async () => {
		const input = inputWithAudioStatus("attached");
		input.content = "";
		input.metadata.campaign_factory.instagram_post_caption = "";
		input.metadata.campaign_factory.instagram_post_caption_hash = undefined;
		input.metadata.campaign_factory.handoff_manifest.instagram_post_caption = "";
		input.metadata.campaign_factory.handoff_manifest.instagram_post_caption_hash = undefined;

		const result = await runPublishPreflight(input, { account });

		expect(result.ok).toBe(false);
		expect(result.issues.some((issue) => issue.code === "campaign_factory_instagram_post_caption_missing")).toBe(true);
	});

	it("allows burned captions and Instagram post captions to differ", async () => {
		const input = inputWithAudioStatus("attached");
		input.content = "new post is up";
		input.metadata.campaign_factory.instagram_post_caption = "new post is up";
		input.metadata.campaign_factory.captionOutcomeContext.caption_text = "burned into video";
		input.metadata.campaign_factory.handoff_manifest.instagram_post_caption = "new post is up";
		input.metadata.campaign_factory.handoff_manifest.captionOutcomeContext.caption_text = "burned into video";

		const result = await runPublishPreflight(input, { account });

		expect(result.ok).toBe(true);
	});

	it("keeps legacy non-Campaign Instagram posts with content safe", async () => {
		const result = await runPublishPreflight(
			{
				platform: "instagram",
				instagramAccountId: "ig_1",
				content: "legacy caption",
				igMediaType: "REELS",
				media,
			},
			{ account },
		);

		expect(result.ok).toBe(true);
	});

	it("does not treat attached or verified status as enough without native audio proof", async () => {
		for (const status of ["attached", "verified"]) {
			const input = inputWithAudioStatus(status);
			const audioIntent = input.metadata.campaign_factory.audio_intent as Record<string, unknown>;
			delete audioIntent.operator_selection;

			const result = await runPublishPreflight(input, { account });

			expect(result.ok).toBe(false);
			expect(result.issues.some((issue) => issue.code === "native_audio_proof_missing")).toBe(true);
		}
	});

	it("does not treat burned metadata as native audio verification", async () => {
		const result = await runPublishPreflight(inputWithAudioStatus("burned"), { account });

		expect(result.ok).toBe(false);
		expect(result.issues.some((issue) => issue.code === "native_audio_unresolved")).toBe(true);
	});

	it("blocks Campaign internal trial reels from becoming Instagram Trial Reels without explicit opt-in", async () => {
		const input = inputWithAudioStatus("attached");
		input.trialReels = true;
		input.metadata.campaign_factory.distribution_surface = "trial_reel";
		input.metadata.campaign_factory.trial_reel = true;

		const result = await runPublishPreflight(input, { account });

		expect(result.ok).toBe(false);
		expect(result.issues.some((issue) => issue.code === "campaign_internal_trial_reel_not_instagram_trial")).toBe(true);
	});

	it("allows Campaign Instagram Trial Reels when Campaign Factory explicitly opts in", async () => {
		const input = inputWithAudioStatus("attached");
		input.trialReels = true;
		input.metadata.campaign_factory.distribution_surface = "trial_reel";
		input.metadata.campaign_factory.trial_reel = true;
		input.metadata.campaign_factory.instagram_trial_reels = true;
		input.metadata.campaign_factory.trial_graduation_strategy = "MANUAL";
		input.metadata.campaign_factory.content_surface = "reel";
		input.metadata.campaign_factory.ig_media_type = "REELS";
		input.trialGraduationStrategy = "MANUAL";

		const result = await runPublishPreflight(input, { account });

		expect(result.ok).toBe(true);
	});

	it("blocks explicit Trial Reels on accounts below the platform eligibility floor", async () => {
		const input = inputWithAudioStatus("attached");
		input.trialReels = true;
		input.metadata.campaign_factory.distribution_surface = "trial_reel";
		input.metadata.campaign_factory.trial_reel = true;
		input.metadata.campaign_factory.instagram_trial_reels = true;
		input.metadata.campaign_factory.trial_graduation_strategy = "MANUAL";
		input.metadata.campaign_factory.content_surface = "reel";
		input.metadata.campaign_factory.ig_media_type = "REELS";
		input.trialGraduationStrategy = "MANUAL";

		const result = await runPublishPreflight(input, {
			account: { ...account, followerCount: 45 },
		});

		expect(result.ok).toBe(false);
		expect(result.issues.some((issue) => issue.code === "ig_trial_reel_account_not_eligible")).toBe(true);
	});

	it("blocks explicit Trial Reels without a valid graduation strategy", async () => {
		const input = inputWithAudioStatus("attached");
		input.trialReels = true;
		input.metadata.campaign_factory.distribution_surface = "trial_reel";
		input.metadata.campaign_factory.instagram_trial_reels = true;
		input.metadata.campaign_factory.content_surface = "reel";
		input.metadata.campaign_factory.ig_media_type = "REELS";

		const result = await runPublishPreflight(input, { account });

		expect(result.ok).toBe(false);
		expect(result.issues.some((issue) => issue.code === "ig_trial_reel_graduation_strategy_missing_or_invalid")).toBe(true);
	});

	it("blocks explicit Trial Reels on non-Reel Campaign surfaces", async () => {
		const input = inputWithAudioStatus("attached");
		input.trialReels = true;
		input.igMediaType = "STORIES";
		input.metadata.campaign_factory.instagram_trial_reels = true;
		input.metadata.campaign_factory.trial_graduation_strategy = "MANUAL";
		input.metadata.campaign_factory.content_surface = "story";
		input.metadata.campaign_factory.ig_media_type = "STORIES";
		input.trialGraduationStrategy = "MANUAL";

		const result = await runPublishPreflight(input, { account });

		expect(result.ok).toBe(false);
		expect(result.issues.map((issue) => issue.code)).toEqual(expect.arrayContaining([
			"ig_trial_reel_type",
			"ig_trial_reel_surface_mismatch",
			"ig_trial_reel_manifest_media_type_mismatch",
		]));
	});
});
