export type AutoposterHealthTier =
	| "normal"
	| "deprioritized"
	| "warming"
	| "suppressed";

export interface AutoposterHealthSignals {
	oauthFailures?: number | null | undefined;
	transientPublishFailures?: number | null | undefined;
	deadLetters?: number | null | undefined;
	quotaWarnings?: number | null | undefined;
	isShadowbanned?: boolean | null | undefined;
	isSuppressed?: boolean | null | undefined;
	duplicateBlocks?: number | null | undefined;
	recentPublishSuccesses?: number | null | undefined;
	engagementFetchSuccesses?: number | null | undefined;
}

export interface AutoposterHealthResult {
	score: number;
	reason: string;
	tier: AutoposterHealthTier;
}

export interface PublishAttemptHealthClassificationInput {
	result?: string | null | undefined;
	errorCode?: string | null | undefined;
	errorMessage?: string | null | undefined;
}

function boundedCount(value: number | null | undefined): number {
	if (!Number.isFinite(value ?? 0)) return 0;
	return Math.max(0, Math.floor(value ?? 0));
}

function clampScore(value: number): number {
	return Math.max(0, Math.min(100, Math.round(value)));
}

function isActiveWindowRequeue(
	input: PublishAttemptHealthClassificationInput,
): boolean {
	const result = (input.result ?? "").toLowerCase();
	const errorText =
		`${input.errorCode ?? ""} ${input.errorMessage ?? ""}`.toLowerCase();
	return (
		result === "requeued" &&
		(errorText.includes("outside_active_window") ||
			errorText.includes("active-window") ||
			errorText.includes("active window") ||
			errorText.includes("outside account window") ||
			errorText.includes("no fallback account satisfied active-window"))
	);
}

function isCapacityControlRequeue(
	input: PublishAttemptHealthClassificationInput,
): boolean {
	const result = (input.result ?? "").toLowerCase();
	const errorText =
		`${input.errorCode ?? ""} ${input.errorMessage ?? ""}`.toLowerCase();
	return (
		result === "requeued" &&
		(errorText.includes("cap_exceeded") ||
			errorText.includes("cap_zero") ||
			errorText.includes("daily_cap") ||
			errorText.includes("warmup_cap") ||
			errorText.includes("held_cap") ||
			errorText.includes("performance_recommended_cap") ||
			errorText.includes("reduced_cap") ||
			errorText.includes("stale_warmup_cap"))
	);
}

function isSystemClaimFailure(
	input: PublishAttemptHealthClassificationInput,
): boolean {
	return (input.result ?? "").toLowerCase() === "claim_failed";
}

function isMetaTransientUnknownError(
	input: PublishAttemptHealthClassificationInput,
): boolean {
	const errorText =
		`${input.errorCode ?? ""} ${input.errorMessage ?? ""}`.toLowerCase();
	return (
		errorText.includes("retryable_publish_failure") &&
		errorText.includes("code=1") &&
		errorText.includes("oauthexception") &&
		errorText.includes("unknown error")
	);
}

export function isPublishAttemptFailureForAccountHealth(
	input: PublishAttemptHealthClassificationInput,
): boolean {
	const result = (input.result ?? "").toLowerCase();
	if (isActiveWindowRequeue(input)) return false;
	if (isCapacityControlRequeue(input)) return false;
	if (isSystemClaimFailure(input)) return false;
	if (isMetaTransientUnknownError(input)) return false;
	return (
		result === "requeued" ||
		result === "failed" ||
		result === "error"
	);
}

export function isPublishAttemptHealthRelevantFailure(
	input: PublishAttemptHealthClassificationInput,
): boolean {
	const result = (input.result ?? "").toLowerCase();
	if (isPublishAttemptFailureForAccountHealth(input)) return true;
	return (
		result === "dead_letter" || result === "duplicate_fingerprint_blocked"
	);
}

export function classifyAutoposterHealthScore(
	score: number | null | undefined,
): AutoposterHealthTier {
	const safeScore = typeof score === "number" ? score : 100;
	if (safeScore >= 80) return "normal";
	if (safeScore >= 60) return "deprioritized";
	if (safeScore >= 40) return "warming";
	return "suppressed";
}

export function calculateAutoposterAccountHealth(
	signals: AutoposterHealthSignals,
): AutoposterHealthResult {
	const oauthFailures = boundedCount(signals.oauthFailures);
	const transientFailures = boundedCount(signals.transientPublishFailures);
	const deadLetters = boundedCount(signals.deadLetters);
	const quotaWarnings = boundedCount(signals.quotaWarnings);
	const duplicateBlocks = boundedCount(signals.duplicateBlocks);
	const publishSuccesses = boundedCount(signals.recentPublishSuccesses);
	const engagementSuccesses = boundedCount(signals.engagementFetchSuccesses);

	const penalties = [
		oauthFailures * 30,
		transientFailures * 8,
		deadLetters * 18,
		quotaWarnings * 10,
		duplicateBlocks * 12,
		signals.isShadowbanned ? 30 : 0,
		signals.isSuppressed ? 35 : 0,
	];
	const rewards = [
		Math.min(12, publishSuccesses * 2),
		Math.min(8, engagementSuccesses),
	];
	const score = clampScore(
		100 -
			penalties.reduce((sum, value) => sum + value, 0) +
			rewards.reduce((sum, value) => sum + value, 0),
	);

	const reasons: string[] = [];
	if (oauthFailures > 0) reasons.push(`oauth_failures:${oauthFailures}`);
	if (transientFailures > 0) {
		reasons.push(`transient_publish_failures:${transientFailures}`);
	}
	if (deadLetters > 0) reasons.push(`dead_letters:${deadLetters}`);
	if (quotaWarnings > 0) reasons.push(`quota_warnings:${quotaWarnings}`);
	if (duplicateBlocks > 0) reasons.push(`duplicate_blocks:${duplicateBlocks}`);
	if (signals.isShadowbanned || signals.isSuppressed) {
		reasons.push("shadowban_or_suppression");
	}
	if (publishSuccesses > 0) {
		reasons.push(`recent_publish_success:${publishSuccesses}`);
	}
	if (engagementSuccesses > 0) {
		reasons.push(`engagement_fetch_success:${engagementSuccesses}`);
	}

	return {
		score,
		reason: reasons.length > 0 ? reasons.join(";") : "no_recent_signals",
		tier: classifyAutoposterHealthScore(score),
	};
}

export function autoposterHealthSortValue(
	score: number | null | undefined,
): number {
	return typeof score === "number" ? score : 100;
}

export function isAutoposterHealthSuppressed(
	score: number | null | undefined,
): boolean {
	return classifyAutoposterHealthScore(score) === "suppressed";
}
