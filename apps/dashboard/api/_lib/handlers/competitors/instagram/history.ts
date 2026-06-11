// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Handlers: GET  /api/competitors?action=ig-comparison-history
 *           POST /api/competitors?action=ig-detect-alerts
 *
 * Instagram competitor comparison history and alert detection.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	getAuthUserOrError,
} from "../../../apiResponse.js";
import { db } from "../shared.js";

interface CompetitorIdUsername {
	id: string;
	username: string;
}

interface SnapshotRow {
	competitor_id: string;
	snapshot_date: string;
	follower_count: number | null;
	engagement_rate: number | null;
}

interface EngagementRateRow {
	engagement_rate: number | null;
}

interface CompetitorAlert {
	user_id: string;
	competitor_id: string;
	alert_type: string;
	message: string;
	metadata: Record<string, unknown>;
}

export async function handleIgComparisonHistory(
	req: VercelRequest,
	res: VercelResponse,
) {
	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const competitorIdsParam = req.query.competitorIds as string;
	const days = Math.min(
		Math.max(parseInt(req.query.days as string, 10) || 30, 1),
		365,
	);

	if (!competitorIdsParam) {
		return apiError(res, 400, "competitorIds required");
	}

	const competitorIds = competitorIdsParam.split(",");

	// Verify these competitors belong to the user
	const { data: verified } = await db()
		.from("competitors")
		.select("id, username")
		.eq("user_id", user.id)
		.eq("platform", "instagram")
		.in("id", competitorIds);

	if (!verified || verified.length === 0) {
		return apiSuccess(res, { series: [] });
	}

	const typedVerified = verified as CompetitorIdUsername[];
	const verifiedIds = typedVerified.map((c: CompetitorIdUsername) => c.id);
	const usernameMap = Object.fromEntries(
		typedVerified.map((c: CompetitorIdUsername) => [c.id, c.username]),
	);

	const startDate = new Date();
	startDate.setDate(startDate.getDate() - days);
	const startDateStr = startDate.toISOString().split("T")[0]!;

	const { data: snapshots } = (await db()
		.from("competitor_snapshots")
		.select("competitor_id, snapshot_date, follower_count, engagement_rate")
		.in("competitor_id", verifiedIds)
		.gte("snapshot_date", startDateStr)
		.order("snapshot_date", { ascending: true })) as {
		data: SnapshotRow[] | null;
		error: unknown;
	};

	// Group by competitor
	const seriesMap: Record<
		string,
		{ date: string; followers: number; engagementRate: number | null }[]
	> = {};
	for (const snap of snapshots || []) {
		const id = snap.competitor_id;
		if (!seriesMap[id]) seriesMap[id] = [];
		seriesMap[id].push({
			date: snap.snapshot_date,
			followers: snap.follower_count || 0,
			engagementRate: snap.engagement_rate ?? null,
		});
	}

	const series = Object.entries(seriesMap).map(([competitorId, data]) => ({
		competitorId,
		username: usernameMap[competitorId] || "unknown",
		data,
	}));

	return apiSuccess(res, { series });
}

export async function handleIgDetectAlerts(
	req: VercelRequest,
	res: VercelResponse,
) {
	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	// Get all IG competitors
	const { data: competitors } = await db()
		.from("competitors")
		.select("id, username, follower_count, engagement_rate, avatar_url")
		.eq("user_id", user.id)
		.eq("platform", "instagram");

	if (!competitors || competitors.length === 0) {
		return apiSuccess(res, { alertsCreated: 0 });
	}

	const alerts: CompetitorAlert[] = [];
	const milestones = [100000, 50000, 10000, 5000, 1000];
	const sevenDaysAgo = new Date();
	sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
	const sevenDaysAgoStr = sevenDaysAgo.toISOString().split("T")[0]!;

	for (const comp of competitors) {
		// Check follower milestones
		const followers = comp.follower_count || 0;
		for (const milestone of milestones) {
			if (followers >= milestone) {
				// Check if we already have this alert
				const { data: existing } = await db()
					.from("competitor_alerts")
					.select("id")
					.eq("user_id", user.id)
					.eq("competitor_id", comp.id)
					.eq("alert_type", "follower_milestone")
					.contains("metadata", { milestone })
					.limit(1);

				if (!existing || existing.length === 0) {
					const formattedMilestone =
						milestone >= 1000 ? `${milestone / 1000}K` : `${milestone}`;
					alerts.push({
						user_id: user.id,
						competitor_id: comp.id,
						alert_type: "follower_milestone",
						message: `@${comp.username} reached ${formattedMilestone} followers!`,
						metadata: {
							milestone,
							currentFollowers: followers,
							avatarUrl: comp.avatar_url,
						},
					});
				}
				break; // Only check highest milestone
			}
		}

		// Check growth spike (>10% weekly)
		const { data: weekAgoSnap } = await db()
			.from("competitor_snapshots")
			.select("follower_count")
			.eq("competitor_id", comp.id)
			.lte("snapshot_date", sevenDaysAgoStr)
			.order("snapshot_date", { ascending: false })
			.limit(1);

		if (weekAgoSnap && weekAgoSnap.length > 0) {
			const prevFollowers = weekAgoSnap[0]!.follower_count || 0;
			if (prevFollowers > 0) {
				const growthPct = ((followers - prevFollowers) / prevFollowers) * 100;
				if (growthPct > 10) {
					alerts.push({
						user_id: user.id,
						competitor_id: comp.id,
						alert_type: "growth_spike",
						message: `@${comp.username} grew ${Math.round(growthPct)}% in the last 7 days!`,
						metadata: {
							growthPct: Math.round(growthPct * 100) / 100,
							prevFollowers,
							currentFollowers: followers,
							avatarUrl: comp.avatar_url,
						},
					});
				}
			}
		}

		// Check engagement spike (>2x avg)
		const { data: recentSnaps } = (await db()
			.from("competitor_snapshots")
			.select("engagement_rate")
			.eq("competitor_id", comp.id)
			.not("engagement_rate", "is", null)
			.order("snapshot_date", { ascending: false })
			.limit(14)) as { data: EngagementRateRow[] | null; error: unknown };

		if (recentSnaps && recentSnaps.length >= 2) {
			const latest = recentSnaps[0]!.engagement_rate || 0;
			const olderRates = recentSnaps
				.slice(1)
				.map((s: EngagementRateRow) => s.engagement_rate || 0)
				.filter((r: number) => r > 0);
			if (olderRates.length > 0) {
				const avgRate =
					olderRates.reduce((s: number, r: number) => s + r, 0) /
					olderRates.length;
				if (avgRate > 0 && latest > avgRate * 2) {
					alerts.push({
						user_id: user.id,
						competitor_id: comp.id,
						alert_type: "engagement_spike",
						message: `@${comp.username}'s engagement rate spiked to ${latest.toFixed(1)}% (avg: ${avgRate.toFixed(1)}%)`,
						metadata: {
							currentRate: latest,
							avgRate,
							avatarUrl: comp.avatar_url,
						},
					});
				}
			}
		}
	}

	// Insert alerts
	if (alerts.length > 0) {
		await db()
			.from("competitor_alerts")
			// biome-ignore lint/suspicious/noExplicitAny: Supabase insert
			.insert(alerts as any);
	}

	return apiSuccess(res, { alertsCreated: alerts.length });
}
