/**
 * Auto-Reply Worker — dedicated cron (every 15 min)
 *
 * Harvests comments on auto-posted content, generates contextual AI replies,
 * and publishes them. Extracted from publish-worker Phase 5 to give it its
 * own time budget and prevent starvation from the publish pipeline.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = {
	maxDuration: 60,
};

const JOB_NAME = "auto-reply-worker";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const { withCronLock, trackCronRun } = await import("../_lib/cronUtils.js");
	const { getSupabaseAny } = await import("../_lib/supabase.js");
	const { logger, serializeError } = await import("../_lib/logger.js");

	const supabase = getSupabaseAny();

	const lockResult = await withCronLock(
		supabase,
		JOB_NAME,
		async () => {
			return trackCronRun(supabase, JOB_NAME, async () => {
				const { data: enabledConfigs } = await supabase
					.from("auto_post_config")
					.select("workspace_id")
					.eq("is_enabled", true);

				if (!enabledConfigs?.length) {
					return {
						itemsProcessed: 0,
						metadata: { reason: "no_enabled_workspace" } as Record<
							string,
							unknown
						>,
					};
				}

				let totalPublished = 0;
				const wsResults: Record<string, unknown>[] = [];

				for (const cfg of enabledConfigs) {
					// Get workspace owner — account_groups doesn't have workspace_id
					const { data: wsRow } = await supabase
						.from("workspaces")
						.select("owner_id")
						.eq("id", cfg.workspace_id)
						.maybeSingle();

					if (!wsRow?.owner_id) {
						wsResults.push({
							workspace_id: cfg.workspace_id,
							skipped: "no_owner",
						});
						continue;
					}

					try {
						const { processAutoReplyQueue } = await import(
							"../_lib/handlers/auto-post/autoReply.js"
						);
						const result = await processAutoReplyQueue(
							cfg.workspace_id,
							wsRow.owner_id,
						);
						totalPublished += result.published;
						wsResults.push({
							workspace_id: cfg.workspace_id,
							...(result as unknown as Record<string, unknown>),
						});
					} catch (err) {
						logger.error(
							`[${JOB_NAME}] Failed for workspace ${cfg.workspace_id}`,
							{ error: serializeError(err) },
						);
						wsResults.push({
							workspace_id: cfg.workspace_id,
							error: serializeError(err),
						});
					}
				}

				logger.info(`[${JOB_NAME}] Complete`, {
					totalPublished,
					workspaces: wsResults.length,
				});
				return {
					itemsProcessed: totalPublished,
					metadata: { workspaces: wsResults } as Record<string, unknown>,
				};
			});
		},
		65,
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ ok: true });
}
