export type TrialGraduationStrategy = "MANUAL" | "SS_PERFORMANCE";

export interface InstagramTrialReelIntent {
	enabled: boolean;
	strategy?: TrialGraduationStrategy | undefined;
	explicit: boolean;
}

const VALID_TRIAL_GRADUATION_STRATEGIES = new Set([
	"MANUAL",
	"SS_PERFORMANCE",
]);

function recordValue(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function boolValue(value: unknown): boolean | null {
	return typeof value === "boolean" ? value : null;
}

function stringValue(value: unknown): string | null {
	return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizeStrategy(value: unknown): TrialGraduationStrategy | undefined {
	const raw = stringValue(value)?.toUpperCase();
	return raw && VALID_TRIAL_GRADUATION_STRATEGIES.has(raw)
		? (raw as TrialGraduationStrategy)
		: undefined;
}

export function campaignFactoryFromMetadata(
	metadata: Record<string, unknown> | null | undefined,
): Record<string, unknown> | null {
	const campaignFactory = recordValue(metadata?.campaign_factory);
	return campaignFactory;
}

export function resolveInstagramTrialReelIntent(input: {
	metadata?: Record<string, unknown> | null | undefined;
	campaignFactory?: Record<string, unknown> | null | undefined;
	instagramTrialReels?: boolean | undefined;
	instagram_trial_reels?: boolean | undefined;
	trialGraduationStrategy?: string | undefined;
}): InstagramTrialReelIntent {
	const campaignFactory =
		recordValue(input.campaignFactory) ||
		campaignFactoryFromMetadata(input.metadata) ||
		{};
	const manifest = recordValue(campaignFactory.handoff_manifest) || {};
	const explicitFlag =
		boolValue(input.instagramTrialReels) ??
		boolValue(input.instagram_trial_reels) ??
		boolValue(campaignFactory.instagram_trial_reels) ??
		boolValue(campaignFactory.instagramTrialReels) ??
		boolValue(manifest.instagram_trial_reels) ??
		boolValue(manifest.instagramTrialReels);
	const strategy =
		normalizeStrategy(input.trialGraduationStrategy) ||
		normalizeStrategy(campaignFactory.trial_graduation_strategy) ||
		normalizeStrategy(campaignFactory.trialGraduationStrategy) ||
		normalizeStrategy(manifest.trial_graduation_strategy) ||
		normalizeStrategy(manifest.trialGraduationStrategy);

	return {
		enabled: explicitFlag === true,
		strategy,
		explicit: explicitFlag !== null,
	};
}

export function hasInternalTrialLanguage(input: {
	metadata?: Record<string, unknown> | null | undefined;
	campaignFactory?: Record<string, unknown> | null | undefined;
}): boolean {
	const campaignFactory =
		recordValue(input.campaignFactory) ||
		campaignFactoryFromMetadata(input.metadata) ||
		{};
	const haystack = [
		campaignFactory.distribution_surface,
		campaignFactory.distributionSurface,
		campaignFactory.campaign,
		campaignFactory.campaign_slug,
		campaignFactory.campaignSlug,
		campaignFactory.proof_run_id,
		campaignFactory.proofRunId,
		campaignFactory.run_type,
		campaignFactory.runType,
		campaignFactory.trial_reel === true ? "trial_reel" : null,
		campaignFactory.trialReel === true ? "trial_reel" : null,
	]
		.map((value) => String(value || "").toLowerCase())
		.join(" ");
	return /\b(trial|proof|test)\b/.test(haystack) || haystack.includes("trial_reel");
}
