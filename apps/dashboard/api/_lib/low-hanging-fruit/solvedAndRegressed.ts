/**
 * Solved & regressed recommendation tracking.
 * Detects when recommendations have been addressed (metrics improved beyond threshold)
 * and tracks regressions (previously solved recs that have worsened again).
 */

import { logger } from "../logger.js";
import type {
	Recommendation,
	RecommendationCategory,
	RegressedRecommendation,
	SolvedRecommendation,
} from "./shared.js";
import { db } from "./shared.js";

/**
 * Check previously stored recommendations against current metrics to detect solved ones.
 */
export async function detectSolvedRecs(
	accountId: string,
	platform: string,
	currentRecs: Recommendation[],
): Promise<SolvedRecommendation[]> {
	const solved: SolvedRecommendation[] = [];

	try {
		// Look up stored baselines
		const { data: stored } = await db()
			.from("recommendation_baselines")
			.select(
				"rec_id, title, icon, category, baseline_value, threshold, post_opt_value",
			)
			.eq("account_id", accountId)
			.eq("platform", platform);

		if (!stored || stored.length === 0) return solved;

		const currentRecIds = new Set(currentRecs.map((r) => r.id));

		for (const baseline of stored) {
			// If this rec no longer appears (metric improved), it's solved
			if (!currentRecIds.has(baseline.rec_id)) {
				// We know the metric exceeded the threshold (baseline + 20%),
				// but don't know the exact current value. Report minimum improvement.
				const minImprovement = baseline.threshold - baseline.baseline_value;
				const improvementPct = Math.round(
					(minImprovement / Math.max(baseline.baseline_value, 0.01)) * 100,
				);
				if (improvementPct > 20) {
					solved.push({
						id: baseline.rec_id,
						title: baseline.title,
						icon: baseline.icon as string,
						category: baseline.category as RecommendationCategory,
						improvementPct,
						baselineValue: baseline.baseline_value,
						currentValue: baseline.post_opt_value ?? baseline.threshold,
					});

					// Mark baseline as solved for regression monitoring
					try {
						await db()
							.from("recommendation_baselines")
							.update({
								solved: true,
								solved_at: new Date().toISOString(),
								post_opt_value: baseline.threshold,
							})
							.eq("account_id", accountId)
							.eq("platform", platform)
							.eq("rec_id", baseline.rec_id);
					} catch (err) {
						logger.warn(
							"[lowHangingFruit] Failed to mark recommendation baseline as solved",
							{
								accountId,
								recId: baseline.rec_id,
								error: String(err),
							},
						);
						// non-fatal
					}
				}
			}
		}
	} catch (err) {
		logger.warn("[lowHangingFruit] Failed to detect solved recommendations", {
			accountId,
			platform,
			error: String(err),
		});
		// Table may not exist yet — skip
	}

	return solved;
}

/**
 * Store current recommendation baselines for future solved detection.
 */
export async function storeBaselines(
	accountId: string,
	platform: string,
	recs: Recommendation[],
): Promise<void> {
	try {
		// Upsert baselines
		const rows = recs.map((r) => ({
			account_id: accountId,
			platform,
			rec_id: r.id,
			title: r.title,
			icon: r.icon,
			category: r.category,
			baseline_value: r.baselineValue,
			threshold: r.baselineValue * 1.2 + 0.05, // 20% improvement + small absolute floor
			updated_at: new Date().toISOString(),
		}));

		await db()
			.from("recommendation_baselines")
			.upsert(rows, { onConflict: "account_id,platform,rec_id" });
	} catch (err) {
		logger.warn("[lowHangingFruit] Failed to store recommendation baselines", {
			accountId,
			platform,
			error: String(err),
		});
		// Table may not exist — skip silently
	}
}

/**
 * Fetch regressed recommendations from the database.
 */
export async function getRegressedRecs(
	accountId: string,
	platform: string,
): Promise<RegressedRecommendation[]> {
	const regressed: RegressedRecommendation[] = [];
	try {
		const { data } = await db()
			.from("recommendation_baselines")
			.select(
				"rec_id, title, icon, category, regression_pct, regression_status, regression_detected_at",
			)
			.eq("account_id", accountId)
			.eq("platform", platform)
			.in("regression_status", ["regressed", "faded"]);

		if (!data) return regressed;

		for (const row of data) {
			const detectedAt = row.regression_detected_at
				? new Date(row.regression_detected_at)
				: new Date();
			const daysSince = Math.floor(
				(Date.now() - detectedAt.getTime()) / (1000 * 60 * 60 * 24),
			);

			regressed.push({
				id: row.rec_id,
				title: row.title,
				icon: row.icon as string,
				category: row.category as RecommendationCategory,
				regressionPct: row.regression_pct || 0,
				daysSinceRegression: daysSince,
				status: row.regression_status as "regressed" | "faded",
			});
		}
	} catch (err) {
		logger.warn("[lowHangingFruit] Failed to fetch regressed recommendations", {
			accountId,
			platform,
			error: String(err),
		});
	}
	return regressed;
}
