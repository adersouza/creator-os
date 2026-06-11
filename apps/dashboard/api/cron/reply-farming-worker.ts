/**
 * Reply Farming Worker — dedicated cron (every 30 min)
 *
 * Finds trending posts in account niches and replies from group accounts
 * to drive profile visits. Extracted from publish-worker Phase 6 to give
 * it its own time budget and prevent starvation.
 *
 * Mosseri guidance: 5:1 reply-to-post ratio drives profile visits.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = {
	maxDuration: 60,
};

const JOB_NAME = "reply-farming-worker";
const MAX_EXECUTION_TIME = 50_000; // 50s of 60s budget

function hasTimeBudget(startTime: number): boolean {
	return Date.now() - startTime < MAX_EXECUTION_TIME;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const { withCronLock, trackCronRun } = await import("../_lib/cronUtils.js");
	const { getSupabaseAny } = await import("../_lib/supabase.js");
	const { logger } = await import("../_lib/logger.js");

	const supabase = getSupabaseAny();
	const globalStart = Date.now();

	const lockResult = await withCronLock(
		supabase,
		JOB_NAME,
		async () => {
			return trackCronRun(supabase, JOB_NAME, async () => {
				const { data: enabledGroups } = await supabase
					.from("auto_post_group_config")
					.select("group_id, workspace_id")
					.eq("enabled", true)
					.eq("platform", "threads");

				const totals = { sent: 0, failed: 0, skipped: 0 };

				if (!enabledGroups || enabledGroups.length === 0) {
					return {
						itemsProcessed: 0,
						metadata: { reason: "no_enabled_groups" },
					};
				}

				const { runReplyFarming } = await import("../_lib/replyFarming.js");

				for (const gc of enabledGroups) {
					if (!hasTimeBudget(globalStart)) break;

					const { data: group } = await supabase
						.from("account_groups")
						.select("account_ids")
						.eq("id", gc.group_id)
						.maybeSingle();

					if (!group?.account_ids || group.account_ids.length === 0) continue;

					try {
						const result = await runReplyFarming(
							gc.workspace_id,
							gc.group_id,
							group.account_ids,
							3, // max replies per group per run
						);
						totals.sent += result.sent;
						totals.failed += result.failed;
						totals.skipped += result.skipped;
					} catch (err) {
						logger.warn(`[${JOB_NAME}] Failed for group`, {
							groupId: gc.group_id,
							error: err instanceof Error ? err.message : String(err),
						});
					}
				}

				logger.info(`[${JOB_NAME}] Complete`, totals);
				return { itemsProcessed: totals.sent, metadata: totals };
			});
		},
		55,
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ ok: true });
}
