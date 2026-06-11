// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Smart Timing Engine — Group-Level Hour Analysis
 *
 * Runs weekly (Wednesdays) via daily-orchestrator Phase 5.
 * Analyzes engagement by posting hour across ALL accounts in each group
 * (not per-account, which had insufficient data). Writes best hours to
 * auto_post_group_config for the timing engine to consume.
 *
 * Minimum data requirement: 30+ published posts with views in last 21 days.
 * Falls back to no-op for groups without enough data.
 */

import { logger } from "../logger.js";
import { getSupabaseAny } from "../supabase.js";

const db = () => getSupabaseAny();

interface TimingResult {
	accountsAnalyzed: number;
	overridesWritten: number;
	antiPatternsDetected: number;
}

interface HourBucket {
	hour: number;
	totalEngagement: number;
	postCount: number;
	avgEngagement: number;
}

export async function computeSmartTiming(): Promise<TimingResult> {
	let accountsAnalyzed = 0;
	let overridesWritten = 0;
	let antiPatternsDetected = 0;

	try {
		// Load all enabled group configs with their group account IDs
		const { data: groupConfigs } = await db()
			.from("auto_post_group_config")
			.select(
				"group_id, workspace_id, active_hours_start, active_hours_end, timezone",
			)
			.eq("enabled", true);

		if (!groupConfigs || groupConfigs.length === 0) {
			logger.info("[smart-timing] No enabled groups found");
			return {
				accountsAnalyzed: 0,
				overridesWritten: 0,
				antiPatternsDetected: 0,
			};
		}

		const twentyOneDaysAgo = new Date(
			Date.now() - 21 * 86_400_000,
		).toISOString();

		for (const gc of groupConfigs) {
			try {
				// Get all accounts in this group
				const { data: groupData } = await db()
					.from("account_groups")
					.select("account_ids")
					.eq("id", gc.group_id)
					.maybeSingle();

				const accountIds = (groupData?.account_ids || []) as string[];
				if (accountIds.length === 0) continue;

				accountsAnalyzed += accountIds.length;

				// Query published posts with engagement data for all group accounts
				const { data: posts } = await db()
					.from("posts")
					.select("published_at, views_count, replies_count, likes_count")
					.in("account_id", accountIds)
					.eq("status", "published")
					.not("views_count", "is", null)
					.gte("published_at", twentyOneDaysAgo)
					.limit(500);

				if (!posts || posts.length < 30) {
					logger.debug("[smart-timing] Insufficient data for group", {
						groupId: gc.group_id,
						postCount: posts?.length ?? 0,
						minRequired: 30,
					});
					continue;
				}

				// Bucket posts by publishing hour (in group's timezone)
				const tz = gc.timezone || "UTC";
				// Validate timezone before processing — invalid tz would silently skip all posts
				try {
					new Date().toLocaleString("en-US", { timeZone: tz });
				} catch {
					logger.warn("[smart-timing] Invalid timezone for group, skipping", {
						groupId: gc.group_id,
						timezone: tz,
					});
					continue;
				}
				const hourBuckets = new Map<
					number,
					{ totalEngagement: number; postCount: number }
				>();

				for (const post of posts) {
					if (!post.published_at) continue;
					const views = (post.views_count as number) || 0;
					const replies = (post.replies_count as number) || 0;
					const likes = (post.likes_count as number) || 0;
					const engagement = views + replies * 5 + likes * 2;

					let hour: number;
					try {
						const hourStr = new Date(
							post.published_at as string,
						).toLocaleString("en-US", {
							hour: "numeric",
							hour12: false,
							timeZone: tz,
						});
						hour = parseInt(hourStr, 10);
						if (Number.isNaN(hour)) continue;
					} catch {
						continue;
					}

					const bucket = hourBuckets.get(hour) || {
						totalEngagement: 0,
						postCount: 0,
					};
					bucket.totalEngagement += engagement;
					bucket.postCount++;
					hourBuckets.set(hour, bucket);
				}

				// Compute average engagement per hour, filter to hours with 3+ posts
				const validBuckets: HourBucket[] = [];
				for (const [hour, bucket] of hourBuckets) {
					if (bucket.postCount >= 3) {
						validBuckets.push({
							hour,
							totalEngagement: bucket.totalEngagement,
							postCount: bucket.postCount,
							avgEngagement: bucket.totalEngagement / bucket.postCount,
						});
					}
				}

				if (validBuckets.length < 3) {
					logger.debug("[smart-timing] Not enough hour buckets with 3+ posts", {
						groupId: gc.group_id,
						validBuckets: validBuckets.length,
					});
					continue;
				}

				// Sort by average engagement (best first)
				validBuckets.sort((a, b) => b.avgEngagement - a.avgEngagement);

				// Top 5 hours = best posting hours
				const bestHours = validBuckets.slice(0, 5).map((b) => b.hour);

				// Detect anti-patterns: hours with consistently <50% of mean engagement
				const meanEngagement =
					validBuckets.reduce((s, b) => s + b.avgEngagement, 0) /
					validBuckets.length;
				const deadHours = validBuckets.filter(
					(b) => b.avgEngagement < meanEngagement * 0.5,
				);
				if (deadHours.length > 0) {
					antiPatternsDetected += deadHours.length;
					logger.info("[smart-timing] Dead hours detected", {
						groupId: gc.group_id,
						deadHours: deadHours.map(
							(h) =>
								`${h.hour}:00 (${h.avgEngagement.toFixed(0)} avg, ${h.postCount} posts)`,
						),
					});
				}

				// Compute optimal active window: contiguous block containing top hours
				const sortedBestHours = [...bestHours].sort((a, b) => a - b);
				const activeStart = Math.max(0, sortedBestHours[0]! - 1); // 1h before earliest best hour
				const activeEnd = Math.min(
					24,
					sortedBestHours[sortedBestHours.length - 1]! + 2,
				); // 1h after latest best hour

				// Write to group config — only update if significantly different from current
				const currentStart = gc.active_hours_start ?? 0;
				const currentEnd = gc.active_hours_end ?? 24;
				const startChanged = Math.abs(activeStart - currentStart) >= 2;
				const endChanged = Math.abs(activeEnd - currentEnd) >= 2;

				if (startChanged || endChanged) {
					const { error } = await db()
						.from("auto_post_group_config")
						.update({
							active_hours_start: activeStart,
							active_hours_end: activeEnd,
							smart_timing_best_hours: bestHours,
							smart_timing_updated_at: new Date().toISOString(),
						})
						.eq("group_id", gc.group_id)
						.eq("workspace_id", gc.workspace_id);

					if (!error) {
						overridesWritten++;
						logger.info("[smart-timing] Updated group timing", {
							groupId: gc.group_id,
							bestHours,
							activeWindow: `${activeStart}-${activeEnd}`,
							previousWindow: `${currentStart}-${currentEnd}`,
							postsAnalyzed: posts.length,
							buckets: validBuckets.length,
						});
					} else {
						logger.warn("[smart-timing] Failed to update group config", {
							groupId: gc.group_id,
							error: String(error),
						});
					}
				} else {
					logger.debug("[smart-timing] Timing unchanged for group", {
						groupId: gc.group_id,
						activeWindow: `${activeStart}-${activeEnd}`,
					});
				}
			} catch (groupErr) {
				logger.warn("[smart-timing] Error processing group", {
					groupId: gc.group_id,
					error:
						groupErr instanceof Error ? groupErr.message : String(groupErr),
				});
			}
		}
	} catch (err) {
		logger.error("[smart-timing] Top-level error", {
			error: err instanceof Error ? err.message : String(err),
		});
	}

	logger.info("[smart-timing] Complete", {
		accountsAnalyzed,
		overridesWritten,
		antiPatternsDetected,
	});

	return { accountsAnalyzed, overridesWritten, antiPatternsDetected };
}
