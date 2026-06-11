import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = { maxDuration: 120 };

const JOB_NAME = "campaign-schedule-recovery";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const { withCronLock, trackCronRun } = await import("../_lib/cronUtils.js");
	const { getSupabaseAny } = await import("../_lib/supabase.js");
	const { logger } = await import("../_lib/logger.js");
	const supabase = getSupabaseAny();

	try {
		const lockResult = await withCronLock(supabase, JOB_NAME, async () => {
			return trackCronRun(supabase, JOB_NAME, async () => {
				const cutoff = new Date(Date.now() - 5 * 60 * 1000).toISOString();

				const { data: rows, error } = await supabase
					.from("posts")
					.select("id,user_id,scheduled_for,qstash_message_id,qstash_dispatch_status,ig_publish_attempts")
					.eq("platform", "instagram")
					.eq("status", "scheduled")
					.lt("scheduled_for", cutoff)
					.or("ig_publish_attempts.is.null,ig_publish_attempts.eq.0")
					.not("campaign_factory_asset_id", "is", null)
					.limit(100);

				if (error) {
					logger.error("[campaign-schedule-recovery] missed dispatch query failed", {
						error: error.message,
					});
					throw new Error("query_failed");
				}

				let recovered = 0;
				const skipped = 0;
				let failed = 0;
				for (const row of rows ?? []) {
					const { data: updated } = await supabase
						.from("posts")
						.update({
							status: "draft",
							scheduled_for: null,
							qstash_message_id: null,
							qstash_dispatched_at: null,
							qstash_dispatch_status: null,
							qstash_failure_reason: "overdue_dispatch_no_publish_attempt",
							updated_at: new Date().toISOString(),
						})
						.eq("id", row.id)
						.eq("status", "scheduled")
						.select("id");
					if (!updated || updated.length === 0) {
						failed++;
						continue;
					}
					recovered++;
				}

				return {
					itemsProcessed: recovered,
					metadata: {
						checked: rows?.length ?? 0,
						recovered,
						skipped,
						failed,
					},
				};
			});
		});

		if (lockResult.skipped) {
			return res.status(200).json({ skipped: true });
		}

		return res.status(200).json({
			ok: true,
			...(lockResult.result.metadata ?? {}),
		});
	} catch (error) {
		logger.error("[campaign-schedule-recovery] recovery run failed", {
			error: error instanceof Error ? error.message : String(error),
		});
		return res.status(500).json({ ok: false, error: "query_failed" });
	}
}
