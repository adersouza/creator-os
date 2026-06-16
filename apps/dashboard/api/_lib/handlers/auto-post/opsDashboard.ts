/**
 * Auto-Post Ops Dashboard
 * POST /api/auto-post?action=ops-dashboard
 *
 * Returns a comprehensive snapshot of the auto-poster system state:
 * master config, AI provider, queue counts, group status, circuit breaker,
 * recent published/rejected items, and computed stats.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import { buildAccountScheduleDriftReport } from "./accountScheduleStatusSync.js";
import { buildAccountDnaOpsSummary } from "./accountDna.js";
import { getAutoposterRejectionReason } from "./rejectionReason.js";

const db = () => getSupabaseAny();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isInActiveWindow(start: number, end: number, tz: string): boolean {
	try {
		const now = new Date();
		const formatter = new Intl.DateTimeFormat("en-US", {
			hour: "numeric",
			hour12: false,
			timeZone: tz,
		});
		const currentHour = parseInt(formatter.format(now), 10);
		if (start < end) return currentHour >= start && currentHour < end;
		return currentHour >= start || currentHour < end; // wraps midnight
	} catch {
		return false;
	}
}

function todayMidnightET(): string {
	const now = new Date();
	const formatter = new Intl.DateTimeFormat("en-US", {
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
		timeZone: "America/New_York",
	});
	const parts = formatter.formatToParts(now);
	const y = parts.find((p) => p.type === "year")?.value;
	const m = parts.find((p) => p.type === "month")?.value;
	const d = parts.find((p) => p.type === "day")?.value;
	// Return ISO timestamp for midnight ET (approximated as UTC-5 for query purposes)
	// Using the date string directly with a timezone offset
	return `${y}-${m}-${d}T05:00:00Z`;
}

function ageMinutes(iso: string | null | undefined): number | null {
	if (!iso) return null;
	const ts = new Date(iso).getTime();
	if (!Number.isFinite(ts)) return null;
	return Math.max(0, Math.round((Date.now() - ts) / 60000));
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

export default async function handleOpsDashboard(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { workspaceId } = req.body || {};
	if (!workspaceId) {
		return apiError(res, 400, "workspaceId is required");
	}

	const todayStart = todayMidnightET();

	try {
		// ── Parallel batch 1: independent queries ───────────────────────
		const [
			configResult,
			aiConfigResult,
			queueTodayResult,
			groupConfigsResult,
			publishedTodayResult,
			recentPublishedResult,
			recentRejectedResult,
			reconciliationItemsResult,
		] = await Promise.all([
			// 1. auto_post_config
			db()
				.from("auto_post_config")
				.select(
					"is_enabled, ai_generations_today, ai_daily_generation_limit, ai_last_generation_date",
				)
				.eq("workspace_id", workspaceId)
				.maybeSingle(),

			// 2. ai_config
			db()
				.from("ai_config")
				.select("provider, model")
				.eq("user_id", userId)
				.maybeSingle(),

			// 3. auto_post_queue counts today
			db()
				.from("auto_post_queue")
				.select("status")
				.eq("workspace_id", workspaceId)
				.gte("created_at", todayStart),

			// 4. group configs joined with account_groups
			db()
				.from("auto_post_group_config")
				.select(
					"group_id, enabled, active_hours_start, active_hours_end, timezone, platform",
				)
				.eq("workspace_id", workspaceId),

			// 6. posts published today
			db()
				.from("posts")
				.select("account_id, published_at")
				.eq("user_id", userId)
				.eq("status", "published")
				.gte("published_at", todayStart)
				.order("published_at", { ascending: false }),

			// 7. recent published queue items (last 20)
			db()
				.from("auto_post_queue")
				.select(
					"content, source_type, source_competitor_username, group_id, posted_at",
				)
				.eq("workspace_id", workspaceId)
				.eq("status", "published")
				.order("posted_at", { ascending: false })
				.limit(20),

			// 8. recent rejected queue items (last 10)
			db()
				.from("auto_post_queue")
				.select(
					"content, rejection_reason, last_error, source_type, group_id, created_at, metadata",
				)
				.eq("workspace_id", workspaceId)
				.eq("status", "rejected")
				.order("created_at", { ascending: false })
				.limit(10),

			// 9. externally published rows that still need local finalization
			db()
				.from("auto_post_queue")
				.select(
					"id, content, account_id, group_id, status, threads_post_id, external_published_at, finalize_error, last_error, created_at, updated_at",
				)
				.eq("workspace_id", workspaceId)
				.in("status", [
					"needs_reconciliation",
					"external_published_local_finalize_failed",
				])
				.order("external_published_at", {
					ascending: false,
					nullsFirst: false,
				})
				.limit(20),
		]);

		// ── Extract data ────────────────────────────────────────────────

		const config = configResult.data;
		const aiConfig = aiConfigResult.data;
		const queueToday = (queueTodayResult.data || []) as Array<{
			status: string;
		}>;
		const groupConfigs = (groupConfigsResult.data || []) as Array<{
			group_id: string;
			enabled: boolean;
			active_hours_start: number;
			active_hours_end: number;
			timezone: string;
			platform: string | null;
		}>;
		const publishedToday = (publishedTodayResult.data || []) as Array<{
			account_id: string;
			published_at: string;
		}>;
		const recentPublished = (recentPublishedResult.data || []) as Array<{
			content: string;
			source_type: string;
			source_competitor_username: string | null;
			group_id: string;
			posted_at: string;
		}>;
		const recentRejected = (recentRejectedResult.data || []) as Array<{
			content: string;
			rejection_reason: string | null;
			last_error?: string | null;
			source_type: string;
			group_id: string;
			created_at: string;
			metadata?: Record<string, unknown> | null;
		}>;
		const reconciliationItems = (reconciliationItemsResult.data ||
			[]) as Array<{
			id: string;
			content: string;
			account_id: string | null;
			group_id: string;
			status: string;
			threads_post_id: string | null;
			external_published_at: string | null;
			finalize_error: string | null;
			last_error: string | null;
			created_at: string;
			updated_at: string | null;
		}>;

		// ── Queue count breakdown ───────────────────────────────────────

		let totalPending = 0;
		let _postsPublishedToday = 0;
		let postsRejectedToday = 0;
		let needsReconciliationToday = 0;
		for (const item of queueToday) {
			if (item.status === "pending" || item.status === "queued") totalPending++;
			else if (item.status === "published") _postsPublishedToday++;
			else if (item.status === "rejected") postsRejectedToday++;
			else if (
				item.status === "needs_reconciliation" ||
				item.status === "external_published_local_finalize_failed"
			) {
				needsReconciliationToday++;
			}
		}

		// ── Parallel batch 2: depends on groupConfigs ───────────────────

		const groupIds = groupConfigs.map((g) => g.group_id);

		const [pendingPerGroupResult, accountGroupsResult, nextScheduledResult] =
			await Promise.all([
				// 5. pending per group
				groupIds.length > 0
					? db()
							.from("auto_post_queue")
							.select("group_id")
							.eq("workspace_id", workspaceId)
							.in("status", ["pending", "queued"])
							.in("group_id", groupIds)
					: Promise.resolve({ data: [] }),

				// account_groups for names + account_ids
				groupIds.length > 0
					? db()
							.from("account_groups")
							.select("id, name, account_ids")
							.in("id", groupIds)
					: Promise.resolve({ data: [] }),

				// next scheduled per group
				groupIds.length > 0
					? db()
							.from("auto_post_queue")
							.select("group_id, scheduled_for")
							.eq("workspace_id", workspaceId)
							.in("status", ["pending", "queued"])
							.not("scheduled_for", "is", null)
							.in("group_id", groupIds)
							.order("scheduled_for", { ascending: true })
					: Promise.resolve({ data: [] }),
			]);

		const pendingPerGroup = (pendingPerGroupResult.data || []) as Array<{
			group_id: string;
		}>;
		const accountGroups = (accountGroupsResult.data || []) as Array<{
			id: string;
			name: string;
			account_ids: string[] | null;
		}>;
		const nextScheduledItems = (nextScheduledResult.data || []) as Array<{
			group_id: string;
			scheduled_for: string;
		}>;
		// ── Build lookup maps ───────────────────────────────────────────

		const groupNameMap = new Map<string, string>();
		const groupAccountCountMap = new Map<string, number>();
		const autoposterAccountIds = new Set<string>();
		for (const g of accountGroups) {
			groupNameMap.set(g.id, g.name);
			// Use array length directly — accounts can be Threads or IG,
			// cross-referencing only the `accounts` table misses IG-only groups
			groupAccountCountMap.set(g.id, (g.account_ids || []).length);
			for (const accountId of g.account_ids || []) {
				if (accountId) autoposterAccountIds.add(accountId);
			}
		}

		const pendingCountMap = new Map<string, number>();
		for (const row of pendingPerGroup) {
			pendingCountMap.set(
				row.group_id,
				(pendingCountMap.get(row.group_id) || 0) + 1,
			);
		}

		// First scheduled_for per group (already ordered ascending)
		const nextScheduledMap = new Map<string, string>();
		for (const row of nextScheduledItems) {
			if (!nextScheduledMap.has(row.group_id)) {
				nextScheduledMap.set(row.group_id, row.scheduled_for);
			}
		}

		// ── Posts published today breakdown ──────────────────────────────

		const postsPerAccount = new Map<string, number>();
		let lastPostAt: string | null = null;
		for (const p of publishedToday) {
			postsPerAccount.set(
				p.account_id,
				(postsPerAccount.get(p.account_id) || 0) + 1,
			);
			if (!lastPostAt || p.published_at > lastPostAt) {
				lastPostAt = p.published_at;
			}
		}

		// ── Circuit breaker ─────────────────────────────────────────────

		let circuitBreaker: { tripped: boolean; hourlyCalls: number } = {
			tripped: false,
			hourlyCalls: 0,
		};
		try {
			const { getStatus } = await import("../../agentCircuitBreaker.js");
			const status = await getStatus(userId);
			circuitBreaker = {
				tripped: status.tripped,
				hourlyCalls: status.counters.hourlyCalls,
			};
		} catch {
			// Redis unavailable — report as not tripped (fail open)
		}

		// ── Build groups array ──────────────────────────────────────────

		const groups = groupConfigs.map((gc) => ({
			groupId: gc.group_id,
			name: groupNameMap.get(gc.group_id) || gc.group_id,
			enabled: gc.enabled,
			platform: gc.platform || "threads",
			activeHoursStart: gc.active_hours_start,
			activeHoursEnd: gc.active_hours_end,
			timezone: gc.timezone || "America/New_York",
			inActiveWindow: isInActiveWindow(
				gc.active_hours_start,
				gc.active_hours_end,
				gc.timezone || "America/New_York",
			),
			pendingInQueue: pendingCountMap.get(gc.group_id) || 0,
			accountCount: groupAccountCountMap.get(gc.group_id) || 0,
			nextScheduled: nextScheduledMap.get(gc.group_id) || null,
		}));

		// ── Stats from published items ──────────────────────────────────

		let avgPostLength = 0;
		const sourceCountMap: Record<string, number> = {};
		const competitorCountMap: Record<string, number> = {};
		const rejectionReasonMap: Record<string, number> = {};

		if (recentPublished.length > 0) {
			let totalChars = 0;
			for (const item of recentPublished) {
				totalChars += (item.content || "").length;
				const src = item.source_type || "unknown";
				sourceCountMap[src] = (sourceCountMap[src] || 0) + 1;
				if (item.source_competitor_username) {
					competitorCountMap[item.source_competitor_username] =
						(competitorCountMap[item.source_competitor_username] || 0) + 1;
				}
			}
			avgPostLength = Math.round(totalChars / recentPublished.length);
		}

		// Source breakdown as percentages
		const totalSourced = Object.values(sourceCountMap).reduce(
			(a, b) => a + b,
			0,
		);
		const sourceBreakdown: Record<string, number> = {};
		for (const [src, count] of Object.entries(sourceCountMap)) {
			sourceBreakdown[src] =
				totalSourced > 0 ? Math.round((count / totalSourced) * 100) : 0;
		}

		// Rejection stats
		for (const item of recentRejected) {
			const reason = getAutoposterRejectionReason(item);
			rejectionReasonMap[reason] = (rejectionReasonMap[reason] || 0) + 1;
		}

		const totalPublishedAndRejected =
			recentPublished.length + recentRejected.length;
		const rejectionRate =
			totalPublishedAndRejected > 0
				? Math.round((recentRejected.length / totalPublishedAndRejected) * 100)
				: 0;

		// Top rejection reason
		let topRejectionReason: string | null = null;
		let topRejectionCount = 0;
		for (const [reason, count] of Object.entries(rejectionReasonMap)) {
			if (count > topRejectionCount) {
				topRejectionCount = count;
				topRejectionReason = reason;
			}
		}

		// Top competitor source
		let topCompetitorSource: string | null = null;
		let topCompetitorCount = 0;
		for (const [username, count] of Object.entries(competitorCountMap)) {
			if (count > topCompetitorCount) {
				topCompetitorCount = count;
				topCompetitorSource = username;
			}
		}

		// ── Account State breakdown ─────────────────────────────────────

			const accountStateBreakdown: Record<string, number> = {};
			let accountScheduleDrift = {
				checked: 0,
				mismatches: 0,
				repaired: 0,
				skippedPaused: 0,
				remainingBlocked: 0,
				dryRun: true,
				rows: [] as Array<{
					account_id: string;
					group_id: string;
					username: string | null;
					currentStatus: string | null;
					desiredStatus: string;
					reason: string;
					manuallyPaused: boolean;
					scheduleBlocksPlanner: boolean;
					wouldRepair: boolean;
				}>,
			};
			const nonActiveAccounts: Array<{
			account_id: string;
			username: string;
			status: string;
			status_label: string;
			status_reason: string | null;
			blocked_until: string | null;
			avg_views_14d: number | null;
			account_health_score: number | null;
			account_health_reason: string | null;
			last_health_recomputed_at: string | null;
		}> = [];
		const accountHealth: Array<{
			account_id: string;
			username: string;
			status: string;
			status_label: string;
			score: number | null;
			reason: string | null;
			last_recomputed_at: string | null;
			restart_warmup_status: string | null;
			restart_warmup_day: number | null;
			restart_warmup_allowed_posts_per_day: number | null;
			restart_warmup_reason: string | null;
			restart_warmup_next_ramp_at: string | null;
			restart_warmup_last_post_views: number | null;
			restart_warmup_last_evaluated_at: string | null;
			recommended_strategy_mode: string | null;
			learned_timing: {
				best_hours: Array<{
					hour: number;
					confidence: number;
					sample_size: number;
					weighted_score: number;
				}>;
				confidence: number | null;
				sample_size: number;
				fallback_reason: string | null;
				next_scheduled_timing_reason: string | null;
				warmup_primary_fallback: boolean;
			} | null;
		}> = [];

		try {
			const { getWorkspaceAccountStates, statusLabel: getStatusLabel } =
				await import("./accountState.js");
			const allStates = await getWorkspaceAccountStates(workspaceId);

			// Get usernames
			const stateAccountIds = allStates.map((s) => s.account_id);
				const { data: stateAccounts } =
					stateAccountIds.length > 0
						? await db()
								.from("accounts")
								.select(
									"id, username, is_active, is_retired, needs_reauth, is_shadowbanned, status",
								)
								.in("id", stateAccountIds)
						: { data: [] };
				const stateUsernameMap = new Map<string, string>();
			if (stateAccounts) {
				for (const a of stateAccounts as Array<{
					id: string;
					username: string;
				}>) {
					stateUsernameMap.set(a.id, a.username);
					}
				}
				const { data: scheduleRows } =
					stateAccountIds.length > 0
						? await db()
								.from("account_schedule")
								.select(
									"account_id, group_id, status, status_reason, blocked_until, paused",
								)
								.eq("workspace_id", workspaceId)
								.in("account_id", stateAccountIds)
						: { data: [] };
				accountScheduleDrift = buildAccountScheduleDriftReport({
					states: allStates,
					accounts: stateAccounts ?? [],
					schedules: scheduleRows ?? [],
					dryRun: true,
				});

				for (const s of allStates) {
				accountStateBreakdown[s.status] =
					(accountStateBreakdown[s.status] ?? 0) + 1;
				accountHealth.push({
					account_id: s.account_id,
					username: stateUsernameMap.get(s.account_id) ?? "unknown",
					status: s.status,
					status_label: getStatusLabel(s.status),
					score: s.account_health_score ?? null,
					reason: s.account_health_reason ?? null,
					last_recomputed_at: s.last_health_recomputed_at ?? null,
					restart_warmup_status: s.restart_warmup_status ?? null,
					restart_warmup_day: s.restart_warmup_day ?? null,
					restart_warmup_allowed_posts_per_day:
						s.restart_warmup_allowed_posts_per_day ?? null,
					restart_warmup_reason: s.restart_warmup_reason ?? null,
					restart_warmup_next_ramp_at:
						s.restart_warmup_next_ramp_at ?? null,
					restart_warmup_last_post_views:
						s.restart_warmup_last_post_views ?? null,
					restart_warmup_last_evaluated_at:
						s.restart_warmup_last_evaluated_at ?? null,
					recommended_strategy_mode: s.recommended_strategy_mode ?? null,
					learned_timing: null,
				});
				if (s.status !== "active") {
					nonActiveAccounts.push({
						account_id: s.account_id,
						username: stateUsernameMap.get(s.account_id) ?? "unknown",
						status: s.status,
						status_label: getStatusLabel(s.status),
						status_reason: s.status_reason,
						blocked_until: s.blocked_until,
						avg_views_14d: s.last_14d_avg_views,
						account_health_score: s.account_health_score ?? null,
						account_health_reason: s.account_health_reason ?? null,
						last_health_recomputed_at: s.last_health_recomputed_at ?? null,
					});
				}
			}
			accountHealth.sort((a, b) => {
				const scoreDelta = (a.score ?? 100) - (b.score ?? 100);
				return scoreDelta !== 0
					? scoreDelta
					: a.username.localeCompare(b.username);
			});
			// Sort non-active: suppressed first, then by username
			nonActiveAccounts.sort((a, b) => {
				const priority: Record<string, number> = {
					suppressed: 0,
					inactive: 1,
					view_cooldown: 2,
					viral_suppress: 3,
					flop_delay: 4,
					shadowban_throttle: 5,
					suppressed_probe: 6,
					warming_silent: 7,
					warming_limited: 8,
				};
				const pa = priority[a.status] ?? 9;
				const pb = priority[b.status] ?? 9;
				return pa !== pb ? pa - pb : a.username.localeCompare(b.username);
			});
		} catch {
			// State table may not be populated yet — non-critical
		}

		try {
			const accountIds = accountHealth.map((account) => account.account_id);
			if (accountIds.length > 0) {
				const [timingRowsResult, nextAccountScheduledResult] = await Promise.all([
					db()
						.from("autoposter_account_hour_performance")
						.select(
							"account_id, hour, posts_count, effective_sample_size, weighted_score, confidence, fallback_source",
						)
						.eq("workspace_id", workspaceId)
						.eq("platform", "threads")
						.in("account_id", accountIds)
						.order("weighted_score", { ascending: false }),

					db()
						.from("auto_post_queue")
						.select("account_id, scheduled_for, metadata")
						.eq("workspace_id", workspaceId)
						.eq("platform", "threads")
						.in("status", ["pending", "queued"])
						.in("account_id", accountIds)
						.not("scheduled_for", "is", null)
						.order("scheduled_for", { ascending: true })
						.limit(Math.max(50, accountIds.length * 3)),
				]);

				const timingByAccount = new Map<
					string,
					Array<{
						hour: number;
						confidence: number;
						sample_size: number;
						weighted_score: number;
						fallback_source: string | null;
					}>
				>();
				for (const row of (timingRowsResult.data || []) as Array<
					Record<string, unknown>
				>) {
					const accountId = String(row.account_id ?? "");
					if (!accountId) continue;
					const list = timingByAccount.get(accountId) ?? [];
					if (list.length < 5) {
						list.push({
							hour: Number(row.hour ?? 0),
							confidence: Number(row.confidence ?? 0),
							sample_size: Number(row.posts_count ?? 0),
							weighted_score: Number(row.weighted_score ?? 0),
							fallback_source:
								typeof row.fallback_source === "string"
									? row.fallback_source
									: null,
						});
					}
					timingByAccount.set(accountId, list);
				}
				const nextTimingReasonByAccount = new Map<string, string | null>();
				for (const row of (nextAccountScheduledResult.data || []) as Array<{
					account_id?: string | null;
					metadata?: Record<string, unknown> | null;
				}>) {
					if (!row.account_id || nextTimingReasonByAccount.has(row.account_id)) {
						continue;
					}
					const timing = row.metadata?.timing as
						| { timingReason?: unknown }
						| null
						| undefined;
					nextTimingReasonByAccount.set(
						row.account_id,
						typeof timing?.timingReason === "string" ? timing.timingReason : null,
					);
				}
				for (const account of accountHealth) {
					const rows = timingByAccount.get(account.account_id) ?? [];
					const sampleSize = rows.reduce(
						(sum, row) => sum + (Number.isFinite(row.sample_size) ? row.sample_size : 0),
						0,
					);
					const confidence =
						rows.length > 0
							? Math.max(...rows.map((row) => row.confidence || 0))
							: null;
					const fallbackReason =
						rows.find((row) => row.fallback_source)?.fallback_source ??
						"global_fallback";
					const nextReason =
						nextTimingReasonByAccount.get(account.account_id) ?? null;
					account.learned_timing = {
						best_hours: rows.slice(0, 3).map((row) => ({
							hour: row.hour,
							confidence: row.confidence,
							sample_size: row.sample_size,
							weighted_score: row.weighted_score,
						})),
						confidence,
						sample_size: sampleSize,
						fallback_reason: fallbackReason,
						next_scheduled_timing_reason: nextReason,
						warmup_primary_fallback:
							nextReason === "warmup_primary_hour" ||
							(account.restart_warmup_status === "warming" &&
								(fallbackReason === "account_sparse" ||
									fallbackReason === "global_fallback")),
					};
				}
			}
		} catch (timingError) {
			logger.warn("Ops dashboard learned timing unavailable", {
				error: String(timingError),
				workspaceId,
			});
		}

		// ── Account DNA coverage + review visibility ───────────────────

		let accountDna = buildAccountDnaOpsSummary({
			accountIds: [...autoposterAccountIds],
			profiles: [],
			metrics: [],
			reviewItems: [],
		});

		try {
			const accountIds = [...autoposterAccountIds];
			const [dnaProfilesResult, dnaMetricsResult, dnaReviewItemsResult] =
				await Promise.all([
					accountIds.length > 0
						? db()
								.from("account_dna")
								.select(
									"id, account_id, group_id, version, status, confidence, archetype, sub_archetype, follower_promise, signature_phrases, primary_topics, taboo_topics, emotional_baseline, updated_at, created_at",
								)
								.eq("workspace_id", workspaceId)
								.in("account_id", accountIds)
								.order("status", { ascending: true })
								.order("version", { ascending: false })
						: Promise.resolve({ data: [] }),

					accountIds.length > 0
						? db()
								.from("account_uniqueness_metrics")
								.select(
									"account_id, uniqueness_score, sibling_collision_score, genericness_score, drift_score, decision, reason, computed_at",
								)
								.eq("workspace_id", workspaceId)
								.in("account_id", accountIds)
								.order("computed_at", { ascending: false })
								.limit(Math.max(accountIds.length * 3, 30))
						: Promise.resolve({ data: [] }),

					db()
						.from("auto_post_queue")
						.select(
							"id, account_id, group_id, content, dna_fit_score, uniqueness_score, sibling_collision_score, genericness_score, dna_decision, dna_reasons, created_at",
						)
						.eq("workspace_id", workspaceId)
						.eq("status", "needs_review")
						.not("dna_decision", "is", null)
						.order("created_at", { ascending: false })
						.limit(20),
				]);

			const latestMetricByAccount = new Map<string, Record<string, unknown>>();
			for (const metric of (dnaMetricsResult.data || []) as Array<
				Record<string, unknown>
			>) {
				const accountId = String(metric.account_id ?? "");
				if (accountId && !latestMetricByAccount.has(accountId)) {
					latestMetricByAccount.set(accountId, metric);
				}
			}
			accountDna = buildAccountDnaOpsSummary({
				accountIds,
				profiles: (dnaProfilesResult.data || []) as Array<
					Record<string, unknown>
				>,
				metrics: [...latestMetricByAccount.values()],
				reviewItems: (dnaReviewItemsResult.data || []) as Array<
					Record<string, unknown>
				>,
			});
		} catch (dnaError) {
			logger.warn("Ops dashboard account DNA unavailable", {
				error: String(dnaError),
				workspaceId,
			});
		}

		// ── Last fill result per group ──────────────────────────────────

		const lastFillPerGroup: Array<{
			group_id: string;
			group_name: string;
			posts_inserted: number;
			posts_generated: number;
			posts_rejected: number;
			early_exit_reason: string | null;
			completed_at: string;
			duration_ms: number | null;
		}> = [];

		try {
			if (groupIds.length > 0) {
				const { data: fillLogs } = await db()
					.from("queue_fill_log")
					.select(
						"group_id, posts_inserted, posts_generated, posts_rejected, early_exit_reason, completed_at, duration_ms",
					)
					.eq("workspace_id", workspaceId)
					.in("group_id", groupIds)
					.order("completed_at", { ascending: false })
					.limit(100);

				if (fillLogs) {
					// Keep only the latest per group
					const seen = new Set<string>();
					for (const f of fillLogs as Array<Record<string, unknown>>) {
						const gid = f.group_id as string;
						if (seen.has(gid)) continue;
						seen.add(gid);
						lastFillPerGroup.push({
							group_id: gid,
							group_name: groupNameMap.get(gid) || gid,
							posts_inserted: f.posts_inserted as number,
							posts_generated: f.posts_generated as number,
							posts_rejected: f.posts_rejected as number,
							early_exit_reason: f.early_exit_reason as string | null,
							completed_at: f.completed_at as string,
							duration_ms: f.duration_ms as number | null,
						});
					}
				}
			}
		} catch {
			// queue_fill_log may not exist yet — non-critical
		}

		// ── Threads scheduling human-likeness visibility ────────────────

		const schedulingSafety = {
			missingTimingMetadata: 0,
			missingWarmupMetadata: 0,
			sameMinuteReadyCollisions: 0,
			poolRowsMissingPlannedAccount: 0,
			nextScheduled: [] as Array<{
				id: string;
				group_id: string | null;
				group_name: string;
				status: string;
				account_id: string | null;
				planned_account_id: string | null;
				scheduled_for: string | null;
				timing_reason: string | null;
				account_window: { start: number | null; end: number | null } | null;
				timezone: string | null;
				warmup_status: string | null;
				warmup_day: number | null;
				has_timing_metadata: boolean;
				has_warmup_metadata: boolean;
				has_planned_account_constraints: boolean;
			}>,
		};
		try {
			const { data: scheduledRows } = await db()
				.from("auto_post_queue")
				.select("id, group_id, status, account_id, scheduled_for, metadata")
				.eq("workspace_id", workspaceId)
				.eq("platform", "threads")
				.in("status", ["pending", "queued"])
				.not("scheduled_for", "is", null)
				.order("scheduled_for", { ascending: true })
				.limit(1000);
			const rows = (scheduledRows || []) as Array<{
				id: string;
				group_id: string | null;
				status: string;
				account_id: string | null;
				scheduled_for: string | null;
				metadata: Record<string, unknown> | null;
			}>;
			const minuteCounts = new Map<string, number>();
			for (const row of rows) {
				const metadata = row.metadata ?? {};
				const timing = metadata.timing as Record<string, unknown> | undefined;
				const planned = metadata.planned_account as
					| Record<string, unknown>
					| undefined;
				const warmup = metadata.restart_warmup as
					| Record<string, unknown>
					| undefined;
				if (!timing?.reason && !timing?.timingReason) {
					schedulingSafety.missingTimingMetadata++;
				}
				const warmupExpected =
					timing?.warmupApplied === true || planned?.warmupCap != null;
				if (warmupExpected && !warmup) {
					schedulingSafety.missingWarmupMetadata++;
				}
				if (!row.account_id && !planned?.accountId) {
					schedulingSafety.poolRowsMissingPlannedAccount++;
				}
				if (row.scheduled_for) {
					const minuteKey = new Date(row.scheduled_for).toISOString().slice(0, 16);
					minuteCounts.set(minuteKey, (minuteCounts.get(minuteKey) ?? 0) + 1);
				}
			}
			schedulingSafety.sameMinuteReadyCollisions = [...minuteCounts.values()].filter(
				(count) => count > 1,
			).length;
			schedulingSafety.nextScheduled = rows.slice(0, 20).map((row) => {
				const metadata = row.metadata ?? {};
				const timing = metadata.timing as Record<string, unknown> | undefined;
				const planned = metadata.planned_account as
					| Record<string, unknown>
					| undefined;
				const warmup = metadata.restart_warmup as
					| Record<string, unknown>
					| undefined;
				const accountWindow =
					(timing?.accountWindow as Record<string, unknown> | undefined) ??
					(planned?.accountWindow as Record<string, unknown> | undefined);
				return {
					id: row.id,
					group_id: row.group_id,
					group_name: row.group_id ? groupNameMap.get(row.group_id) || row.group_id : "",
					status: row.status,
					account_id: row.account_id,
					planned_account_id:
						typeof planned?.accountId === "string" ? planned.accountId : null,
					scheduled_for: row.scheduled_for,
					timing_reason:
						typeof timing?.reason === "string"
							? timing.reason
							: typeof timing?.timingReason === "string"
								? timing.timingReason
								: null,
					account_window: accountWindow
						? {
								start:
									typeof accountWindow.start === "number"
										? accountWindow.start
										: null,
								end:
									typeof accountWindow.end === "number" ? accountWindow.end : null,
							}
						: null,
					timezone: typeof timing?.timezone === "string" ? timing.timezone : null,
					warmup_status:
						typeof warmup?.status === "string" ? warmup.status : null,
					warmup_day: typeof warmup?.day === "number" ? warmup.day : null,
					has_timing_metadata: Boolean(timing?.reason || timing?.timingReason),
					has_warmup_metadata: Boolean(warmup),
					has_planned_account_constraints: Boolean(planned?.accountId),
				};
			});
		} catch (scheduleSafetyError) {
			logger.warn("Ops dashboard scheduling safety unavailable", {
				error: String(scheduleSafetyError),
				workspaceId,
			});
		}

		// ── Operational SLOs + doctor alerts ────────────────────────────

		let doctorAlerts: Array<{
			check_name: string;
			severity: string;
			message: string;
			details: Record<string, unknown> | null;
			created_at: string;
		}> = [];
		let sloMetrics = {
			reconciliationBacklog: 0,
			oldestReconciliationAgeMinutes: null as number | null,
			publishSuccessRate24h: null as number | null,
			deadLetterRate24h: null as number | null,
			claimFailureRate24h: null as number | null,
			doctorIssueCount: 0,
		};

		try {
			const since24h = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
			const [
				doctorAlertsResult,
				doctorIssueCountResult,
				reconciliationBacklogResult,
				oldestReconciliationResult,
				publishAttemptsResult,
			] = await Promise.all([
				db()
					.from("watchdog_alerts")
					.select("check_name, severity, message, details, created_at")
					.eq("workspace_id", workspaceId)
					.is("resolved_at", null)
					.like("check_name", "autoposter-doctor:%")
					.order("created_at", { ascending: false })
					.limit(20),

				db()
					.from("watchdog_alerts")
					.select("id", { count: "exact", head: true })
					.eq("workspace_id", workspaceId)
					.is("resolved_at", null)
					.like("check_name", "autoposter-doctor:%"),

				db()
					.from("auto_post_queue")
					.select("id", { count: "exact", head: true })
					.eq("workspace_id", workspaceId)
					.in("status", [
						"needs_reconciliation",
						"external_published_local_finalize_failed",
					]),

				db()
					.from("auto_post_queue")
					.select("external_published_at, created_at")
					.eq("workspace_id", workspaceId)
					.in("status", [
						"needs_reconciliation",
						"external_published_local_finalize_failed",
					])
					.order("external_published_at", {
						ascending: true,
						nullsFirst: false,
					})
					.limit(1),

				db()
					.from("publish_attempts")
					.select("result, started_at")
					.eq("workspace_id", workspaceId)
					.gte("started_at", since24h)
					.limit(1000),
			]);

			doctorAlerts = (doctorAlertsResult.data || []) as typeof doctorAlerts;

			const attempts = (publishAttemptsResult.data || []) as Array<{
				result: string;
				started_at: string;
			}>;
			const terminalAttempts = attempts.filter(
				(a) => a.result && a.result !== "started",
			);
			const denominator = terminalAttempts.length;
			const countResult = (result: string) =>
				terminalAttempts.filter((a) => a.result === result).length;
			const rate = (count: number) =>
				denominator > 0 ? Math.round((count / denominator) * 100) : null;

			const oldestRow = (
				(oldestReconciliationResult.data || []) as Array<{
					external_published_at: string | null;
					created_at: string | null;
				}>
			)[0];
			sloMetrics = {
				reconciliationBacklog: reconciliationBacklogResult.count ?? 0,
				oldestReconciliationAgeMinutes: ageMinutes(
					oldestRow?.external_published_at ?? oldestRow?.created_at,
				),
				publishSuccessRate24h: rate(countResult("published")),
				deadLetterRate24h: rate(countResult("dead_letter")),
				claimFailureRate24h: rate(countResult("claim_failed")),
				doctorIssueCount: doctorIssueCountResult.count ?? doctorAlerts.length,
			};
		} catch (sloError) {
			logger.warn("Ops dashboard SLO metrics unavailable", {
				error: String(sloError),
				workspaceId,
			});
		}

		// ── Response ────────────────────────────────────────────────────

		return apiSuccess(res, {
			masterSwitch: config?.is_enabled ?? false,
			aiProvider: aiConfig?.provider || null,
			aiModel: aiConfig?.model || null,
			genToday: config?.ai_generations_today ?? 0,
			genLimit: config?.ai_daily_generation_limit ?? 0,
			totalPending,
			postsPublishedToday: publishedToday.length,
			postsRejectedToday,
			needsReconciliationToday,
			lastPostAt,
			circuitBreaker,
			groups,
			recentPublished,
			recentRejected,
			reconciliationItems,
			doctorAlerts,
			sloMetrics,
			stats: {
				avgPostLength,
				sourceBreakdown,
				rejectionRate,
				topRejectionReason,
				topCompetitorSource,
			},
				accountStates: {
					breakdown: accountStateBreakdown,
					nonActive: nonActiveAccounts,
					health: accountHealth.slice(0, 50),
					scheduleDrift: {
						checked: accountScheduleDrift.checked,
						mismatches: accountScheduleDrift.mismatches,
						skippedPaused: accountScheduleDrift.skippedPaused,
						remainingBlocked: accountScheduleDrift.remainingBlocked,
						rows: accountScheduleDrift.rows.slice(0, 50),
					},
					total: Object.values(accountStateBreakdown).reduce((a, b) => a + b, 0),
				},
			accountDna,
			lastFillPerGroup,
			schedulingSafety,
		});
	} catch (error: unknown) {
		logger.error("Ops dashboard error", { error: String(error) });
		return apiError(res, 500, "Failed to build ops dashboard");
	}
}
