// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Discord Operations Dashboard — automated reporting to Discord
 *
 * Three report cadences:
 *   - Hourly status ping (every hour via health-monitor)
 *   - Daily report (6 AM ET via daily-orchestrator)
 *   - Weekly strategy recommendation (Sundays via weekly-reports)
 *
 * Also sends milestone/alert messages in real-time:
 *   - Viral post detection (500+ views in 2 hours)
 *   - Account milestones (follower thresholds)
 *   - Quality gate rejection rate alerts
 *   - Shadowban warnings
 */

import { logger, serializeError } from "../logger.js";
import { getSupabase } from "../supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: flexible query results
const db = (): any => getSupabase();

const LOG_PREFIX = "[discord-ops]";

// ============================================================================
// Discord Webhook Helper
// ============================================================================

async function sendToDiscord(content: string): Promise<void> {
	const webhookUrl =
		process.env.DISCORD_OPS_WEBHOOK_URL ||
		process.env.DISCORD_ALERT_WEBHOOK_URL;
	if (!webhookUrl) {
		logger.warn(`${LOG_PREFIX} No Discord webhook configured`);
		return;
	}

	try {
		await fetch(webhookUrl, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ content }),
			signal: AbortSignal.timeout(5000),
		});
	} catch (err) {
		logger.error(`${LOG_PREFIX} Discord send failed`, { error: String(err) });
	}
}

async function sendEmbed(
	title: string,
	description: string,
	color: number,
	fields?: { name: string; value: string; inline?: boolean | undefined }[],
): Promise<void> {
	const webhookUrl =
		process.env.DISCORD_OPS_WEBHOOK_URL ||
		process.env.DISCORD_ALERT_WEBHOOK_URL;
	if (!webhookUrl) return;

	try {
		await fetch(webhookUrl, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				embeds: [
					{
						title,
						description,
						color,
						fields: fields || [],
						timestamp: new Date().toISOString(),
						footer: { text: "Juno33 Autoposter" },
					},
				],
			}),
			signal: AbortSignal.timeout(5000),
		});
	} catch (err) {
		logger.error(`${LOG_PREFIX} Discord embed send failed`, {
			error: String(err),
		});
	}
}

// ============================================================================
// Hourly Status Ping
// ============================================================================

export async function sendHourlyPing(): Promise<void> {
	try {
		// Skip hourly ping entirely when autoposter is disabled — avoids misleading
		// "Queue: X pending" messages that look like alerts when nothing is posting.
		const { data: enabledWorkspaces, error: enabledWorkspacesError } =
			await db()
				.from("auto_post_config")
				.select("workspace_id")
				.eq("is_enabled", true)
				.limit(1);
		if (enabledWorkspacesError) {
			logger.error(`${LOG_PREFIX} Failed to check autoposter enabled state`, {
				error: serializeError(enabledWorkspacesError),
			});
		} else if (!enabledWorkspaces || enabledWorkspaces.length === 0) {
			logger.info(`${LOG_PREFIX} Hourly ping skipped — autoposter disabled`);
			return;
		}

		const now = new Date();
		const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);

		// Posts published in last hour
		const { data: publishedPosts } = await db()
			.from("posts")
			.select("id, content, views_count, account_id, accounts(username)")
			.eq("platform", "threads")
			.eq("status", "published")
			.gte("published_at", oneHourAgo.toISOString())
			.order("views_count", { ascending: false });

		const publishedCount = publishedPosts?.length || 0;

		// Queue status
		const { data: queueItems } = await db()
			.from("auto_post_queue")
			.select("id")
			.in("status", ["pending", "queued"]);
		const queueCount = queueItems?.length || 0;

		// Quality gate rejections in last hour
		const { data: rejectedItems } = await db()
			.from("auto_post_queue")
			.select("id")
			.eq("status", "rejected")
			.gte("created_at", oneHourAgo.toISOString());
		const rejectedCount = rejectedItems?.length || 0;

		// Active/dead accounts
		const { data: activeAccounts } = await db()
			.from("accounts")
			.select("id")
			.eq("is_active", true);
		const activeCount = activeAccounts?.length || 0;

		const { data: allAccounts } = await db().from("accounts").select("id");
		const totalCount = allAccounts?.length || 0;

		// Self-replies published in last hour
		const { data: selfReplies } = await db()
			.from("auto_self_replies")
			.select("id")
			.eq("status", "published")
			.gte("published_at", oneHourAgo.toISOString());
		const selfReplyCount = selfReplies?.length || 0;

		// Cross-replies published in last hour
		const { data: crossReplies } = await db()
			.from("auto_cross_replies")
			.select("id")
			.eq("status", "published")
			.gte("published_at", oneHourAgo.toISOString());
		const crossReplyCount = crossReplies?.length || 0;

		// Top post this hour
		let topPostLine = "No posts this hour";
		if (publishedPosts && publishedPosts.length > 0) {
			const top = publishedPosts[0];
			const acctName =
				((top as Record<string, unknown>).accounts as Record<string, unknown>)
					?.username || "unknown";
			const preview = (top.content || "").slice(0, 60);
			topPostLine = `"${preview}..." - ${top.views_count || 0} views (${acctName})`;
		}

		const timeStr = now.toLocaleString("en-US", {
			timeZone: "America/New_York",
			month: "short",
			day: "numeric",
			hour: "numeric",
			minute: "2-digit",
			hour12: true,
		});

		const msg = [
			`**HOURLY** - ${timeStr} ET`,
			`Published: **${publishedCount}** | Queue: **${queueCount}** pending | Rejected: **${rejectedCount}** (quality gate)`,
			`Self-replies: **${selfReplyCount}** | Cross-replies: **${crossReplyCount}**`,
			`Top post: ${topPostLine}`,
			`Active: **${activeCount}/${totalCount}** | Dead: **${totalCount - activeCount}/${totalCount}**`,
		].join("\n");

		await sendToDiscord(msg);
		logger.info(`${LOG_PREFIX} Hourly ping sent`);
	} catch (err) {
		logger.error(`${LOG_PREFIX} Hourly ping failed`, {
			error: serializeError(err),
		});
	}
}

// ============================================================================
// Daily Report (6 AM ET)
// ============================================================================

export async function sendDailyReport(): Promise<void> {
	try {
		const now = new Date();
		const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);

		// Total metrics for the day
		const { data: dayPosts } = await db()
			.from("posts")
			.select(
				"id, views_count, replies_count, likes_count, reposts_count, account_id, content, accounts(username, group_id)",
			)
			.eq("platform", "threads")
			.eq("status", "published")
			.gte("published_at", yesterday.toISOString());

		const totalPosts = dayPosts?.length || 0;
		let totalViews = 0;
		let totalReplies = 0;
		let totalLikes = 0;

		for (const post of dayPosts || []) {
			totalViews += post.views_count || 0;
			totalReplies += post.replies_count || 0;
			totalLikes += post.likes_count || 0;
		}

		// Quality gate stats
		const { data: rejectedDay } = await db()
			.from("auto_post_queue")
			.select("id")
			.eq("status", "rejected")
			.gte("created_at", yesterday.toISOString());

		const { data: generatedDay } = await db()
			.from("auto_post_queue")
			.select("id")
			.gte("created_at", yesterday.toISOString());

		const rejectedCount = rejectedDay?.length || 0;
		const generatedCount = generatedDay?.length || 0;
		const rejectionRate =
			generatedCount > 0
				? Math.round((rejectedCount / generatedCount) * 100)
				: 0;

		// Group performance
		const groupStats = new Map<
			string,
			{ name: string; views: number; posts: number }
		>();
		for (const post of dayPosts || []) {
			const acct = (post as Record<string, unknown>).accounts as Record<
				string,
				unknown
			>;
			const groupId = (acct?.group_id as string) || "ungrouped";
			if (!groupStats.has(groupId)) {
				groupStats.set(groupId, { name: groupId, views: 0, posts: 0 });
			}
			const stat = groupStats.get(groupId) ?? {
				name: groupId,
				views: 0,
				posts: 0,
			};
			stat.views += post.views_count || 0;
			stat.posts++;
		}

		// Resolve group names
		const groupIds = [...groupStats.keys()].filter((id) => id !== "ungrouped");
		if (groupIds.length > 0) {
			const { data: groups } = await db()
				.from("account_groups")
				.select("id, name")
				.in("id", groupIds);
			for (const g of groups || []) {
				const stat = groupStats.get(g.id);
				if (stat) stat.name = g.name;
			}
		}

		const sortedGroups = [...groupStats.values()].sort(
			(a, b) => b.views - a.views,
		);
		const bestGroup = sortedGroups[0];
		const worstGroup = sortedGroups[sortedGroups.length - 1];

		// Self-reply / cross-reply stats
		const { data: selfRepliesDay } = await db()
			.from("auto_self_replies")
			.select("id")
			.eq("status", "published")
			.gte("published_at", yesterday.toISOString());

		const { data: crossRepliesDay } = await db()
			.from("auto_cross_replies")
			.select("id")
			.eq("status", "published")
			.gte("published_at", yesterday.toISOString());

		// Health tier distribution
		const { data: healthData } = await db()
			.from("account_health_snapshots")
			.select("health_tier")
			.eq("account_table", "accounts")
			.eq("period_days", 7);

		const tierCounts: Record<string, number> = {
			star: 0,
			healthy: 0,
			struggling: 0,
			dead: 0,
		};
		for (const h of healthData || []) {
			if (h.health_tier in tierCounts) tierCounts[h.health_tier]!++;
		}

		const dateStr = now.toLocaleDateString("en-US", {
			timeZone: "America/New_York",
			month: "short",
			day: "numeric",
		});

		const lines = [
			`**DAILY REPORT** - ${dateStr}`,
			``,
			`**Metrics**`,
			`Views: **${totalViews.toLocaleString()}** | Replies: **${totalReplies}** | Likes: **${totalLikes}** | Posts: **${totalPosts}**`,
			`Self-replies: **${selfRepliesDay?.length || 0}** | Cross-replies: **${crossRepliesDay?.length || 0}**`,
			`Quality gate rejections: **${rejectedCount}** (${rejectionRate}%)`,
			``,
			`**Health Tiers**`,
			`Stars: **${tierCounts.star}** | Healthy: **${tierCounts.healthy}** | Struggling: **${tierCounts.struggling}** | Dead: **${tierCounts.dead}**`,
			``,
			`**Group Performance**`,
		];

		if (bestGroup)
			lines.push(
				`Best: **${bestGroup.name}** (${bestGroup.views.toLocaleString()} views, ${bestGroup.posts} posts)`,
			);
		if (worstGroup && worstGroup !== bestGroup)
			lines.push(
				`Worst: **${worstGroup.name}** (${worstGroup.views.toLocaleString()} views, ${worstGroup.posts} posts)`,
			);

		// Top post
		if (dayPosts && dayPosts.length > 0) {
			const sorted = [...dayPosts].sort(
				(a, b) => (b.views_count || 0) - (a.views_count || 0),
			);
			const top = sorted[0];
			const acctName =
				((top as Record<string, unknown>).accounts as Record<string, unknown>)
					?.username || "unknown";
			lines.push(``);
			lines.push(`**Top Post**`);
			lines.push(
				`"${(top.content || "").slice(0, 80)}..." - **${top.views_count || 0}** views (${acctName})`,
			);
		}

		await sendToDiscord(lines.join("\n"));
		logger.info(`${LOG_PREFIX} Daily report sent`);
	} catch (err) {
		logger.error(`${LOG_PREFIX} Daily report failed`, {
			error: serializeError(err),
		});
	}
}

// ============================================================================
// Weekly Strategy Recommendation (Sundays)
// ============================================================================

export async function sendWeeklyStrategy(): Promise<void> {
	try {
		const now = new Date();
		const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

		// Get all posts from last week with metrics
		const { data: weekPosts } = await db()
			.from("posts")
			.select(
				"id, content, views_count, replies_count, likes_count, published_at, source_type",
			)
			.eq("platform", "threads")
			.eq("status", "published")
			.gte("published_at", weekAgo.toISOString())
			.not("views_count", "is", null);

		if (!weekPosts || weekPosts.length === 0) {
			await sendToDiscord("**WEEKLY STRATEGY** - No data this week");
			return;
		}

		// Analyze content length performance
		const shortPosts = weekPosts.filter(
			(p: Record<string, unknown>) => ((p.content as string) || "").length < 50,
		);
		const longPosts = weekPosts.filter(
			(p: Record<string, unknown>) =>
				((p.content as string) || "").length >= 50,
		);
		const avgViewsShort =
			shortPosts.length > 0
				? shortPosts.reduce(
						(sum: number, p: Record<string, unknown>) =>
							sum + ((p.views_count as number) || 0),
						0,
					) / shortPosts.length
				: 0;
		const avgViewsLong =
			longPosts.length > 0
				? longPosts.reduce(
						(sum: number, p: Record<string, unknown>) =>
							sum + ((p.views_count as number) || 0),
						0,
					) / longPosts.length
				: 0;

		// Analyze question posts vs statements
		const questionPosts = weekPosts.filter((p: Record<string, unknown>) =>
			((p.content as string) || "").includes("?"),
		);
		const statementPosts = weekPosts.filter(
			(p: Record<string, unknown>) =>
				!((p.content as string) || "").includes("?"),
		);
		const avgViewsQuestion =
			questionPosts.length > 0
				? questionPosts.reduce(
						(sum: number, p: Record<string, unknown>) =>
							sum + ((p.views_count as number) || 0),
						0,
					) / questionPosts.length
				: 0;
		const avgViewsStatement =
			statementPosts.length > 0
				? statementPosts.reduce(
						(sum: number, p: Record<string, unknown>) =>
							sum + ((p.views_count as number) || 0),
						0,
					) / statementPosts.length
				: 0;

		// Analyze by hour of day
		const hourBuckets: Record<number, { views: number; count: number }> = {};
		for (const post of weekPosts) {
			const hour = new Date(post.published_at).getHours();
			if (!hourBuckets[hour]) hourBuckets[hour] = { views: 0, count: 0 };
			hourBuckets[hour].views += post.views_count || 0;
			hourBuckets[hour].count++;
		}

		const hourAvgs = Object.entries(hourBuckets)
			.map(([hour, data]) => ({
				hour: Number(hour),
				avgViews: data.views / data.count,
			}))
			.sort((a, b) => b.avgViews - a.avgViews);

		const bestHours = hourAvgs
			.slice(0, 3)
			.map((h) => {
				const ampm = h.hour >= 12 ? "pm" : "am";
				const display = h.hour === 0 ? 12 : h.hour > 12 ? h.hour - 12 : h.hour;
				return `${display}${ampm}`;
			})
			.join(", ");

		const worstHours = hourAvgs
			.slice(-3)
			.map((h) => {
				const ampm = h.hour >= 12 ? "pm" : "am";
				const display = h.hour === 0 ? 12 : h.hour > 12 ? h.hour - 12 : h.hour;
				return `${display}${ampm}`;
			})
			.join(", ");

		// Total stats
		const totalViews = weekPosts.reduce(
			(sum: number, p: Record<string, unknown>) =>
				sum + ((p.views_count as number) || 0),
			0,
		);
		const totalReplies = weekPosts.reduce(
			(sum: number, p: Record<string, unknown>) =>
				sum + ((p.replies_count as number) || 0),
			0,
		);

		const dateRange = `${weekAgo.toLocaleDateString("en-US", { month: "short", day: "numeric" })} - ${now.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;

		const questionMultiplier =
			avgViewsStatement > 0
				? (avgViewsQuestion / avgViewsStatement).toFixed(1)
				: "N/A";
		const shortMultiplier =
			avgViewsLong > 0 ? (avgViewsShort / avgViewsLong).toFixed(1) : "N/A";

		const lines = [
			`**WEEKLY STRATEGY** - ${dateRange}`,
			``,
			`**Overall**: ${totalViews.toLocaleString()} views | ${totalReplies} replies | ${weekPosts.length} posts`,
			``,
			`**What's Working**`,
			`Questions vs statements: **${questionMultiplier}x** (${questionPosts.length} questions, avg ${Math.round(avgViewsQuestion)} views)`,
			`Short (<50 chars) vs long: **${shortMultiplier}x** (${shortPosts.length} short, avg ${Math.round(avgViewsShort)} views)`,
			`Best hours: **${bestHours}** (highest avg views)`,
			``,
			`**What's Not Working**`,
			`Worst hours: **${worstHours}** (lowest avg views)`,
			avgViewsLong > avgViewsShort
				? `Long posts outperforming short — test more detailed content`
				: ``,
			``,
			`**Action Items**`,
			questionMultiplier !== "N/A" && Number(questionMultiplier) > 1.5
				? `Increase question content to 60%+`
				: `Question content not outperforming — diversify formats`,
			`Focus posting during ${bestHours}`,
			`Reduce posting during ${worstHours}`,
		].filter(Boolean);

		await sendToDiscord(lines.join("\n"));
		logger.info(`${LOG_PREFIX} Weekly strategy sent`);
	} catch (err) {
		logger.error(`${LOG_PREFIX} Weekly strategy failed`, {
			error: serializeError(err),
		});
	}
}

// ============================================================================
// Real-time Milestone Alerts
// ============================================================================

/**
 * Check for viral posts (500+ views in 2 hours) and milestone events.
 * Called from health-monitor cron.
 */
export async function checkMilestonesAndAlerts(): Promise<void> {
	try {
		const now = new Date();
		const twoHoursAgo = new Date(now.getTime() - 2 * 60 * 60 * 1000);

		// Viral detection: posts with 500+ views published in last 2 hours
		const { data: viralPosts } = await db()
			.from("posts")
			.select("id, content, views_count, published_at, accounts(username)")
			.eq("platform", "threads")
			.eq("status", "published")
			.gte("published_at", twoHoursAgo.toISOString())
			.gte("views_count", 500)
			.order("views_count", { ascending: false })
			.limit(5);

		for (const post of viralPosts || []) {
			const acctName =
				((post as Record<string, unknown>).accounts as Record<string, unknown>)
					?.username || "unknown";
			const preview = (post.content || "").slice(0, 80);
			await sendEmbed(
				"VIRAL POST DETECTED",
				`"${preview}..." hit **${post.views_count}** views in 2 hours`,
				0x00ff00, // Green
				[
					{ name: "Account", value: `@${acctName}`, inline: true },
					{ name: "Views", value: String(post.views_count), inline: true },
				],
			);
		}

		// Quality gate rejection rate alert.
		// The autoposter intentionally over-generates and rejects weak candidates, so
		// raw rejection rate is only actionable when it also starves the ready queue.
		const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
		const { data: hourGenerated } = await db()
			.from("auto_post_queue")
			.select("id, status")
			.gte("created_at", oneHourAgo.toISOString());

		if (hourGenerated && hourGenerated.length >= 10) {
			const rejected = hourGenerated.filter(
				(i: { status: string }) => i.status === "rejected",
			).length;
			const accepted = hourGenerated.filter((i: { status: string }) =>
				["pending", "queued", "published"].includes(i.status),
			).length;
			const rate = (rejected / hourGenerated.length) * 100;
			const { count: readyDepth } = await db()
				.from("auto_post_queue")
				.select("*", { count: "exact", head: true })
				.eq("platform", "threads")
				.in("status", ["pending", "queued"]);

			if (rate > 80 && accepted < 3 && (readyDepth || 0) < 10) {
				await sendEmbed(
					"Quality Gate Alert",
					`**${Math.round(rate)}%** rejection rate in last hour (${rejected}/${hourGenerated.length}) and ready queue is low (${readyDepth || 0})`,
					0xf39c12, // Orange
					[
						{
							name: "Action",
							value:
								"Queue fill may be starving. Inspect gate reasons and recent fill logs.",
						},
					],
				);
			}
		}

		// Shadowban warnings: accounts with 0 views for 72+ hours
		const { data: possibleBans } = await db()
			.from("account_health_snapshots")
			.select("account_name, consecutive_dead_days")
			.eq("account_table", "accounts")
			.gte("consecutive_dead_days", 3)
			.eq("period_days", 7);

		for (const ban of possibleBans || []) {
			await sendEmbed(
				"Shadowban Warning",
				`**@${ban.account_name}**: 0 views for ${ban.consecutive_dead_days} consecutive days`,
				0xe74c3c, // Red
				[{ name: "Action", value: "Flagged for recovery protocol" }],
			);
		}
	} catch (err) {
		logger.error(`${LOG_PREFIX} Milestone check failed`, {
			error: serializeError(err),
		});
	}
}
