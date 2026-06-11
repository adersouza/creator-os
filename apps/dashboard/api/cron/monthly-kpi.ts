// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Monthly Retention + CES KPI Cron
 *
 * Runs 1st of every month at 8AM UTC.
 * Computes: "Of users active 90 days ago, what % are still active AND have higher CES?"
 *
 * Uses verifyCronAuth + withCronLock + trackCronRun pattern.
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { AlertLevel, alert, alertCronFailure } from "../_lib/alerting.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { logger } from "../_lib/logger.js";
import { getRedis } from "../_lib/redis.js";
import { getSupabase } from "../_lib/supabase.js";

// Row / API Types
interface ProfileRow {
	user_id: string;
	last_login_at: string | null;
}
interface AccountRow {
	id: string;
	user_id: string;
}
interface PostRow {
	account_id: string;
}
interface PostEngRow {
	likes_count: number | null;
	replies_count: number | null;
	reposts_count: number | null;
	views_count: number | null;
}

const db = () => getSupabase();

interface MonthlyKPIResult {
	yearMonth: string;
	retentionGrowthPct: number;
	active90dAgo: number;
	stillActive: number;
	cesImproved: number;
	churnCount: number;
	avgCesChange: number;
	medianDaysActive: number;
	computedAt: string;
}

function median(arr: number[]): number {
	if (arr.length === 0) return 0;
	const sorted = [...arr].sort((a, b) => a - b);
	const mid = Math.floor(sorted.length / 2);
	return sorted.length % 2 !== 0
		? sorted[mid]!
		: (sorted[mid - 1]! + sorted[mid]!) / 2;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	try {
		const supabase = db();

		const lockResult = await withCronLock(
			supabase as SupabaseClient,
			"monthly-kpi",
			async () => {
				return trackCronRun(
					supabase as SupabaseClient,
					"monthly-kpi",
					async () => {
						const now = new Date();
						const yearMonth = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
						const ninetyDaysAgo = new Date(
							now.getTime() - 90 * 24 * 60 * 60 * 1000,
						);
						const ninetyDaysAgoWeekStart = new Date(
							ninetyDaysAgo.getTime() - 7 * 24 * 60 * 60 * 1000,
						);
						const sevenDaysAgo = new Date(
							now.getTime() - 7 * 24 * 60 * 60 * 1000,
						);

						await assertLastLoginSchema(supabase as SupabaseClient);

						// Step 1: Users who were active 90 days ago (logged in around then + had posts that week)
						const { data: profilesActive90d, error: active90dError } =
							await supabase
								.from("user_preferences")
								.select("user_id, last_login_at")
								.lte("last_login_at", ninetyDaysAgo.toISOString())
								.gte("last_login_at", ninetyDaysAgoWeekStart.toISOString());

						if (active90dError) throw active90dError;

						const candidates = profilesActive90d ?? [];
						if (candidates.length === 0) {
							const kpi: MonthlyKPIResult = {
								yearMonth,
								retentionGrowthPct: 0,
								active90dAgo: 0,
								stillActive: 0,
								cesImproved: 0,
								churnCount: 0,
								avgCesChange: 0,
								medianDaysActive: 0,
								computedAt: now.toISOString(),
							};
							await storeAndReport(kpi);
							return {
								itemsProcessed: 0,
								metadata: kpi as unknown as Record<string, unknown>,
							};
						}

						const candidateIds = (candidates as unknown as Array<{
							user_id: string;
							last_login_at: string | null;
						}>).map(
							(p) => p.user_id,
						);

						// Verify they had posts that week (90 days ago)
						const { data: accountsForCandidates } = await supabase
							.from("accounts")
							.select("id, user_id")
							.in("user_id", candidateIds);

						const accountsByUser = new Map<string, string[]>();
						for (const a of accountsForCandidates ?? []) {
							const arr = accountsByUser.get(a.user_id) || [];
							arr.push(a.id);
							accountsByUser.set(a.user_id, arr);
						}

						const allAccountIds = (accountsForCandidates ?? []).map(
							(a: AccountRow) => a.id,
						);

						const { data: posts90d } = await supabase
							.from("posts")
							.select("account_id")
							.in("account_id", allAccountIds)
							.gte("created_at", ninetyDaysAgoWeekStart.toISOString())
							.lte("created_at", ninetyDaysAgo.toISOString());

						const accountsWithPosts90d = new Set(
							(posts90d ?? []).map((p) => (p as unknown as PostRow).account_id),
						);

						// Filter to users who actually had posts that week
						const activeUsers90d = candidateIds.filter((uid: string) => {
							const accts = accountsByUser.get(uid) || [];
							return accts.some((aid) => accountsWithPosts90d.has(aid));
						});

						if (activeUsers90d.length === 0) {
							const kpi: MonthlyKPIResult = {
								yearMonth,
								retentionGrowthPct: 0,
								active90dAgo: 0,
								stillActive: 0,
								cesImproved: 0,
								churnCount: 0,
								avgCesChange: 0,
								medianDaysActive: 0,
								computedAt: now.toISOString(),
							};
							await storeAndReport(kpi);
							return {
								itemsProcessed: 0,
								metadata: kpi as unknown as Record<string, unknown>,
							};
						}

						// Step 2: Of those, filter to still active this week
						const { data: profilesStillActive, error: stillActiveError } =
							await supabase
								.from("user_preferences")
								.select("user_id, last_login_at")
								.in("user_id", activeUsers90d)
								.gte("last_login_at", sevenDaysAgo.toISOString());

						if (stillActiveError) throw stillActiveError;

						const stillActiveIds = (profilesStillActive ?? []).map(
							(p) => (p as unknown as { user_id: string }).user_id,
						);

						// Check they also posted this week
						const stillActiveAccountIds = stillActiveIds.flatMap(
							(uid: string) => accountsByUser.get(uid) || [],
						);

						const { data: postsThisWeek } = await supabase
							.from("posts")
							.select("account_id")
							.in("account_id", stillActiveAccountIds)
							.gte("created_at", sevenDaysAgo.toISOString());

						const accountsWithPostsNow = new Set(
							(postsThisWeek ?? []).map(
								(p) => (p as unknown as PostRow).account_id,
							),
						);

						const confirmedStillActive = stillActiveIds.filter(
							(uid: string) => {
								const accts = accountsByUser.get(uid) || [];
								return accts.some((aid: string) =>
									accountsWithPostsNow.has(aid),
								);
							},
						);

						// Step 3: Compare CES (Creator Engagement Score) — use engagement rate as proxy
						// CES 90 days ago vs now for still-active users
						let cesImprovedCount = 0;
						let totalCesChange = 0;
						const daysActiveList: number[] = [];

						for (const uid of confirmedStillActive) {
							const accts = accountsByUser.get(uid) || [];
							if (accts.length === 0) continue;

							// CES 90 days ago (avg engagement rate of posts around that time)
							const { data: oldPosts } = await supabase
								.from("posts")
								.select(
									"likes_count, replies_count, reposts_count, views_count",
								)
								.in("account_id", accts)
								.gte("created_at", ninetyDaysAgoWeekStart.toISOString())
								.lte("created_at", ninetyDaysAgo.toISOString());

							// CES now (last 7 days)
							const { data: newPosts } = await supabase
								.from("posts")
								.select(
									"likes_count, replies_count, reposts_count, views_count",
								)
								.in("account_id", accts)
								.gte("created_at", sevenDaysAgo.toISOString());

							const cesOld = computeCES(oldPosts ?? []);
							const cesNew = computeCES(newPosts ?? []);

							if (cesNew > cesOld) cesImprovedCount++;
							totalCesChange += cesNew - cesOld;

							// Days active approximation
							const profile = (candidates as unknown as ProfileRow[]).find(
								(p) => p.user_id === uid,
							);
							if (profile?.last_login_at) {
								const firstActive = new Date(
									profile.last_login_at as string,
								).getTime();
								daysActiveList.push(
									Math.floor(
										(now.getTime() - firstActive) / (1000 * 60 * 60 * 24),
									),
								);
							}
						}

						const churnCount =
							activeUsers90d.length - confirmedStillActive.length;
						const retentionGrowthPct =
							activeUsers90d.length > 0
								? Math.round(
										(cesImprovedCount / activeUsers90d.length) * 10000,
									) / 100
								: 0;
						const avgCesChange =
							confirmedStillActive.length > 0
								? Math.round(
										(totalCesChange / confirmedStillActive.length) * 100,
									) / 100
								: 0;

						const kpi: MonthlyKPIResult = {
							yearMonth,
							retentionGrowthPct,
							active90dAgo: activeUsers90d.length,
							stillActive: confirmedStillActive.length,
							cesImproved: cesImprovedCount,
							churnCount,
							avgCesChange,
							medianDaysActive: median(daysActiveList),
							computedAt: now.toISOString(),
						};

						await storeAndReport(kpi);

						return {
							itemsProcessed: activeUsers90d.length,
							metadata: kpi as unknown as Record<string, unknown>,
						};
					},
				);
			},
			125,
		);

		if ("skipped" in lockResult && lockResult.skipped) {
			return res.status(200).json({ skipped: true });
		}

		return res.status(200).json({
			success: true,
			result: (lockResult as Record<string, unknown>).result,
		});
	} catch (err) {
		const message = err instanceof Error ? err.message : String(err);
		logger.error("[monthly-kpi] Cron execution failed", { error: message });
		try {
			const { captureServerException } = await import(
				"../_lib/sentryServer.js"
			);
			await captureServerException(err, { cronJob: "monthly-kpi" });
		} catch {
			/* sentry non-critical */
		}
		alertCronFailure("monthly-kpi", message);
		return res.status(200).json({ ok: false, error: message });
	}
}

function computeCES(posts: PostEngRow[]): number {
	if (posts.length === 0) return 0;
	let totalEng = 0;
	let totalViews = 0;
	for (const p of posts) {
		totalEng +=
			(p.likes_count ?? 0) + (p.replies_count ?? 0) + (p.reposts_count ?? 0);
		totalViews += p.views_count ?? 0;
	}
	return totalViews > 0 ? (totalEng / totalViews) * 100 : 0;
}

async function assertLastLoginSchema(supabase: SupabaseClient): Promise<void> {
	const { error } = await supabase
		.from("user_preferences")
		.select("user_id, last_login_at")
		.limit(1);

	if (!error) return;
	throw new Error(
		`monthly-kpi schema mismatch: expected user_preferences.last_login_at (${error.message})`,
	);
}

async function storeAndReport(kpi: MonthlyKPIResult): Promise<void> {
	// Store in Redis
	try {
		const redis = getRedis();
		await redis.set(
			`kpi:monthly:${kpi.yearMonth}`,
			JSON.stringify(kpi),
			{ ex: 90 * 24 * 60 * 60 }, // 90 day TTL
		);
	} catch (err) {
		logger.error("[monthly-kpi] Redis store failed", { error: String(err) });
	}

	// Format month name
	const [year, month] = kpi.yearMonth.split("-");
	const monthName = new Date(
		parseInt(year!, 10),
		parseInt(month!, 10) - 1,
	).toLocaleString("en-US", { month: "short" });

	// Send Discord report
	await alert(AlertLevel.INFO, `📊 Monthly KPI — ${monthName} ${year}`, {
		"Retention+Growth": `${kpi.retentionGrowthPct}% (target: 40%)`,
		"Active 90d ago": String(kpi.active90dAgo),
		"Still active": String(kpi.stillActive),
		"CES improved": String(kpi.cesImproved),
		Churned: String(kpi.churnCount),
		"Avg CES change": `${kpi.avgCesChange > 0 ? "+" : ""}${kpi.avgCesChange}`,
		"Median days active": String(kpi.medianDaysActive),
	});
}
