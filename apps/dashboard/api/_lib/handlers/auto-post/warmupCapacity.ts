import { getSupabaseAny } from "../../supabase.js";
import { logger } from "../../logger.js";

const db = () => getSupabaseAny();

export interface WarmupCapacityState {
	status?: string | null | undefined;
	recommended_strategy_mode?: string | null | undefined;
	recommended_posts_per_day?: number | null | undefined;
	account_health_score?: number | null | undefined;
	restart_warmup_status?: string | null | undefined;
	restart_warmup_day?: number | null | undefined;
	restart_warmup_allowed_posts_per_day?: number | null | undefined;
	restart_warmup_reason?: string | null | undefined;
}

export interface EffectivePostingCap {
	cap: number | null;
	reason: string;
}

export interface CapacityQueueRow {
	id?: string | null | undefined;
	account_id?: string | null | undefined;
	status?: string | null | undefined;
	posted_at?: string | null | undefined;
	scheduled_for?: string | null | undefined;
	next_retry_at?: string | null | undefined;
	created_at?: string | null | undefined;
	metadata?: unknown;
}

function safeTimeZone(timezone?: string | null): string {
	const tz = timezone || "UTC";
	try {
		new Intl.DateTimeFormat("en-US", { timeZone: tz }).format(new Date());
		return tz;
	} catch {
		return "UTC";
	}
}

export function getDateKeyInTimezone(
	value: Date | string,
	timezone?: string | null,
): string {
	const date = value instanceof Date ? value : new Date(value);
	const parts = new Intl.DateTimeFormat("en-CA", {
		timeZone: safeTimeZone(timezone),
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
	}).formatToParts(date);
	const byType = Object.fromEntries(
		parts.map((part) => [part.type, part.value]),
	);
	return `${byType.year}-${byType.month}-${byType.day}`;
}

function plannedAccountId(metadata: unknown): string | null {
	if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
		return null;
	}
	const record = metadata as Record<string, unknown>;
	const planned = record.planned_account ?? record.plannedAccount;
	if (!planned || typeof planned !== "object" || Array.isArray(planned)) {
		return null;
	}
	const id = (planned as Record<string, unknown>).accountId;
	return typeof id === "string" && id.trim() ? id : null;
}

export function plannedAccountIdFromMetadata(metadata: unknown): string | null {
	return plannedAccountId(metadata);
}

function capacityTimestamp(row: CapacityQueueRow): string | null {
	const status = (row.status ?? "").toLowerCase();
	if (status === "published" || status === "posted") {
		return row.posted_at ?? row.scheduled_for ?? null;
	}
	if (status === "publishing") {
		return row.posted_at ?? row.scheduled_for ?? row.next_retry_at ?? null;
	}
	if (status === "queued" || status === "pending") {
		return row.next_retry_at ?? row.scheduled_for ?? null;
	}
	return null;
}

function capacityAccountId(row: CapacityQueueRow): string | null {
	return row.account_id ?? plannedAccountId(row.metadata);
}

export function capacityAccountIdForRow(row: CapacityQueueRow): string | null {
	return capacityAccountId(row);
}

function cleanupSortTimestamp(row: CapacityQueueRow): number {
	const ts =
		capacityTimestamp(row) ?? row.scheduled_for ?? row.created_at ?? row.id ?? "";
	const ms = new Date(ts).getTime();
	return Number.isFinite(ms) ? ms : Number.MAX_SAFE_INTEGER;
}

export interface WarmupCleanupAccountContext {
	timezone?: string | null | undefined;
	minIntervalMinutes?: number | null | undefined;
	state?: WarmupCapacityState | null | undefined;
}

export interface StaleWarmupReadyRowCleanupDecision {
	id: string;
	accountId: string;
	reason:
		| "stale_warmup_state_suppressed"
		| "stale_cap_zero"
		| "stale_warmup_cap_exceeded"
		| "stale_min_interval_conflict";
	cap: number;
	usedCount: number;
	localDay: string;
	timezone: string;
	minIntervalMinutes?: number | null | undefined;
	previousReadyRowId?: string | null | undefined;
	gapMinutes?: number | null | undefined;
}

export function planStaleWarmupReadyRowCleanup(input: {
	now?: Date | undefined;
	rows: CapacityQueueRow[];
	accounts: Map<string, WarmupCleanupAccountContext>;
}): {
	keptIds: string[];
	toNeedsReview: StaleWarmupReadyRowCleanupDecision[];
} {
	const keptIds: string[] = [];
	const toNeedsReview: StaleWarmupReadyRowCleanupDecision[] = [];
	const rowsByAccount = new Map<string, CapacityQueueRow[]>();

	for (const row of input.rows) {
		const accountId = capacityAccountId(row);
		if (!accountId || !input.accounts.has(accountId)) continue;
		const list = rowsByAccount.get(accountId) ?? [];
		list.push(row);
		rowsByAccount.set(accountId, list);
	}

	for (const [accountId, accountRows] of rowsByAccount) {
		const context = input.accounts.get(accountId);
		const cap = deriveEffectivePostingCap(context?.state);
		const accountToReviewIds = new Set<string>();

		const timezone = safeTimeZone(context?.timezone);
		const usedByDay = new Map<string, number>();
		const readyByDay = new Map<string, CapacityQueueRow[]>();

		if (cap.cap != null) {
			for (const row of accountRows) {
				const status = (row.status ?? "").toLowerCase();
				const ts = capacityTimestamp(row);
				if (!ts) continue;
				const localDay = getDateKeyInTimezone(ts, timezone);
				if (status === "pending" || status === "queued") {
					const list = readyByDay.get(localDay) ?? [];
					list.push(row);
					readyByDay.set(localDay, list);
					continue;
				}
				if (["published", "posted", "publishing"].includes(status)) {
					usedByDay.set(localDay, (usedByDay.get(localDay) ?? 0) + 1);
				}
			}

			for (const [localDay, readyRows] of readyByDay) {
				let used = usedByDay.get(localDay) ?? 0;
				const sorted = [...readyRows].sort((a, b) => {
					const delta = cleanupSortTimestamp(a) - cleanupSortTimestamp(b);
					if (delta !== 0) return delta;
					return String(a.id ?? "").localeCompare(String(b.id ?? ""));
				});

				for (const row of sorted) {
					if (!row.id) continue;
					if (cap.cap > 0 && used < cap.cap) {
						used++;
						keptIds.push(row.id);
						continue;
					}

					const restartStatus = context?.state?.restart_warmup_status ?? "none";
					const reason =
						restartStatus === "suppressed"
							? "stale_warmup_state_suppressed"
							: cap.cap === 0
								? "stale_cap_zero"
								: "stale_warmup_cap_exceeded";
					toNeedsReview.push({
						id: row.id,
						accountId,
						reason,
						cap: cap.cap,
						usedCount: used,
						localDay,
						timezone,
					});
					accountToReviewIds.add(row.id);
				}
			}
		}

		const minIntervalMinutes = Math.max(
			0,
			Number(context?.minIntervalMinutes ?? 0),
		);
		if (minIntervalMinutes <= 0) continue;
		const minIntervalMs = minIntervalMinutes * 60_000;
		const readyRows = accountRows
			.filter((row) => {
				if (!row.id || accountToReviewIds.has(row.id)) return false;
				const status = (row.status ?? "").toLowerCase();
				return status === "pending" || status === "queued";
			})
			.sort((a, b) => {
				const delta = cleanupSortTimestamp(a) - cleanupSortTimestamp(b);
				if (delta !== 0) return delta;
				return String(a.id ?? "").localeCompare(String(b.id ?? ""));
			});
		let previousKept: CapacityQueueRow | null = null;
		for (const row of readyRows) {
			if (!row.id) continue;
			const rowTs = capacityTimestamp(row);
			const rowMs = rowTs ? new Date(rowTs).getTime() : Number.NaN;
			if (!Number.isFinite(rowMs)) continue;
			if (!previousKept) {
				previousKept = row;
				continue;
			}
			const previousTs = capacityTimestamp(previousKept);
			const previousMs = previousTs
				? new Date(previousTs).getTime()
				: Number.NaN;
			if (!Number.isFinite(previousMs)) {
				previousKept = row;
				continue;
			}
			const gapMs = rowMs - previousMs;
			if (gapMs >= minIntervalMs) {
				previousKept = row;
				continue;
			}
			const localDay = getDateKeyInTimezone(rowTs ?? row.created_at ?? "", timezone);
			toNeedsReview.push({
				id: row.id,
				accountId,
				reason: "stale_min_interval_conflict",
				cap: cap.cap ?? -1,
				usedCount: 0,
				localDay,
				timezone,
				minIntervalMinutes,
				previousReadyRowId: previousKept.id ?? null,
				gapMinutes: Math.round((gapMs / 60_000) * 100) / 100,
			});
			accountToReviewIds.add(row.id);
		}
	}

	return { keptIds, toNeedsReview };
}

export interface WarmupCleanupStateInput extends WarmupCapacityState {
	account_id: string;
	group_id?: string | null | undefined;
	workspace_id?: string | null | undefined;
}

export async function cleanupStaleWarmupReadyRows(input: {
	workspaceId: string;
	states: WarmupCleanupStateInput[];
	now?: Date | undefined;
}): Promise<{
	checkedRows: number;
	keptRows: number;
	movedToReview: number;
	reasons: Record<string, number>;
}> {
	const accountIds = [
		...new Set(
			input.states
				.map((state) => state.account_id)
				.filter((id): id is string => typeof id === "string" && id.length > 0),
		),
	];
	if (accountIds.length === 0) {
		return { checkedRows: 0, keptRows: 0, movedToReview: 0, reasons: {} };
	}

	const accountContexts = new Map<string, WarmupCleanupAccountContext>();
	for (const state of input.states) {
		accountContexts.set(state.account_id, { state });
	}

	try {
		const { data: schedules, error } = await db()
			.from("account_schedule")
			.select("account_id, timezone, min_interval_minutes")
			.eq("workspace_id", input.workspaceId)
			.in("account_id", accountIds);
		if (error) throw error;
		for (const schedule of (schedules ?? []) as Array<{
			account_id?: string | null;
			timezone?: string | null;
			min_interval_minutes?: number | null;
		}>) {
			if (!schedule.account_id) continue;
			const existing = accountContexts.get(schedule.account_id);
			if (!existing) continue;
			accountContexts.set(schedule.account_id, {
				...existing,
				timezone: schedule.timezone ?? existing.timezone ?? null,
				minIntervalMinutes:
					schedule.min_interval_minutes ?? existing.minIntervalMinutes ?? null,
			});
		}
	} catch (error) {
		logger.warn("[warmupCapacity] Failed to load account timezones for cleanup", {
			workspaceId: input.workspaceId,
			error: error instanceof Error ? error.message : String(error),
		});
	}

	const rows = await loadCapacityRowsForAccounts({
		workspaceId: input.workspaceId,
		accountIds,
		now: input.now,
	});
	const plan = planStaleWarmupReadyRowCleanup({
		now: input.now,
		rows,
		accounts: accountContexts,
	});

	const rowsById = new Map(rows.map((row) => [row.id, row]));
	const reasons: Record<string, number> = {};
	let movedToReview = 0;

	for (const decision of plan.toNeedsReview) {
		const row = rowsById.get(decision.id);
		const metadata =
			row?.metadata && typeof row.metadata === "object" && !Array.isArray(row.metadata)
				? { ...(row.metadata as Record<string, unknown>) }
				: {};
		metadata.stale_warmup_cleanup = {
			reason: decision.reason,
			accountId: decision.accountId,
			cap: decision.cap,
			usedCount: decision.usedCount,
			localDay: decision.localDay,
			timezone: decision.timezone,
			minIntervalMinutes: decision.minIntervalMinutes ?? null,
			previousReadyRowId: decision.previousReadyRowId ?? null,
			gapMinutes: decision.gapMinutes ?? null,
			cleanedAt: (input.now ?? new Date()).toISOString(),
		};

		const { data, error } = await db()
			.from("auto_post_queue")
			.update({
				status: "needs_review",
				pool_status: "available",
				last_error: decision.reason,
				rejection_reason: decision.reason,
				metadata,
				schedule_nonce: null,
				qstash_message_id: null,
				claim_token: null,
				claim_expires_at: null,
				updated_at: new Date().toISOString(),
			})
			.eq("id", decision.id)
			.in("status", ["pending", "queued"])
			.select("id");

		if (error) {
			logger.warn("[warmupCapacity] Failed to clean stale warm-up row", {
				workspaceId: input.workspaceId,
				queueItemId: decision.id,
				accountId: decision.accountId,
				reason: decision.reason,
				error: error.message,
			});
			continue;
		}
		const updated = data?.length ?? 0;
		if (updated > 0) {
			movedToReview += updated;
			reasons[decision.reason] = (reasons[decision.reason] ?? 0) + updated;
		}
	}

	return {
		checkedRows: rows.filter((row) =>
			["pending", "queued"].includes((row.status ?? "").toLowerCase()),
		).length,
		keptRows: plan.keptIds.length,
		movedToReview,
		reasons,
	};
}

export async function cleanupPersistedStaleWarmupReadyRows(input: {
	workspaceId: string;
	now?: Date | undefined;
}): Promise<{
	checkedRows: number;
	keptRows: number;
	movedToReview: number;
	reasons: Record<string, number>;
}> {
	const { data, error } = await db()
		.from("account_autoposter_state")
		.select(
			"account_id, group_id, workspace_id, status, recommended_strategy_mode, recommended_posts_per_day, account_health_score, restart_warmup_status, restart_warmup_day, restart_warmup_allowed_posts_per_day, restart_warmup_reason",
		)
		.eq("workspace_id", input.workspaceId);

	if (error) throw error;
	return cleanupStaleWarmupReadyRows({
		workspaceId: input.workspaceId,
		states: (data ?? []) as WarmupCleanupStateInput[],
		now: input.now,
	});
}

export function deriveEffectivePostingCap(
	state?: WarmupCapacityState | null,
): EffectivePostingCap {
	const restartStatus = state?.restart_warmup_status ?? "none";
	const healthScore =
		typeof state?.account_health_score === "number"
			? state.account_health_score
			: null;
	const isProbe = state?.status === "suppressed_probe";

	if (isProbe) {
		return { cap: 1, reason: "suppressed_probe_cap" };
	}

	if (
		restartStatus === "suppressed" ||
		state?.status === "suppressed" ||
		(healthScore != null && healthScore < 40)
	) {
		return { cap: 0, reason: "suppressed_cap_zero" };
	}

	if (state?.recommended_strategy_mode === "suppress" && !isProbe) {
		return { cap: 0, reason: "performance_suppressed_cap_zero" };
	}

	const restartCap =
		typeof state?.restart_warmup_allowed_posts_per_day === "number"
			? Math.max(0, Math.floor(state.restart_warmup_allowed_posts_per_day))
			: null;
	if (restartStatus === "held") {
		return { cap: restartCap ?? 1, reason: "held_cap" };
	}
	if (restartStatus === "warming") {
		return { cap: restartCap ?? 1, reason: "warmup_cap" };
	}

	if (state?.status === "warming_limited") {
		return { cap: 1, reason: "legacy_warming_limited_cap" };
	}
	if (state?.recommended_strategy_mode === "reduce") {
		return { cap: 1, reason: "performance_reduce_cap" };
	}
	if (typeof state?.recommended_posts_per_day === "number") {
		return {
			cap: Math.max(0, Math.floor(state.recommended_posts_per_day)),
			reason: "performance_recommended_cap",
		};
	}

	return { cap: null, reason: "uncapped" };
}

export function countUsedPostingCapacityForAccount(input: {
	accountId: string;
	timezone?: string | null | undefined;
	now?: Date | undefined;
	rows: CapacityQueueRow[];
	excludeQueueItemId?: string | null | undefined;
}): number {
	const now = input.now ?? new Date();
	const today = getDateKeyInTimezone(now, input.timezone);
	let used = 0;
	for (const row of input.rows) {
		if (input.excludeQueueItemId && row.id === input.excludeQueueItemId) {
			continue;
		}
		if (capacityAccountId(row) !== input.accountId) continue;
		const status = (row.status ?? "").toLowerCase();
		if (
			!["published", "posted", "publishing", "queued", "pending"].includes(
				status,
			)
		) {
			continue;
		}
		const ts = capacityTimestamp(row);
		if (!ts) continue;
		if (getDateKeyInTimezone(ts, input.timezone) !== today) continue;
		used++;
	}
	return used;
}

export async function loadCapacityRowsForAccounts(input: {
	workspaceId: string;
	accountIds: string[];
	groupId?: string | null | undefined;
	now?: Date | undefined;
}): Promise<CapacityQueueRow[]> {
	if (input.accountIds.length === 0) return [];
	const now = input.now ?? new Date();
	const lookback = new Date(now.getTime() - 48 * 60 * 60 * 1000).toISOString();
	const lookahead = new Date(now.getTime() + 48 * 60 * 60 * 1000).toISOString();

	let query = db()
		.from("auto_post_queue")
		.select("id,account_id,status,posted_at,scheduled_for,next_retry_at,metadata")
		.eq("workspace_id", input.workspaceId)
		.eq("platform", "threads")
		.in("status", ["published", "posted", "publishing", "queued", "pending"])
		.or(
			`posted_at.gte.${lookback},scheduled_for.gte.${lookback},next_retry_at.gte.${lookback}`,
		)
		.or(
			`posted_at.lte.${lookahead},scheduled_for.lte.${lookahead},next_retry_at.lte.${lookahead}`,
		);
	if (input.groupId) query = query.eq("group_id", input.groupId);

	const { data, error } = await query;
	if (error) throw error;
	return (data ?? []) as CapacityQueueRow[];
}

export async function getRemainingPostingCapacity(input: {
	workspaceId: string;
	accountId: string;
	state?: WarmupCapacityState | null | undefined;
	timezone?: string | null | undefined;
	groupId?: string | null | undefined;
	now?: Date | undefined;
	excludeQueueItemId?: string | null | undefined;
	rows?: CapacityQueueRow[] | undefined;
}): Promise<{
	cap: number | null;
	used: number;
	remaining: number | null;
	reason: string;
}> {
	const cap = deriveEffectivePostingCap(input.state);
	const rows =
		input.rows ??
		(await loadCapacityRowsForAccounts({
			workspaceId: input.workspaceId,
			groupId: input.groupId,
			accountIds: [input.accountId],
			now: input.now,
		}));
	const used = countUsedPostingCapacityForAccount({
		accountId: input.accountId,
		timezone: input.timezone,
		now: input.now,
		rows,
		excludeQueueItemId: input.excludeQueueItemId,
	});
	return {
		cap: cap.cap,
		used,
		remaining: cap.cap == null ? null : Math.max(0, cap.cap - used),
		reason: cap.reason,
	};
}
