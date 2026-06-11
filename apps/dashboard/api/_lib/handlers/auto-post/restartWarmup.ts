export type RestartWarmupStatus =
	| "none"
	| "warming"
	| "held"
	| "completed"
	| "suppressed";

export interface RestartWarmupState {
	restart_warmup_status?: RestartWarmupStatus | null | undefined;
	restart_warmup_started_at?: string | null | undefined;
	restart_warmup_day?: number | null | undefined;
	restart_warmup_allowed_posts_per_day?: number | null | undefined;
	restart_warmup_reason?: string | null | undefined;
	restart_warmup_next_ramp_at?: string | null | undefined;
	restart_warmup_last_post_views?: number | null | undefined;
	restart_warmup_last_evaluated_at?: string | null | undefined;
}

export interface RestartWarmupPolicy {
	status: RestartWarmupStatus;
	day: number;
	allowedPostsPerDay: number | null;
	reason: string;
	nextRampAt: string | null;
	lastPostViews: number | null;
	textOnly: boolean;
	mediaChanceCap: number | null;
	primaryHoursOnly: boolean;
	directMicrocopyAllowed: boolean;
	directMicrocopyCapPercent: number;
	genericQuestionCap: number;
	shouldSkipToday: boolean;
}

export interface RestartWarmupEvaluationInput {
	now: Date;
	previous?: RestartWarmupState | null | undefined;
	accountId: string;
	healthScore?: number | null | undefined;
	lastAutoposterPublishedAt?: string | null | undefined;
	recentWarmupViews?: number[] | null | undefined;
	isSuppressed?: boolean | null | undefined;
	isProbeMode?: boolean | null | undefined;
	isThreads?: boolean | null | undefined;
}

export interface RestartWarmupEvaluation extends RestartWarmupPolicy {
	startedAt: string | null;
	lastEvaluatedAt: string;
}

const INACTIVITY_MS = 48 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;
const WINNER_VIEWS = 100;
const DECENT_AVG_VIEWS = 20;
const DECENT_SINGLE_POST_VIEWS = 50;
const NEAR_ZERO_AVG_VIEWS = 5;

function hashString(value: string): number {
	let hash = 0;
	for (let i = 0; i < value.length; i++) {
		hash = ((hash << 5) - hash + value.charCodeAt(i)) | 0;
	}
	return Math.abs(hash);
}

function deterministicRange(
	accountId: string,
	day: number,
	min: number,
	max: number,
): number {
	if (min >= max) return max;
	return min + (hashString(`${accountId}:${day}`) % (max - min + 1));
}

function nextUtcDay(value: Date): string {
	return new Date(value.getTime() + DAY_MS).toISOString();
}

function daySince(startedAt: string | null | undefined, now: Date): number {
	if (!startedAt) return 1;
	const started = new Date(startedAt);
	if (Number.isNaN(started.getTime())) return 1;
	return Math.max(1, Math.floor((now.getTime() - started.getTime()) / DAY_MS) + 1);
}

function rampCap(accountId: string, day: number): number {
	if (day <= 1) return 1;
	if (day === 2) return deterministicRange(accountId, day, 1, 2);
	if (day === 3) return 2;
	if (day <= 5) return deterministicRange(accountId, day, 2, 3);
	return 3;
}

function average(values: number[]): number | null {
	if (values.length === 0) return null;
	return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function inactiveLongEnough(
	lastAutoposterPublishedAt: string | null | undefined,
	now: Date,
): boolean {
	if (!lastAutoposterPublishedAt) return true;
	const publishedAt = new Date(lastAutoposterPublishedAt).getTime();
	if (Number.isNaN(publishedAt)) return true;
	return now.getTime() - publishedAt >= INACTIVITY_MS;
}

export function evaluateRestartWarmup(
	input: RestartWarmupEvaluationInput,
): RestartWarmupEvaluation {
	const nowIso = input.now.toISOString();
	const previousStatus = input.previous?.restart_warmup_status ?? "none";
	const previousStartedAt = input.previous?.restart_warmup_started_at ?? null;
	const wasActive =
		previousStatus === "warming" ||
		previousStatus === "held" ||
		previousStatus === "suppressed";
	const shouldEnter =
		input.isThreads !== false &&
		(wasActive || inactiveLongEnough(input.lastAutoposterPublishedAt, input.now));
	const recentViews = (input.recentWarmupViews ?? [])
		.map((value) => Math.max(0, Number(value) || 0))
		.slice(0, 3);
	const lastPostViews =
		recentViews[0] ?? input.previous?.restart_warmup_last_post_views ?? null;
	const avgRecent = average(recentViews);
	const maxRecent = recentViews.length > 0 ? Math.max(...recentViews) : null;
	const healthScore = input.healthScore ?? 100;

	if (!shouldEnter) {
		return {
			status: previousStatus === "completed" ? "completed" : "none",
			startedAt: previousStatus === "completed" ? previousStartedAt : null,
			day: 0,
			allowedPostsPerDay: null,
			reason:
				previousStatus === "completed"
					? "restart_warmup_completed"
					: "recent_autoposter_activity",
			nextRampAt: null,
			lastPostViews,
			textOnly: false,
			mediaChanceCap: null,
			primaryHoursOnly: false,
			directMicrocopyAllowed: true,
			directMicrocopyCapPercent: 10,
			genericQuestionCap: 2,
			shouldSkipToday: false,
			lastEvaluatedAt: nowIso,
		};
	}

	const startedAt = wasActive && previousStartedAt ? previousStartedAt : nowIso;
	const day = daySince(startedAt, input.now);
	const baseCap = rampCap(input.accountId, day);
	const hasWinner = (maxRecent ?? 0) >= WINNER_VIEWS;
	const hasDecentViews =
		(avgRecent ?? 0) >= DECENT_AVG_VIEWS ||
		(maxRecent ?? 0) >= DECENT_SINGLE_POST_VIEWS;
	const nearZero = recentViews.length >= 3 && (avgRecent ?? 0) < NEAR_ZERO_AVG_VIEWS;

	let status: RestartWarmupStatus = "warming";
	let allowedPostsPerDay: number | null = baseCap;
	let reason = `restart_warmup_day_${day}`;
	let nextRampAt: string | null = nextUtcDay(input.now);
	let shouldSkipToday = false;

	if (input.isProbeMode) {
		status = "warming";
		allowedPostsPerDay = 1;
		reason = "suppressed_probe_active";
		nextRampAt = nextUtcDay(input.now);
	} else if (input.isSuppressed || healthScore < 40) {
		status = "suppressed";
		allowedPostsPerDay = 0;
		reason = input.isSuppressed
			? "account_suppressed"
			: `health_suppressed:${healthScore}`;
		nextRampAt = null;
		shouldSkipToday = true;
	} else if (healthScore < 60) {
		status = "held";
		allowedPostsPerDay = 1;
		reason = `health_hold:${healthScore}`;
	} else if (nearZero) {
		status = "held";
		allowedPostsPerDay = 1;
		reason = `near_zero_views_avg:${Math.round((avgRecent ?? 0) * 10) / 10}`;
	} else if (day >= 6 && !hasDecentViews && !hasWinner) {
		status = "held";
		allowedPostsPerDay = Math.min(baseCap, 2);
		reason = "waiting_for_decent_views";
	} else if (day > 7 && (hasDecentViews || hasWinner)) {
		status = "completed";
		allowedPostsPerDay = null;
		reason = hasWinner ? "completed_after_winner" : "completed_after_decent_views";
		nextRampAt = null;
	}

	if (hasWinner && status === "warming") {
		allowedPostsPerDay = Math.min(3, Math.max(allowedPostsPerDay ?? 0, baseCap));
		reason = `${reason};winner_unlocked_next_step`;
	}

	const textOnly = day <= 1 || status === "held";
	return {
		status,
		startedAt,
		day,
		allowedPostsPerDay,
		reason,
		nextRampAt,
		lastPostViews,
		textOnly,
		mediaChanceCap: textOnly ? 0 : day <= 7 ? 10 : null,
		primaryHoursOnly: day <= 1 || status === "held",
		directMicrocopyAllowed: day > 1 && status === "warming",
		directMicrocopyCapPercent: day <= 1 || status !== "warming" ? 0 : 5,
		genericQuestionCap: 0,
		shouldSkipToday,
		lastEvaluatedAt: nowIso,
	};
}

export function restartWarmupPolicyFromState(
	state?: RestartWarmupState | null,
): RestartWarmupPolicy | null {
	const status = state?.restart_warmup_status ?? "none";
	if (status === "none" || !status) return null;
	const day = Math.max(0, Math.floor(state?.restart_warmup_day ?? 0));
	const allowedPostsPerDay =
		typeof state?.restart_warmup_allowed_posts_per_day === "number"
			? state.restart_warmup_allowed_posts_per_day
			: null;
	return {
		status,
		day,
		allowedPostsPerDay,
		reason: state?.restart_warmup_reason ?? status,
		nextRampAt: state?.restart_warmup_next_ramp_at ?? null,
		lastPostViews: state?.restart_warmup_last_post_views ?? null,
		textOnly: day <= 1 || status === "held",
		mediaChanceCap: day <= 1 || status === "held" ? 0 : day <= 7 ? 10 : null,
		primaryHoursOnly: day <= 1 || status === "held",
		directMicrocopyAllowed: day > 1 && status === "warming",
		directMicrocopyCapPercent: day <= 1 || status !== "warming" ? 0 : 5,
		genericQuestionCap: 0,
		shouldSkipToday: status === "suppressed",
	};
}
