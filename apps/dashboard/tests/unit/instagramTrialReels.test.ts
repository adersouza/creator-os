import { describe, expect, it } from "vitest";
import {
	hasInternalTrialLanguage,
	resolveInstagramTrialReelIntent,
} from "../../api/_lib/instagramTrialReels.js";
import { instagramTrialParams } from "../../api/_lib/instagram/publishing.js";

describe("Instagram Trial Reels explicit contract", () => {
	it("does not infer Instagram Trial Reels from internal trial distribution labels", () => {
		const metadata = {
			campaign_factory: {
				distribution_surface: "trial_reel",
				campaign_slug: "stacey_trial_batch",
			},
		};

		expect(hasInternalTrialLanguage({ metadata })).toBe(true);
		expect(resolveInstagramTrialReelIntent({ metadata })).toEqual({
			enabled: false,
			strategy: undefined,
			explicit: false,
		});
	});

	it("enables Trial Reels only with an explicit flag and valid strategy", () => {
		const metadata = {
			campaign_factory: {
				distribution_surface: "trial_reel",
				instagram_trial_reels: true,
				trial_graduation_strategy: "SS_PERFORMANCE",
			},
		};

		expect(resolveInstagramTrialReelIntent({ metadata })).toEqual({
			enabled: true,
			strategy: "SS_PERFORMANCE",
			explicit: true,
		});
	});

	it("does not build Meta trial_params for normal Reels", () => {
		expect(
			instagramTrialParams({
				mediaType: "REELS",
				trialReels: false,
				trialGraduationStrategy: "MANUAL",
			}),
		).toBeUndefined();
	});

	it("does not build Meta trial_params for non-Reel surfaces", () => {
		expect(
			instagramTrialParams({
				mediaType: "STORIES",
				trialReels: true,
				trialGraduationStrategy: "MANUAL",
			}),
		).toBeUndefined();
	});

	it("builds the exact Meta trial_params payload for explicit Trial Reels", () => {
		expect(
			instagramTrialParams({
				mediaType: "REELS",
				trialReels: true,
				trialGraduationStrategy: "MANUAL",
			}),
		).toEqual({ graduation_strategy: "MANUAL" });
	});
});
