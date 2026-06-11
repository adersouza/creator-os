// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Phase 3: Data Retention
 * Purges stale rows from operational tables with configurable retention periods.
 */

import type {
	Logger,
	PhaseMetadata,
	PurgeResult,
	TypedSupabaseClient,
} from "./shared.js";

export async function phaseDataRetention(
	supabase: TypedSupabaseClient,
	logger: Logger,
): Promise<PhaseMetadata["dataRetention"]> {
	const results: PurgeResult[] = [];

	const cutoff90 = new Date(
		Date.now() - 90 * 24 * 60 * 60 * 1000,
	).toISOString();
	const cutoff60 = new Date(
		Date.now() - 60 * 24 * 60 * 60 * 1000,
	).toISOString();
	const cutoff30 = new Date(
		Date.now() - 30 * 24 * 60 * 60 * 1000,
	).toISOString();
	const cutoff3 = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();
	const cutoff180 = new Date(
		Date.now() - 180 * 24 * 60 * 60 * 1000,
	).toISOString();

	// 1. account_analytics — purge by date column (DATE type)
	const cutoff90Date = cutoff90.split("T")[0]!;
	const { data: aa, error: aaErr } = await supabase
		.from("account_analytics")
		.delete()
		.lt("date", cutoff90Date)
		.select("id");
	if (aaErr)
		logger.warn("[daily-maintenance] account_analytics delete error", {
			error: aaErr.message,
		});
	results.push({ table: "account_analytics", deleted: aa?.length ?? 0 });

	// 2. post_metric_history — purge by snapshot_at
	const { data: pmh, error: pmhErr } = await supabase
		.from("post_metric_history")
		.delete()
		.lt("snapshot_at", cutoff90)
		.select("id");
	if (pmhErr)
		logger.warn("[daily-maintenance] post_metric_history delete error", {
			error: pmhErr.message,
		});
	results.push({ table: "post_metric_history", deleted: pmh?.length ?? 0 });

	// 3. audience_demographics — purge by fetched_at
	const { data: ad, error: adErr } = await supabase
		.from("audience_demographics")
		.delete()
		.lt("fetched_at", cutoff90)
		.select("id");
	if (adErr)
		logger.warn("[daily-maintenance] audience_demographics delete error", {
			error: adErr.message,
		});
	results.push({ table: "audience_demographics", deleted: ad?.length ?? 0 });

	// 4. cron_runs — 30-day retention (by started_at)
	const { data: cr, error: crErr } = await supabase
		.from("cron_runs")
		.delete()
		.lt("started_at", cutoff30)
		.select("id");
	if (crErr)
		logger.warn("[daily-maintenance] cron_runs delete error", {
			error: crErr.message,
		});
	results.push({ table: "cron_runs", deleted: cr?.length ?? 0 });

	// 4b. autopilot_runs — 30-day retention, cascades to autopilot_run_steps
	try {
		// biome-ignore lint/suspicious/noExplicitAny: table is added by Phase 5 migration and may not exist on older environments
		const { data: ar, error: arErr } = await (supabase as any)
			.from("autopilot_runs")
			.delete()
			.lt("started_at", cutoff30)
			.select("id");
		if (arErr)
			logger.warn("[daily-maintenance] autopilot_runs delete error", {
				error: arErr.message,
			});
		results.push({ table: "autopilot_runs", deleted: ar?.length ?? 0 });
	} catch (arCatchErr) {
		logger.debug("[daily-maintenance] autopilot_runs table may not exist", {
			error: String(arCatchErr),
		});
	}

	// 5. cron_locks — clean up stale locks older than 24 hours
	const lockCutoff = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
	const { data: cl, error: clErr } = await supabase
		.from("cron_locks")
		.delete()
		.lt("locked_at", lockCutoff)
		.select("job_name");
	if (clErr)
		logger.warn("[daily-maintenance] cron_locks delete error", {
			error: clErr.message,
		});
	results.push({ table: "cron_locks", deleted: cl?.length ?? 0 });

	// 6. stripe_processed_events — 14-day retention (Stripe retries for up to 3 days; extra margin)
	const cutoff14d = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString();
	const { data: spe, error: speErr } = await supabase
		.from("stripe_processed_events")
		.delete()
		.lt("processed_at", cutoff14d)
		.select("event_id");
	if (speErr)
		logger.warn("[daily-maintenance] stripe_processed_events delete error", {
			error: speErr.message,
		});
	results.push({ table: "stripe_processed_events", deleted: spe?.length ?? 0 });

	// 7. threads_webhook_events — purge processed events older than 30 days
	const { data: twe, error: tweErr } = await supabase
		.from("threads_webhook_events")
		.delete()
		.eq("processed", true)
		.lt("received_at", cutoff30)
		.select("id");
	if (tweErr)
		logger.warn("[daily-maintenance] threads_webhook_events delete error", {
			error: tweErr.message,
		});
	results.push({ table: "threads_webhook_events", deleted: twe?.length ?? 0 });

	// 8. ig_webhook_events — purge processed events older than 30 days
	const { data: iwe, error: iweErr } = await supabase
		.from("ig_webhook_events")
		.delete()
		.eq("processed", true)
		.lt("received_at", cutoff30)
		.select("id");
	if (iweErr)
		logger.warn("[daily-maintenance] ig_webhook_events delete error", {
			error: iweErr.message,
		});
	results.push({ table: "ig_webhook_events", deleted: iwe?.length ?? 0 });

	// 9. webhook_deliveries — purge delivered/dead_letter entries older than 30 days
	const { data: wd, error: wdErr } = await supabase
		.from("webhook_deliveries")
		.delete()
		.in("status", ["delivered", "dead_letter"])
		.lt("created_at", cutoff30)
		.select("id");
	if (wdErr)
		logger.warn("[daily-maintenance] webhook_deliveries delete error", {
			error: wdErr.message,
		});
	results.push({ table: "webhook_deliveries", deleted: wd?.length ?? 0 });

	// 10. push_subscriptions — purge subscriptions unused for 90 days
	const { data: ps, error: psErr } = await supabase
		.from("push_subscriptions")
		.delete()
		.lt("last_used_at", cutoff90)
		.not("last_used_at", "is", null)
		.select("id");
	if (psErr)
		logger.warn("[daily-maintenance] push_subscriptions delete error", {
			error: psErr.message,
		});
	results.push({ table: "push_subscriptions", deleted: ps?.length ?? 0 });

	// 11. inspiration_ideas — archive expired pending ideas, delete archived > 90 days (#505)
	const cutoff7 = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
	const cutoff90Ideas = new Date(
		Date.now() - 90 * 24 * 60 * 60 * 1000,
	).toISOString();
	try {
		// Step 1: Archive pending ideas that have expired (past expires_at or older than 7 days)
		const { data: archived, error: archiveErr } = await supabase
			.from("inspiration_ideas")
			.update({ status: "archived" })
			.lt("generated_at", cutoff7)
			.eq("status", "pending")
			.select("id");
		if (archiveErr)
			logger.warn("[daily-maintenance] inspiration_ideas archive error", {
				error: archiveErr.message,
			});
		const archivedCount = archived?.length ?? 0;

		// Step 2: Permanently delete archived ideas older than 90 days
		const { data: ii, error: iiErr } = await supabase
			.from("inspiration_ideas")
			.delete()
			.lt("generated_at", cutoff90Ideas)
			.eq("status", "archived")
			.select("id");
		if (iiErr)
			logger.warn("[daily-maintenance] inspiration_ideas delete error", {
				error: iiErr.message,
			});
		results.push({
			table: "inspiration_ideas",
			deleted: (ii?.length ?? 0) + archivedCount,
		});
		logger.info("[daily-maintenance] inspiration_ideas lifecycle", {
			archived: archivedCount,
			permanentlyDeleted: ii?.length ?? 0,
		});
	} catch (iiCatchErr) {
		// Table may not exist — skip silently
		logger.debug("[daily-maintenance] inspiration_ideas table may not exist", {
			error: String(iiCatchErr),
		});
	}

	// 12. sync_jobs — auto-fail stuck jobs
	try {
		// Auto-fail jobs stuck in processing > 1 hour
		const processingCutoff = new Date(
			Date.now() - 60 * 60 * 1000,
		).toISOString();
		const { data: sjProc, error: sjProcErr } = await supabase
			.from("sync_jobs")
			.update({
				status: "failed",
				error_message: "Auto-failed: stuck in processing > 1 hour",
			})
			.eq("status", "processing")
			.lt("updated_at", processingCutoff)
			.select("id");
		if (sjProcErr)
			logger.warn("[daily-maintenance] sync_jobs auto-fail processing error", {
				error: sjProcErr.message,
			});
		const stuckProcessing = sjProc?.length ?? 0;

		// Auto-fail jobs stuck in queue > 6 hours
		const queueCutoff = new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString();
		const { data: sjQueued, error: sjQueuedErr } = await supabase
			.from("sync_jobs")
			.update({
				status: "failed",
				error_message: "Auto-failed: stuck in queue > 6 hours",
			})
			.eq("status", "queued")
			.lt("updated_at", queueCutoff)
			.select("id");
		if (sjQueuedErr)
			logger.warn("[daily-maintenance] sync_jobs auto-fail queued error", {
				error: sjQueuedErr.message,
			});
		const stuckQueued = sjQueued?.length ?? 0;

		logger.info("[daily-maintenance] sync_jobs auto-fail stuck jobs", {
			stuckProcessing,
			stuckQueued,
		});

		// 13. sync_jobs — 30-day retention
		const { data: sjDel, error: sjDelErr } = await supabase
			.from("sync_jobs")
			.delete()
			.in("status", ["completed", "failed"])
			.lt("created_at", cutoff30)
			.select("id");
		if (sjDelErr)
			logger.warn("[daily-maintenance] sync_jobs retention delete error", {
				error: sjDelErr.message,
			});
		const sjDeleted = sjDel?.length ?? 0;
		results.push({
			table: "sync_jobs",
			deleted: stuckProcessing + stuckQueued + sjDeleted,
		});
		logger.info("[daily-maintenance] sync_jobs 30-day retention", {
			deleted: sjDeleted,
		});
	} catch (sjCatchErr) {
		logger.warn("[daily-maintenance] sync_jobs cleanup error", {
			error: String(sjCatchErr),
		});
	}

	// 14. notifications — purge read notifications > 90 days, all notifications > 180 days
	const { data: notifRead, error: notifReadErr } = await supabase
		.from("notifications")
		.delete()
		.eq("read", true)
		.lt("created_at", cutoff90)
		.select("id");
	if (notifReadErr)
		logger.warn("[daily-maintenance] notifications (read) delete error", {
			error: notifReadErr.message,
		});
	const { data: notifOld, error: notifOldErr } = await supabase
		.from("notifications")
		.delete()
		.lt("created_at", cutoff180)
		.select("id");
	if (notifOldErr)
		logger.warn("[daily-maintenance] notifications (180d) delete error", {
			error: notifOldErr.message,
		});
	results.push({
		table: "notifications",
		deleted: (notifRead?.length ?? 0) + (notifOld?.length ?? 0),
	});

	// 15. listening_results — 90-day retention by checked_at
	const { data: lr, error: lrErr } = await supabase
		.from("listening_results")
		.delete()
		.lt("checked_at", cutoff90)
		.select("id");
	if (lrErr)
		logger.warn("[daily-maintenance] listening_results delete error", {
			error: lrErr.message,
		});
	results.push({ table: "listening_results", deleted: lr?.length ?? 0 });

	// 16. auto_post_activity — 60-day retention
	const { data: apa, error: apaErr } = await supabase
		.from("auto_post_activity")
		.delete()
		.lt("created_at", cutoff60)
		.select("id");
	if (apaErr)
		logger.warn("[daily-maintenance] auto_post_activity delete error", {
			error: apaErr.message,
		});
	results.push({ table: "auto_post_activity", deleted: apa?.length ?? 0 });

	// 17. webhook dead letters — purge old entries > 90 days from both webhook tables
	// These tables use received_at for age but have no status column — just purge by age
	// biome-ignore lint/suspicious/noExplicitAny: Supabase deep type recursion (TS2589)
	const { data: tweDl, error: tweDlErr } = await (supabase as any)
		.from("threads_webhook_events")
		.delete()
		.lt("received_at", cutoff90)
		.select("id");
	if (tweDlErr)
		logger.warn("[daily-maintenance] threads_webhook_events delete error", {
			error: tweDlErr.message,
		});
	// biome-ignore lint/suspicious/noExplicitAny: Supabase deep type recursion (TS2589)
	const { data: iweDl, error: iweDlErr } = await (supabase as any)
		.from("ig_webhook_events")
		.delete()
		.lt("received_at", cutoff90)
		.select("id");
	if (iweDlErr)
		logger.warn("[daily-maintenance] ig_webhook_events delete error", {
			error: iweDlErr.message,
		});
	results.push({
		table: "webhook_dead_letters",
		deleted: (tweDl?.length ?? 0) + (iweDl?.length ?? 0),
	});

	// 18. competitor_snapshots — 180-day retention by snapshot_date (DATE column)
	const cutoff180Date = cutoff180.split("T")[0]!;
	const { data: cs, error: csErr } = await supabase
		.from("competitor_snapshots")
		.delete()
		.lt("snapshot_date", cutoff180Date)
		.select("id");
	if (csErr)
		logger.warn("[daily-maintenance] competitor_snapshots delete error", {
			error: csErr.message,
		});
	results.push({ table: "competitor_snapshots", deleted: cs?.length ?? 0 });

	// 19. auto_post_queue — purge terminal states older than 90 days
	const { data: apq, error: apqErr } = await supabase
		.from("auto_post_queue")
		.delete()
		.in("status", ["published", "dead_letter", "cancelled", "rejected", "failed"])
		.lt("created_at", cutoff90)
		.select("id");
	if (apqErr)
		logger.warn("[daily-maintenance] auto_post_queue delete error", {
			error: apqErr.message,
		});
	results.push({ table: "auto_post_queue", deleted: apq?.length ?? 0 });

	// 20. competitor_posts — 90-day retention by created_at
	// biome-ignore lint/suspicious/noExplicitAny: legacy table is absent from current generated types in some environments
	const { data: cp, error: cpErr } = await (supabase as any)
		.from("competitor_posts")
		.delete()
		.lt("created_at", cutoff90)
		.select("id");
	if (cpErr)
		logger.warn("[daily-maintenance] competitor_posts delete error", {
			error: cpErr.message,
		});
	results.push({ table: "competitor_posts", deleted: cp?.length ?? 0 });

	// 21. posts (orphaned) — clean up posts from deleted accounts
	const { data: op, error: opErr } = await supabase
		.from("posts")
		.delete()
		.is("account_id", null)
		.lt("published_at", cutoff90)
		.select("id");
	if (opErr)
		logger.warn("[daily-maintenance] posts (orphaned) delete error", {
			error: opErr.message,
		});
	results.push({ table: "posts_orphaned", deleted: op?.length ?? 0 });

	// 22. scheduler_decisions — retain only the last 3 days of v2 scheduler logs
	try {
		// biome-ignore lint/suspicious/noExplicitAny: generated types can lag operational log tables during phased rollout
		const { data: sd, error: sdErr } = await (supabase as any)
			.from("scheduler_decisions")
			.delete()
			.lt("created_at", cutoff3)
			.select("id");
		if (sdErr)
			logger.warn("[daily-maintenance] scheduler_decisions delete error", {
				error: sdErr.message,
			});
		results.push({ table: "scheduler_decisions", deleted: sd?.length ?? 0 });
	} catch (sdCatchErr) {
		logger.debug("[daily-maintenance] scheduler_decisions table may not exist", {
			error: String(sdCatchErr),
		});
	}

	// 23. queue_fill_log — retain 7 days of explain logs
	try {
		// biome-ignore lint/suspicious/noExplicitAny: generated types can lag operational log tables during phased rollout
		const { data: qfl, error: qflErr } = await (supabase as any)
			.from("queue_fill_log")
			.delete()
			.lt("completed_at", cutoff7)
			.select("id");
		if (qflErr)
			logger.warn("[daily-maintenance] queue_fill_log delete error", {
				error: qflErr.message,
			});
		results.push({ table: "queue_fill_log", deleted: qfl?.length ?? 0 });
	} catch (qflCatchErr) {
		logger.debug("[daily-maintenance] queue_fill_log table may not exist", {
			error: String(qflCatchErr),
		});
	}

	// 24. creator_events — 180-day retention by DATE column
	try {
		// biome-ignore lint/suspicious/noExplicitAny: generated types can lag operational log tables during phased rollout
		const { data: ce, error: ceErr } = await (supabase as any)
			.from("creator_events")
			.delete()
			.lt("event_date", cutoff180Date)
			.select("id");
		if (ceErr)
			logger.warn("[daily-maintenance] creator_events delete error", {
				error: ceErr.message,
			});
		results.push({ table: "creator_events", deleted: ce?.length ?? 0 });
	} catch (ceCatchErr) {
		logger.debug("[daily-maintenance] creator_events table may not exist", {
			error: String(ceCatchErr),
		});
	}

	const totalDeleted = results.reduce((s, r) => s + r.deleted, 0);
	logger.info("[daily-maintenance] Data retention purge completed", {
		results,
		totalDeleted,
	});

	return { deleted: totalDeleted };
}
