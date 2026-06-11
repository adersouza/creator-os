// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Advanced recommendation checks (checks 11-13).
 * Cross-group performance gap analysis, post decay/velocity detection,
 * and account health monitoring (stagnation, shadowban).
 */

import { logger } from "../logger.js";
import type { ConfidenceLevel, Recommendation } from "./shared.js";
import { dbAny } from "./shared.js";

// ── Local Types ─────────────────────────────────────────────────────────────

interface DecaySnapshot {
	post_id: string;
	views_count: number | null;
	snapshot_at: string | null;
	hours_since_publish: number | null;
}

interface DecayPost {
	id: string;
	content: string | null;
	published_at: string;
	views_count: number | null;
}

// ── Check 11: Group Performance Gap ──────────────────────────────────────────

/**
 * Compare engagement rates across enabled account groups.
 * If one group outperforms another by >2x, surface a recommendation
 * to shift strategy toward the higher-performing group.
 */
export async function checkGroupPerformanceGap(
	userId: string,
): Promise<Recommendation[]> {
	const recs: Recommendation[] = [];

	try {
		// 1. Get enabled auto-post group configs for this user's workspace
		const { data: groupConfigs } = await dbAny()
			.from("auto_post_group_config")
			.select("group_id")
			.eq("enabled", true);

		if (!groupConfigs || groupConfigs.length < 2) return recs;

		const groupIds = groupConfigs.map(
			(gc: { group_id: string }) => gc.group_id,
		);

		// 2. Fetch account groups (filter by user ownership + match config group_ids)
		const { data: groups } = await dbAny()
			.from("account_groups")
			.select("id, name, account_ids")
			.eq("user_id", userId)
			.in("id", groupIds);

		if (!groups || groups.length < 2) return recs;

		// 3. Collect all account IDs across all groups
		const allAccountIds: string[] = [];
		const groupAccountMap = new Map<string, string[]>();
		const groupNameMap = new Map<string, string>();

		for (const g of groups as Array<{
			id: string;
			name: string;
			account_ids: string[] | null;
		}>) {
			const aids = g.account_ids || [];
			groupAccountMap.set(g.id, aids);
			groupNameMap.set(g.id, g.name || g.id);
			for (const aid of aids) {
				if (!allAccountIds.includes(aid)) {
					allAccountIds.push(aid);
				}
			}
		}

		if (allAccountIds.length === 0) return recs;

		// 4. Query published posts from the last 7 days across all accounts
		const sevenDaysAgo = new Date(
			Date.now() - 7 * 24 * 60 * 60 * 1000,
		).toISOString();

		const { data: postsRaw } = await dbAny()
			.from("posts")
			.select(
				"account_id, likes_count, replies_count, reposts_count, views_count",
			)
			.in("account_id", allAccountIds)
			.eq("status", "published")
			.not("published_at", "is", null)
			.gte("published_at", sevenDaysAgo);

		if (!postsRaw || postsRaw.length === 0) return recs;

		const posts = postsRaw as Array<{
			account_id: string;
			likes_count: number | null;
			replies_count: number | null;
			reposts_count: number | null;
			views_count: number | null;
		}>;

		// 5. Build a reverse map: accountId -> groupId
		const accountToGroup = new Map<string, string>();
		for (const [groupId, aids] of groupAccountMap) {
			for (const aid of aids) {
				accountToGroup.set(aid, groupId);
			}
		}

		// 6. Aggregate engagement per group
		const groupStats = new Map<
			string,
			{ totalEngagement: number; totalViews: number; postCount: number }
		>();

		for (const p of posts) {
			const groupId = accountToGroup.get(p.account_id);
			if (!groupId) continue;

			const engagement =
				(p.likes_count || 0) + (p.replies_count || 0) + (p.reposts_count || 0);
			const views = p.views_count || 0;

			const existing = groupStats.get(groupId) || {
				totalEngagement: 0,
				totalViews: 0,
				postCount: 0,
			};
			existing.totalEngagement += engagement;
			existing.totalViews += views;
			existing.postCount++;
			groupStats.set(groupId, existing);
		}

		// Need at least 2 groups with data
		const groupsWithData = [...groupStats.entries()].filter(
			([_id, s]) => s.postCount >= 3,
		);
		if (groupsWithData.length < 2) return recs;

		// 7. Compute engagement rate per group (engagement / views, or raw engagement if no views)
		const groupERs: Array<{
			groupId: string;
			name: string;
			er: number;
			postCount: number;
		}> = [];

		for (const [groupId, stats] of groupsWithData) {
			const er =
				stats.totalViews > 0
					? (stats.totalEngagement / stats.totalViews) * 100
					: stats.totalEngagement / stats.postCount;
			groupERs.push({
				groupId,
				name: groupNameMap.get(groupId) || groupId,
				er,
				postCount: stats.postCount,
			});
		}

		// Sort descending by ER
		groupERs.sort((a, b) => b.er - a.er);

		const best = groupERs[0];
		const worst = groupERs[groupERs.length - 1];
		if (!best || !worst) return recs;

		// 8. Check if best is >2x worst
		if (worst.er > 0 && best.er / worst.er > 2) {
			const multiplier = (best.er / worst.er).toFixed(1);
			const totalPosts = best.postCount + worst.postCount;
			const confidence: ConfidenceLevel = totalPosts > 20 ? "high" : "medium";
			const confidenceLabel =
				totalPosts > 20
					? `Strong evidence from ${totalPosts} posts across groups`
					: `Based on ${totalPosts} recent posts — more data will improve accuracy`;

			recs.push({
				id: "group-performance-gap",
				title: "Performance gap between groups",
				description: `${best.name} is outperforming ${worst.name} by ${multiplier}x on engagement. Consider shifting content focus or posting frequency toward ${best.name}'s strategy.`,
				impactScore: 7,
				effortScore: 2,
				roi: 3.5,
				dataPoint: `${multiplier}x engagement gap between top and bottom groups`,
				icon: "\u{1F4CA}",
				confidence,
				confidenceLabel,
				ctaPath: "/auto-poster",
				category: "content",
				baselineValue: worst.er,
			});
		}
	} catch (err) {
		logger.warn("[lowHangingFruit] Group performance gap check failed", {
			error: String(err),
			userId,
		});
	}

	return recs;
}

// ── Check 12: Post Decay Detection ───────────────────────────────────────────

/**
 * Detect slow-burn viral posts still gaining views vs posts that have peaked.
 * Queries post_metric_history for posts published in the last 72 hours,
 * compares the two most recent snapshots per post to determine growth velocity.
 *
 * - "Still growing" slow burner: views increasing at >50% of hour-1 velocity AND post >48h old
 * - "Peaked": views flatlined (<5% growth between last 2 snapshots) AND post >24h old
 *
 * Surfaces slow-burners as high-impact recommendations to cross-post or reshare.
 */
export async function checkPostDecayPatterns(
	accountId: string,
	platform: string,
): Promise<Recommendation[]> {
	const recs: Recommendation[] = [];

	try {
		const now = Date.now();
		const cutoff72h = new Date(now - 72 * 60 * 60 * 1000).toISOString();

		// 1. Get posts published in the last 72 hours
		const postsTable = platform === "instagram" ? "instagram_posts" : "posts";
		const accountCol =
			platform === "instagram" ? "instagram_account_id" : "account_id";

		const { data: recentPostsRaw } = await dbAny()
			.from(postsTable)
			.select("id, content, published_at, views_count")
			.eq(accountCol, accountId)
			.gte("published_at", cutoff72h)
			.not("published_at", "is", null)
			.order("published_at", { ascending: false })
			.limit(50);

		const recentPosts = (recentPostsRaw || []) as DecayPost[];
		if (recentPosts.length === 0) return recs;

		const postIds = recentPosts.map((p) => p.id).filter(Boolean);

		// 2. Get all metric history snapshots for these posts, ordered by snapshot_at desc
		const { data: snapshotsRaw } = await dbAny()
			.from("post_metric_history")
			.select("post_id, views_count, snapshot_at, hours_since_publish")
			.in("post_id", postIds)
			.order("snapshot_at", { ascending: false });

		const snapshots = (snapshotsRaw || []) as DecaySnapshot[];
		if (snapshots.length === 0) return recs;

		// 3. Group snapshots by post_id, keeping only the two most recent per post
		const snapshotsByPost = new Map<string, DecaySnapshot[]>();
		for (const snap of snapshots) {
			if (!snap.post_id) continue;
			const existing = snapshotsByPost.get(snap.post_id) || [];
			if (existing.length < 2) {
				existing.push(snap);
				snapshotsByPost.set(snap.post_id, existing);
			}
		}

		// 4. Also gather hour-1 velocity estimates: earliest snapshot per post for baseline
		const earliestSnapshotByPost = new Map<string, DecaySnapshot>();
		// Iterate in reverse (ascending order) to find earliest per post
		for (let i = snapshots.length - 1; i >= 0; i--) {
			const snap = snapshots[i];
			if (!snap?.post_id) continue;
			earliestSnapshotByPost.set(snap.post_id, snap);
		}

		// 5. Analyze each post
		for (const post of recentPosts) {
			if (!post.id || !post.published_at) continue;

			const postAgeHours =
				(now - new Date(post.published_at).getTime()) / (1000 * 60 * 60);
			const twoSnapshots = snapshotsByPost.get(post.id);

			// Need at least 2 snapshots for comparison
			if (!twoSnapshots || twoSnapshots.length < 2) continue;

			const latest = twoSnapshots[0]; // most recent
			const previous = twoSnapshots[1]; // second most recent
			if (!latest || !previous) continue;

			const latestViews = latest.views_count || 0;
			const previousViews = previous.views_count || 0;

			// Skip if no meaningful view data
			if (latestViews === 0 && previousViews === 0) continue;

			// Calculate time delta between snapshots (hours)
			let snapshotDeltaHours = 1; // default fallback
			if (latest.snapshot_at && previous.snapshot_at) {
				snapshotDeltaHours = Math.max(
					0.5,
					(new Date(latest.snapshot_at).getTime() -
						new Date(previous.snapshot_at).getTime()) /
						(1000 * 60 * 60),
				);
			} else if (
				latest.hours_since_publish != null &&
				previous.hours_since_publish != null
			) {
				snapshotDeltaHours = Math.max(
					0.5,
					latest.hours_since_publish - previous.hours_since_publish,
				);
			}

			const viewGrowth = latestViews - previousViews;
			const currentVelocity = viewGrowth / snapshotDeltaHours; // views/hour

			// Estimate hour-1 velocity from the earliest snapshot
			const earliest = earliestSnapshotByPost.get(post.id);
			let hour1Velocity = 0;
			if (
				earliest &&
				earliest.hours_since_publish != null &&
				earliest.hours_since_publish > 0
			) {
				hour1Velocity =
					(earliest.views_count || 0) / earliest.hours_since_publish;
			} else if (earliest?.views_count) {
				// Fallback: assume earliest snapshot was taken ~1h in
				hour1Velocity = earliest.views_count;
			}

			// Avoid division by zero — need a meaningful hour-1 velocity baseline
			if (hour1Velocity <= 0) continue;

			const growthRatio = previousViews > 0 ? viewGrowth / previousViews : 0;

			// Slow-burner detection: still growing at >50% of hour-1 velocity AND >48h old
			if (
				postAgeHours > 48 &&
				currentVelocity > hour1Velocity * 0.5 &&
				currentVelocity > 0
			) {
				const contentPreview = (post.content || "")
					.replace(/\n/g, " ")
					.slice(0, 60)
					.trim();
				const ageLabel =
					postAgeHours >= 48
						? `${Math.round(postAgeHours)} hours`
						: `${Math.round(postAgeHours)} hours`;
				const velocityLabel = Math.round(currentVelocity);

				recs.push({
					id: "slow-burn-trending",
					title: "Slow-burn post still trending",
					description: `Your post '${contentPreview}${(post.content || "").length > 60 ? "..." : ""}' is still gaining views at ${velocityLabel} views/hour after ${ageLabel}. Consider cross-posting to feeders or resharing.`,
					impactScore: 8,
					effortScore: 1,
					roi: 8,
					dataPoint: `${velocityLabel} views/hr after ${ageLabel}`,
					icon: "\u{1F525}",
					confidence: "high",
					confidenceLabel: "Based on post_metric_history snapshot comparison",
					ctaPath: "/compose",
					category: "content",
					baselineValue: currentVelocity,
				});

				// Only surface the best slow-burner
				break;
			}

			// Peaked detection: flatlined (<5% growth) AND >24h old
			// (We don't surface this as a recommendation — it's informational.
			//  The slow-burner is the actionable rec. Peaked posts are expected.)
			if (postAgeHours > 24 && growthRatio < 0.05 && latestViews > 100) {
				// Log for observability but don't surface as rec — peaked posts are normal
				logger.debug("Post peaked (expected lifecycle)", {
					postId: post.id,
					latestViews,
					growthRatio: Math.round(growthRatio * 100),
					postAgeHours: Math.round(postAgeHours),
				});
			}
		}
	} catch (err) {
		logger.warn("[lowHangingFruit] Post decay pattern check failed", {
			error: String(err),
			accountId,
		});
	}

	return recs;
}

// ── Check 13: Account Health ────────────────────────────────────────────────

/**
 * Detect stagnant or shadowbanned accounts by querying account_metrics_history.
 * Surfaces high-impact recommendations for accounts that need attention.
 */
export async function checkAccountHealth(
	accountId: string,
	platform: string,
): Promise<Recommendation[]> {
	const recs: Recommendation[] = [];

	const fourteenDaysAgo = new Date(Date.now() - 14 * 86_400_000)
		.toISOString()
		.split("T")[0]!;
	const sevenDaysAgo = new Date(Date.now() - 7 * 86_400_000)
		.toISOString()
		.split("T")[0]!;

	// Get metrics history for this account
	const { data: history } = await dbAny()
		.from("account_metrics_history")
		.select("date, followers_count, total_views, engagement_rate")
		.eq("account_id", accountId)
		.gte("date", fourteenDaysAgo)
		.order("date", { ascending: true });

	if (!history || (history as unknown[]).length < 3) return recs;

	type HistRow = {
		date: string;
		followers_count: number;
		total_views: number;
		engagement_rate: number;
	};
	const rows = history as HistRow[];

	// Split into this week vs last week
	const thisWeek = rows.filter((h) => h.date >= sevenDaysAgo!);
	const lastWeek = rows.filter((h) => h.date < sevenDaysAgo!);

	if (thisWeek.length === 0 || lastWeek.length === 0) return recs;

	const latestFollowers = thisWeek[thisWeek.length - 1]?.followers_count ?? 0;
	const earliestFollowers = lastWeek[0]?.followers_count ?? 0;
	const followerChange = latestFollowers - earliestFollowers;

	// Check for stagnation: no follower growth + posting activity
	let healthPostsQ = dbAny()
		.from("posts")
		.select("id", { count: "exact", head: true });
	healthPostsQ =
		platform === "instagram"
			? healthPostsQ.eq("instagram_account_id", accountId)
			: healthPostsQ.eq("account_id", accountId);
	const { count: recentPostCount } = await healthPostsQ
		.eq("status", "published")
		.gte("published_at", new Date(Date.now() - 7 * 86_400_000).toISOString());

	const postsThisWeek = recentPostCount || 0;

	if (followerChange <= 0 && postsThisWeek >= 3) {
		recs.push({
			id: "account-stagnant",
			title: "Account growth has stalled",
			description: `This account has ${followerChange === 0 ? "zero" : "negative"} follower growth over 14 days despite ${postsThisWeek} posts this week. Consider a content refresh, engagement-first strategy, or deprioritizing this account.`,
			impactScore: 8,
			effortScore: 3,
			roi: 8 / 3,
			dataPoint: `${followerChange} followers in 14d, ${postsThisWeek} posts/week`,
			icon: "⚠️",
			confidence: "high",
			confidenceLabel: "Based on 14 days of follower history",
			ctaPath: null,
			category: "health",
			baselineValue: 0,
		});
	}

	// Check for possible shadowban: views dropped >50% week-over-week
	const avgViewsThisWeek =
		thisWeek.reduce((sum, h) => sum + (h.total_views || 0), 0) /
		thisWeek.length;
	const avgViewsLastWeek =
		lastWeek.reduce((sum, h) => sum + (h.total_views || 0), 0) /
		lastWeek.length;

	if (
		avgViewsLastWeek > 0 &&
		avgViewsThisWeek < avgViewsLastWeek * 0.5 &&
		followerChange >= 0
	) {
		const dropPct = Math.round((1 - avgViewsThisWeek / avgViewsLastWeek) * 100);
		recs.push({
			id: "account-possible-shadowban",
			title: "Possible shadowban detected",
			description: `Views dropped ${dropPct}% week-over-week (avg ${Math.round(avgViewsLastWeek)} → ${Math.round(avgViewsThisWeek)}) while followers are stable. This may indicate suppression. Consider pausing posting for 7-14 days and engaging manually.`,
			impactScore: 9,
			effortScore: 2,
			roi: 9 / 2,
			dataPoint: `${dropPct}% view drop, followers stable`,
			icon: "🔇",
			confidence: "medium",
			confidenceLabel: "Based on 14-day view history vs follower trend",
			ctaPath: null,
			category: "health",
			baselineValue: avgViewsThisWeek / Math.max(avgViewsLastWeek, 1),
		});
	}

	return recs;
}
