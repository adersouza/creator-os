// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Shadowban Scanner — Daily detection of dead accounts
 *
 * Runs as a phase in daily-orchestrator (1 AM UTC).
 * Checks all Threads accounts used by the autoposter:
 *   - Account must have been posting for 3+ days
 *   - Account must have 10+ published auto-posts
 *   - If total views across ALL auto-posts = 0 → flag as shadowbanned
 *
 * Flagged accounts:
 *   - accounts.is_shadowbanned = true (skipped in round-robin rotation)
 *   - Discord alert with consolidated report
 *
 * Auto-recovery: if a previously flagged account gains views, unflag it.
 */

import { logger } from "../logger.js";
import { getSupabaseAny } from "../supabase.js";

const db = getSupabaseAny;

const MIN_POSTING_DAYS = 2;
const MIN_PUBLISHED_POSTS = 5;

interface ScanResult {
	flagged: string[];
	unflagged: string[];
	totalScanned: number;
}

export async function processShadowbanScan(): Promise<ScanResult> {
	const result: ScanResult = { flagged: [], unflagged: [], totalScanned: 0 };

	// Get all workspaces with autoposter enabled
	const { data: configs } = await db()
		.from("auto_post_config")
		.select("workspace_id, discord_webhook_url")
		.eq("is_enabled", true);

	if (!configs || configs.length === 0) return result;

	// Collect all account IDs used by autoposter groups
	const wsDiscordMap = new Map<string, string | null>();
	const allGroupAccountIds = new Set<string>();

	for (const cfg of configs) {
		wsDiscordMap.set(
			cfg.workspace_id as string,
			(cfg.discord_webhook_url as string) || null,
		);
	}

	const wsIds = Array.from(wsDiscordMap.keys());
	const { data: groupConfigs } = await db()
		.from("auto_post_group_config")
		.select("workspace_id, group_id")
		.in("workspace_id", wsIds)
		.eq("enabled", true);

	if (!groupConfigs || groupConfigs.length === 0) return result;

	const groupIds = groupConfigs.map((g: { group_id: string }) => g.group_id);
	const { data: groups } = await db()
		.from("account_groups")
		.select("id, account_ids")
		.in("id", groupIds);

	if (!groups) return result;

	for (const group of groups) {
		for (const aid of (group.account_ids || []) as string[]) {
			allGroupAccountIds.add(aid);
		}
	}

	if (allGroupAccountIds.size === 0) return result;

	// Get all Threads accounts (with current shadowban status)
	const accountIds = Array.from(allGroupAccountIds);
	const { data: accounts } = await db()
		.from("accounts")
		.select("id, username, is_shadowbanned, created_at")
		.in("id", accountIds)
		.not("threads_user_id", "is", null);

	if (!accounts || accounts.length === 0) return result;

	const now = Date.now();
	const toFlag: Array<{ id: string; username: string; postCount: number }> = [];
	const toUnflag: Array<{ id: string; username: string }> = [];

	for (const account of accounts) {
		result.totalScanned++;

		// Use `posts` table (views_count synced by analytics pipeline) instead of
		// auto_post_queue.views_at_24h (never populated — engagement_fetched_at is always null).
		const threeDaysAgo = new Date(now - 3 * 86_400_000).toISOString();
		const { data: posts } = await db()
			.from("posts")
			.select("id, views_count, published_at")
			.eq("account_id", account.id)
			.eq("status", "published")
			.gte("published_at", threeDaysAgo)
			.order("published_at", { ascending: true });

		if (!posts || posts.length < MIN_PUBLISHED_POSTS) continue;

		// Check posting duration (first post must be 3+ days ago)
		const firstPostAt = new Date(posts[0]!.published_at as string).getTime();
		const daysSinceFirstPost = (now - firstPostAt) / 86_400_000;
		if (daysSinceFirstPost < MIN_POSTING_DAYS) continue;

		// Sum all views
		const totalViews = posts.reduce(
			(sum: number, p: { views_count: number | null }) =>
				sum + ((p.views_count as number) || 0),
			0,
		);

		if (totalViews === 0 && !account.is_shadowbanned) {
			// Flag as shadowbanned
			toFlag.push({
				id: account.id,
				username: account.username,
				postCount: posts.length,
			});
		} else if (totalViews > 0 && account.is_shadowbanned) {
			// Auto-recovery: account has views now, unflag
			toUnflag.push({ id: account.id, username: account.username });
		}
	}

	// Apply flags
	if (toFlag.length > 0) {
		const flagIds = toFlag.map((a) => a.id);
		await db()
			.from("accounts")
			.update({ is_shadowbanned: true })
			.in("id", flagIds);

		result.flagged = flagIds;
		logger.warn("Shadowban scanner: flagged accounts", {
			count: toFlag.length,
			accounts: toFlag.map((a) => `@${a.username} (${a.postCount} posts)`),
		});
	}

	// Apply unflag (auto-recovery)
	if (toUnflag.length > 0) {
		const unflagIds = toUnflag.map((a) => a.id);
		await db()
			.from("accounts")
			.update({ is_shadowbanned: false })
			.in("id", unflagIds);

		result.unflagged = unflagIds;
		logger.info("Shadowban scanner: unflagged recovered accounts", {
			count: toUnflag.length,
			accounts: toUnflag.map((a) => `@${a.username}`),
		});
	}

	// Send Discord report (consolidated across all workspaces)
	if (toFlag.length > 0 || toUnflag.length > 0) {
		await sendShadowbanReport(toFlag, toUnflag, wsDiscordMap);
	}

	return result;
}

// ---------------------------------------------------------------------------
// Discord Report
// ---------------------------------------------------------------------------

async function sendShadowbanReport(
	flagged: Array<{ id: string; username: string; postCount: number }>,
	unflagged: Array<{ id: string; username: string }>,
	wsDiscordMap: Map<string, string | null>,
): Promise<void> {
	// Use first workspace's Discord URL, or fall back to global
	let webhookUrl = process.env.DISCORD_ALERT_WEBHOOK_URL;
	for (const url of wsDiscordMap.values()) {
		if (url) {
			webhookUrl = url;
			break;
		}
	}

	if (!webhookUrl) return;

	const fields: Array<{ name: string; value: string; inline?: boolean | undefined }> = [];

	if (flagged.length > 0) {
		const list = flagged
			.map((a) => `\`@${a.username}\` — ${a.postCount} posts, 0 views`)
			.join("\n");
		fields.push({
			name: `Flagged as Shadowbanned (${flagged.length})`,
			value: list.substring(0, 1024),
		});
	}

	if (unflagged.length > 0) {
		const list = unflagged
			.map((a) => `\`@${a.username}\` — views recovered`)
			.join("\n");
		fields.push({
			name: `Auto-Recovered (${unflagged.length})`,
			value: list.substring(0, 1024),
		});
	}

	fields.push({
		name: "Action Required",
		value:
			"Check flagged accounts in Adspower and re-authenticate if needed. Accounts are skipped in auto-poster rotation until unflagged.",
	});

	try {
		await fetch(webhookUrl, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				embeds: [
					{
						title: "Daily Shadowban Report",
						color: flagged.length > 0 ? 0xe74c3c : 0x2ecc71, // Red if flagged, green if only recoveries
						fields,
						timestamp: new Date().toISOString(),
						footer: { text: "Shadowban Scanner • daily-orchestrator" },
					},
				],
			}),
		});
	} catch (err) {
		logger.warn("Failed to send shadowban Discord report", {
			error: err instanceof Error ? err.message : String(err),
		});
	}
}
