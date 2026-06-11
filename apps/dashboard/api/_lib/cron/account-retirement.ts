/**
 * Account Retirement Scanner
 *
 * More aggressive than shadowban scanner — permanently removes dead accounts
 * from autoposter groups so they stop wasting posts.
 *
 * Criteria: 10+ published auto-posts AND 0 total views across ALL posts.
 *
 * Actions:
 *   1. Set accounts.is_retired = true
 *   2. Remove account ID from all account_groups.account_ids arrays
 *   3. Send Discord report listing retired accounts for replacement
 *
 * Runs weekly as Phase 2 of auto-learning cron (Sunday 6am UTC).
 * Can also be triggered manually for one-time scans.
 */

import { logger } from "../logger.js";
import { getSupabaseAny } from "../supabase.js";

const db = getSupabaseAny;

const MIN_PUBLISHED_POSTS = 10;

interface RetirementResult {
	retired: Array<{ id: string; username: string; postCount: number }>;
	totalScanned: number;
	groupsUpdated: number;
}

export async function processAccountRetirement(): Promise<RetirementResult> {
	const result: RetirementResult = {
		retired: [],
		totalScanned: 0,
		groupsUpdated: 0,
	};

	// Find all accounts with 10+ published posts and 0 total views
	const { data: candidates } = await db()
		.from("accounts")
		.select("id, username, is_retired, is_shadowbanned")
		.eq("is_retired", false)
		.not("threads_user_id", "is", null);

	if (!candidates || candidates.length === 0) return result;

	const toRetire: Array<{ id: string; username: string; postCount: number }> =
		[];

	for (const account of candidates) {
		result.totalScanned++;

		// Only count posts with confirmed metrics (engagement_fetched_at not null)
		const { data: posts } = await db()
			.from("auto_post_queue")
			.select("id, views_at_24h")
			.eq("account_id", account.id)
			.in("status", ["posted", "published"])
			.not("posted_at", "is", null)
			.not("engagement_fetched_at", "is", null);

		if (!posts || posts.length < MIN_PUBLISHED_POSTS) continue;

		const totalViews = posts.reduce(
			(sum: number, p: { views_at_24h: number | null }) =>
				sum + ((p.views_at_24h as number) || 0),
			0,
		);

		if (totalViews === 0) {
			toRetire.push({
				id: account.id,
				username: account.username,
				postCount: posts.length,
			});
		}
	}

	if (toRetire.length === 0) return result;

	const retireIds = toRetire.map((a) => a.id);

	// 1. Flag accounts as retired
	const { error: retireErr } = await db()
		.from("accounts")
		.update({ is_retired: true, is_shadowbanned: true })
		.in("id", retireIds);
	if (retireErr) {
		logger.error("[account-retirement] Failed to flag accounts as retired", {
			ids: retireIds,
			error: retireErr.message,
		});
	}

	// 2. Remove from all account_groups
	const { data: allGroups } = await db()
		.from("account_groups")
		.select("id, name, account_ids");

	const retireSet = new Set(retireIds);
	let groupsUpdated = 0;

	for (const group of allGroups || []) {
		const ids = (group.account_ids || []) as string[];
		const filtered = ids.filter((id) => !retireSet.has(id));

		if (filtered.length !== ids.length) {
			const { error: groupErr } = await db()
				.from("account_groups")
				.update({ account_ids: filtered })
				.eq("id", group.id);
			if (groupErr) {
				logger.error("[account-retirement] Failed to update account_groups", {
					groupId: group.id,
					error: groupErr.message,
				});
			}

			const removed = ids.length - filtered.length;
			logger.info("Removed retired accounts from group", {
				groupId: group.id,
				groupName: group.name,
				removed,
				remaining: filtered.length,
			});
			groupsUpdated++;
		}
	}

	result.retired = toRetire;
	result.groupsUpdated = groupsUpdated;

	logger.warn("Account retirement scan complete", {
		retired: toRetire.length,
		groupsUpdated,
		accounts: toRetire.map((a) => `@${a.username} (${a.postCount} posts)`),
	});

	// 3. Discord report
	await sendRetirementReport(toRetire);

	return result;
}

async function sendRetirementReport(
	retired: Array<{ id: string; username: string; postCount: number }>,
): Promise<void> {
	// Try workspace-specific webhook first, then global
	let webhookUrl = process.env.DISCORD_ALERT_WEBHOOK_URL;

	const { data: configs } = await db()
		.from("auto_post_config")
		.select("discord_webhook_url")
		.eq("is_enabled", true)
		.not("discord_webhook_url", "is", null)
		.limit(1);

	if (configs?.[0]?.discord_webhook_url) {
		webhookUrl = configs[0].discord_webhook_url as string;
	}

	if (!webhookUrl) return;

	const list = retired
		.map((a) => `\`@${a.username}\` — ${a.postCount} posts, 0 views`)
		.join("\n");

	try {
		await fetch(webhookUrl, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				embeds: [
					{
						title: `Account Retirement Report (${retired.length} accounts)`,
						color: 0xe74c3c,
						description:
							"These accounts have been removed from all autoposter groups. Create replacements in Adspower.",
						fields: [
							{
								name: "Retired Accounts",
								value: list.substring(0, 1024),
							},
						],
						timestamp: new Date().toISOString(),
						footer: { text: "Account Retirement Scanner • auto-learning" },
					},
				],
			}),
		});
	} catch (err) {
		logger.warn("Failed to send retirement Discord report", {
			error: err instanceof Error ? err.message : String(err),
		});
	}
}
