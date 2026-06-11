// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";

const db = () => getSupabaseAny();

export const THREADS_GLOBAL_PRIMARY_HOURS = [6, 7, 11, 12, 13] as const;
export const THREADS_GLOBAL_SECONDARY_HOURS = [20, 23] as const;

const LOOKBACK_DAYS = 60;
const HALF_LIFE_DAYS = 14;
const MIN_ACCOUNT_SAMPLE = 12;
const MIN_HOUR_SAMPLE = 3;
const PRIOR_STRENGTH = 5;

export type TimingReason =
	| "account_proven_hour"
	| "account_exploration_hour"
	| "global_fallback_hour"
	| "random_human_hour"
	| "warmup_primary_hour";

export interface PerformanceFactForTiming {
	workspace_id?: string | null | undefined;
	group_id?: string | null | undefined;
	account_id: string | null;
	creator_key?: string | null | undefined;
	posting_hour: number | null;
	published_at: string | null;
	views_24h?: number | null | undefined;
	current_views?: number | null | undefined;
	replies_24h?: number | null | undefined;
	current_replies?: number | null | undefined;
	profile_clicks_proxy?: number | null | undefined;
}

export interface HourPerformanceBucket {
	workspace_id: string;
	group_id: string | null;
	account_id: string;
	platform: "threads";
	hour: number;
	posts_count: number;
	effective_sample_size: number;
	avg_views_24h: number;
	median_views_24h: number;
	above_100_rate: number;
	avg_replies_24h: number;
	profile_clicks_proxy: number;
	weighted_score: number;
	confidence: number;
	fallback_source: "account_learned" | "account_sparse";
	last_seen_at: string | null;
}

export interface AccountTimingHour {
	hour: number;
	postsCount: number;
	effectiveSampleSize: number;
	avgViews24h: number;
	medianViews24h: number;
	above100Rate: number;
	avgReplies24h: number;
	profileClicksProxy: number;
	weightedScore: number;
	confidence: number;
	fallbackSource: string;
	lastSeenAt: string | null;
}

export interface AccountTimingProfile {
	accountId: string;
	provenHours: AccountTimingHour[];
	explorationHours: AccountTimingHour[];
	allHours: AccountTimingHour[];
	confidence: number;
	sampleSize: number;
	fallbackSource: "account_learned" | "account_sparse" | "global_fallback";
}

function finiteNumber(value: unknown, fallback = 0): number {
	const number = typeof value === "number" ? value : Number(value);
	return Number.isFinite(number) ? number : fallback;
}

function daysBetween(later: Date, earlier: Date): number {
	return Math.max(0, (later.getTime() - earlier.getTime()) / 86_400_000);
}

function median(values: number[]): number {
	if (values.length === 0) return 0;
	const sorted = [...values].sort((a, b) => a - b);
	const mid = Math.floor(sorted.length / 2);
	return sorted.length % 2 === 0
		? (sorted[mid - 1]! + sorted[mid]!) / 2
		: sorted[mid]!;
}

function percentile(values: number[], p: number): number {
	if (values.length === 0) return 0;
	const sorted = [...values].sort((a, b) => a - b);
	const idx = Math.min(
		sorted.length - 1,
		Math.max(0, Math.ceil((p / 100) * sorted.length) - 1),
	);
	return sorted[idx]!;
}

function round(value: number, digits = 2): number {
	const factor = 10 ** digits;
	return Math.round(value * factor) / factor;
}

function compositeScore(input: {
	medianViews: number;
	avgCappedViews: number;
	above100Rate: number;
	avgReplies: number;
	profileClicks: number;
}): number {
	return (
		input.medianViews * 0.42 +
		input.avgCappedViews * 0.28 +
		input.above100Rate * 100 * 0.18 +
		input.avgReplies * 2 * 0.08 +
		input.profileClicks * 5 * 0.04
	);
}

export function buildAccountHourPerformanceBuckets(input: {
	workspaceId: string;
	groupId?: string | null | undefined;
	facts: PerformanceFactForTiming[];
	now?: Date | undefined;
}): HourPerformanceBucket[] {
	const now = input.now ?? new Date();
	const byAccount = new Map<string, PerformanceFactForTiming[]>();
	for (const fact of input.facts) {
		if (!fact.account_id || !Number.isInteger(fact.posting_hour)) continue;
		const hour = Number(fact.posting_hour);
		if (hour < 0 || hour > 23) continue;
		if (!fact.published_at) continue;
		const publishedAt = new Date(fact.published_at);
		if (!Number.isFinite(publishedAt.getTime())) continue;
		if (daysBetween(now, publishedAt) > LOOKBACK_DAYS) continue;
		const list = byAccount.get(fact.account_id) ?? [];
		list.push(fact);
		byAccount.set(fact.account_id, list);
	}

	const buckets: HourPerformanceBucket[] = [];
	for (const [accountId, accountFacts] of byAccount.entries()) {
		const accountViews = accountFacts.map((fact) =>
			finiteNumber(fact.views_24h ?? fact.current_views, 0),
		);
		const cap = Math.max(100, percentile(accountViews, 90));
		const accountMedian = median(accountViews);
		const accountAvgCapped =
			accountViews.reduce((sum, views) => sum + Math.min(views, cap), 0) /
			Math.max(1, accountViews.length);
		const accountAbove100 =
			accountViews.filter((views) => views >= 100).length /
			Math.max(1, accountViews.length);
		const accountReplies =
			accountFacts.reduce(
				(sum, fact) =>
					sum + finiteNumber(fact.replies_24h ?? fact.current_replies, 0),
				0,
			) / Math.max(1, accountFacts.length);
		const accountClicks =
			accountFacts.reduce(
				(sum, fact) => sum + finiteNumber(fact.profile_clicks_proxy, 0),
				0,
			) / Math.max(1, accountFacts.length);
		const accountBaseline = compositeScore({
			medianViews: accountMedian,
			avgCappedViews: accountAvgCapped,
			above100Rate: accountAbove100,
			avgReplies: accountReplies,
			profileClicks: accountClicks,
		});

		for (let hour = 0; hour < 24; hour++) {
			const hourFacts = accountFacts.filter((fact) => fact.posting_hour === hour);
			if (hourFacts.length === 0) continue;
			let effectiveSample = 0;
			let weightedViews = 0;
			let weightedReplies = 0;
			let weightedClicks = 0;
			let weightedAbove100 = 0;
			let lastSeenAt: string | null = null;
			for (const fact of hourFacts) {
				const publishedAt = new Date(fact.published_at!);
				const ageDays = daysBetween(now, publishedAt);
				const weight = 0.5 ** (ageDays / HALF_LIFE_DAYS);
				const views = finiteNumber(fact.views_24h ?? fact.current_views, 0);
				effectiveSample += weight;
				weightedViews += Math.min(views, cap) * weight;
				weightedReplies +=
					finiteNumber(fact.replies_24h ?? fact.current_replies, 0) * weight;
				weightedClicks += finiteNumber(fact.profile_clicks_proxy, 0) * weight;
				weightedAbove100 += (views >= 100 ? 1 : 0) * weight;
				if (!lastSeenAt || fact.published_at! > lastSeenAt) {
					lastSeenAt = fact.published_at!;
				}
			}
			const rawViews = hourFacts.map((fact) =>
				finiteNumber(fact.views_24h ?? fact.current_views, 0),
			);
			const avgCappedViews = weightedViews / Math.max(0.01, effectiveSample);
			const avgReplies = weightedReplies / Math.max(0.01, effectiveSample);
			const profileClicks = weightedClicks / Math.max(0.01, effectiveSample);
			const above100Rate = weightedAbove100 / Math.max(0.01, effectiveSample);
			const hourComposite = compositeScore({
				medianViews: median(rawViews),
				avgCappedViews,
				above100Rate,
				avgReplies,
				profileClicks,
			});
			const smoothedScore =
				(effectiveSample * hourComposite + PRIOR_STRENGTH * accountBaseline) /
				(effectiveSample + PRIOR_STRENGTH);
			const sampleConfidence = Math.min(1, effectiveSample / 8);
			const accountConfidence =
				accountFacts.length >= MIN_ACCOUNT_SAMPLE ? 1 : 0.45;
			const hourConfidence = hourFacts.length >= MIN_HOUR_SAMPLE ? 1 : 0.55;
			const confidence = sampleConfidence * accountConfidence * hourConfidence;
			buckets.push({
				workspace_id: input.workspaceId,
				group_id: input.groupId ?? accountFacts[0]?.group_id ?? null,
				account_id: accountId,
				platform: "threads",
				hour,
				posts_count: hourFacts.length,
				effective_sample_size: round(effectiveSample),
				avg_views_24h: round(
					rawViews.reduce((sum, views) => sum + views, 0) /
						Math.max(1, rawViews.length),
				),
				median_views_24h: round(median(rawViews)),
				above_100_rate: round(above100Rate, 4),
				avg_replies_24h: round(avgReplies),
				profile_clicks_proxy: round(profileClicks),
				weighted_score: round(smoothedScore),
				confidence: round(confidence, 4),
				fallback_source:
					accountFacts.length >= MIN_ACCOUNT_SAMPLE && hourFacts.length >= MIN_HOUR_SAMPLE
						? "account_learned"
						: "account_sparse",
				last_seen_at: lastSeenAt,
			});
		}
	}
	return buckets;
}

function toTimingHour(row: Record<string, unknown>): AccountTimingHour {
	return {
		hour: finiteNumber(row.hour),
		postsCount: finiteNumber(row.posts_count),
		effectiveSampleSize: finiteNumber(row.effective_sample_size),
		avgViews24h: finiteNumber(row.avg_views_24h),
		medianViews24h: finiteNumber(row.median_views_24h),
		above100Rate: finiteNumber(row.above_100_rate),
		avgReplies24h: finiteNumber(row.avg_replies_24h),
		profileClicksProxy: finiteNumber(row.profile_clicks_proxy),
		weightedScore: finiteNumber(row.weighted_score),
		confidence: finiteNumber(row.confidence),
		fallbackSource: String(row.fallback_source ?? "account_sparse"),
		lastSeenAt: typeof row.last_seen_at === "string" ? row.last_seen_at : null,
	};
}

export async function rebuildAccountHourPerformanceBuckets(input: {
	workspaceId: string;
	groupId?: string | undefined;
	accountIds: string[];
	now?: Date | undefined;
}): Promise<{ upserted: number; accounts: number }> {
	const accountIds = [...new Set(input.accountIds)].filter(Boolean);
	if (accountIds.length === 0) return { upserted: 0, accounts: 0 };
	const since = new Date(
		(input.now ?? new Date()).getTime() - LOOKBACK_DAYS * 86_400_000,
	).toISOString();
	try {
		let query = db()
			.from("autoposter_post_performance_facts")
			.select(
				"workspace_id, group_id, account_id, creator_key, posting_hour, published_at, views_24h, current_views, replies_24h, current_replies, profile_clicks_proxy",
			)
			.eq("workspace_id", input.workspaceId)
			.eq("platform", "threads")
			.in("account_id", accountIds)
			.gte("published_at", since)
			.limit(5000);
		if (input.groupId) query = query.eq("group_id", input.groupId);
		const { data, error } = await query;
		if (error) throw error;
		const buckets = buildAccountHourPerformanceBuckets({
			workspaceId: input.workspaceId,
			groupId: input.groupId,
			facts: (data ?? []) as PerformanceFactForTiming[],
			now: input.now,
		});
		if (buckets.length > 0) {
			const { error: upsertError } = await db()
				.from("autoposter_account_hour_performance")
				.upsert(
					buckets.map((bucket) => ({
						...bucket,
						computed_at: new Date().toISOString(),
					})),
					{ onConflict: "workspace_id,account_id,platform,hour" },
				);
			if (upsertError) throw upsertError;
		}
		return { upserted: buckets.length, accounts: accountIds.length };
	} catch (error) {
		logger.warn("[accountTimingPerformance] Failed to rebuild hour buckets", {
			workspaceId: input.workspaceId,
			groupId: input.groupId,
			error: error instanceof Error ? error.message : String(error),
		});
		return { upserted: 0, accounts: accountIds.length };
	}
}

export async function loadAccountTimingProfiles(input: {
	workspaceId: string;
	groupId?: string | undefined;
	accountIds: string[];
}): Promise<Map<string, AccountTimingProfile>> {
	const accountIds = [...new Set(input.accountIds)].filter(Boolean);
	const profiles = new Map<string, AccountTimingProfile>();
	if (accountIds.length === 0) return profiles;
	try {
		let query = db()
			.from("autoposter_account_hour_performance")
			.select(
				"account_id, hour, posts_count, effective_sample_size, avg_views_24h, median_views_24h, above_100_rate, avg_replies_24h, profile_clicks_proxy, weighted_score, confidence, fallback_source, last_seen_at",
			)
			.eq("workspace_id", input.workspaceId)
			.eq("platform", "threads")
			.in("account_id", accountIds)
			.order("weighted_score", { ascending: false });
		if (input.groupId) query = query.eq("group_id", input.groupId);
		const { data, error } = await query;
		if (error) throw error;
		const byAccount = new Map<string, AccountTimingHour[]>();
		for (const row of (data ?? []) as Array<Record<string, unknown>>) {
			const accountId = String(row.account_id ?? "");
			if (!accountId) continue;
			const list = byAccount.get(accountId) ?? [];
			list.push(toTimingHour(row));
			byAccount.set(accountId, list);
		}
		for (const accountId of accountIds) {
			const hours = (byAccount.get(accountId) ?? []).sort(
				(a, b) => b.weightedScore - a.weightedScore,
			);
			const sampleSize = hours.reduce((sum, hour) => sum + hour.postsCount, 0);
			const confidence = hours.reduce(
				(max, hour) => Math.max(max, hour.confidence),
				0,
			);
			const provenHours = hours.filter(
				(hour) =>
					hour.fallbackSource === "account_learned" &&
					hour.postsCount >= MIN_HOUR_SAMPLE &&
					hour.confidence >= 0.45,
			);
			const provenSet = new Set(provenHours.map((hour) => hour.hour));
			const explorationHours = hours.filter((hour) => !provenSet.has(hour.hour));
			profiles.set(accountId, {
				accountId,
				provenHours,
				explorationHours,
				allHours: hours,
				confidence,
				sampleSize,
				fallbackSource:
					provenHours.length > 0 && sampleSize >= MIN_ACCOUNT_SAMPLE
						? "account_learned"
						: sampleSize > 0
							? "account_sparse"
							: "global_fallback",
			});
		}
	} catch (error) {
		logger.warn("[accountTimingPerformance] Failed to load timing profiles", {
			workspaceId: input.workspaceId,
			groupId: input.groupId,
			error: error instanceof Error ? error.message : String(error),
		});
		for (const accountId of accountIds) {
			profiles.set(accountId, {
				accountId,
				provenHours: [],
				explorationHours: [],
				allHours: [],
				confidence: 0,
				sampleSize: 0,
				fallbackSource: "global_fallback",
			});
		}
	}
	return profiles;
}
