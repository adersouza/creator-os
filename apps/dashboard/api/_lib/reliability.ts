import { logger } from "./logger.js";
import { classifyWebhookError, isDefinitiveOAuthError, isRetryableMetaError } from "./retryUtils.js";
import type { getSupabaseAny } from "./supabase.js";

export type ReliabilityTone = "healthy" | "warning" | "critical";

type Db = ReturnType<typeof getSupabaseAny>;

export type SchedulingSloSummary = {
	generatedAt: string;
	windowHours: number;
	scheduledTotal: number;
	publishedTotal: number;
	failedTotal: number;
	onTime60s: number;
	lateOver5m: number;
	successRate: number;
	onTimeRate: number;
	driftSeconds: {
		p50: number;
		p95: number;
		p99: number;
		max: number;
		avg: number;
	};
	qstashFailures: number;
	dlqCount: number;
	backlogCount: number;
	impactedAccountIds: string[];
	tone: ReliabilityTone;
	issues: Array<{
		key: string;
		title: string;
		severity: "warning" | "critical";
		route: string;
	}>;
	trend: Array<Record<string, unknown>>;
};

export type MetaApiUsageSnapshot = {
	status?: number | null;
	appUsage?: Record<string, number> | null;
	businessUsage?: Record<string, number> | null;
	retryAfterSeconds?: number | null;
	usagePercent?: number | null;
	tone: ReliabilityTone;
};

export type MetaApiUsageSummary = {
	generatedAt: string;
	tone: ReliabilityTone;
	latest: Array<Record<string, unknown>>;
	maxUsagePercent: number;
	retryAfterActiveCount: number;
	warningCount: number;
	criticalCount: number;
};

export type WebhookHealthSummary = {
	generatedAt: string;
	tone: ReliabilityTone;
	failedDeliveries: number;
	deadLetterDeliveries: number;
	threadsDeadLetters: number;
	instagramDeadLetters: number;
	nextRetryCount: number;
	issues: Array<Record<string, unknown>>;
};

export type TokenSloSummary = {
	generatedAt: string;
	tone: ReliabilityTone;
	totalIssues: number;
	needsReauth: number;
	expiringSoon: number;
	expired: number;
	accounts: Array<Record<string, unknown>>;
};

export type ReliabilitySections = {
	reliabilitySlo: SchedulingSloSummary;
	metaApiUsage: MetaApiUsageSummary;
	webhookHealth: WebhookHealthSummary;
	tokenSlo: TokenSloSummary;
};

export function calculateSchedulingSlo(
	postRows: Array<Record<string, unknown>>,
	queueRows: Array<Record<string, unknown>> = [],
	windowHours = 24,
	trend: Array<Record<string, unknown>> = [],
): SchedulingSloSummary {
	const now = new Date().toISOString();
	const scheduledRows = postRows.filter((row) => stringOrNull(row.scheduled_for));
	const publishedRows = scheduledRows.filter((row) => row.status === "published" && stringOrNull(row.published_at));
	const failedRows = scheduledRows.filter((row) => row.status === "failed");
	const drifts = publishedRows
		.map((row) => {
			const scheduled = Date.parse(String(row.scheduled_for));
			const published = Date.parse(String(row.published_at));
			if (!Number.isFinite(scheduled) || !Number.isFinite(published)) return null;
			return Math.max(0, Math.round((published - scheduled) / 1000));
		})
		.filter((value): value is number => typeof value === "number");
	const onTime60s = drifts.filter((value) => value <= 60).length;
	const lateOver5m = drifts.filter((value) => value > 300).length;
	const scheduledTotal = scheduledRows.length;
	const publishedTotal = publishedRows.length;
	const failedTotal = failedRows.length;
	const successRate = scheduledTotal > 0 ? roundPct(publishedTotal / scheduledTotal) : 100;
	const onTimeRate = publishedTotal > 0 ? roundPct(onTime60s / publishedTotal) : 100;
	const qstashFailures = queueRows.filter((row) => row.status === "dead_letter" || row.dead_letter === true).length;
	const backlogCount = queueRows.filter((row) => ["pending", "queued", "retrying", "processing"].includes(String(row.status))).length;
	const impactedAccountIds = Array.from(new Set(
		[...failedRows, ...queueRows]
			.map((row) => stringOrNull(row.account_id ?? row.instagram_account_id))
			.filter((value): value is string => Boolean(value)),
	));
	const issues: SchedulingSloSummary["issues"] = [];
	if (failedTotal > 0) {
		issues.push({ key: "failed_posts", title: `${failedTotal} scheduled posts failed`, severity: "critical", route: "/calendar?status=failed" });
	}
	if (lateOver5m > 0) {
		issues.push({ key: "publish_drift", title: `${lateOver5m} posts drifted over 5 minutes`, severity: lateOver5m > 3 ? "critical" : "warning", route: "/calendar?status=published" });
	}
	if (qstashFailures > 0) {
		issues.push({ key: "qstash_dlq", title: `${qstashFailures} queue items are dead-lettered`, severity: "critical", route: "/admin/dead-letters" });
	}
	if (backlogCount > 20) {
		issues.push({ key: "queue_backlog", title: `${backlogCount} due queue items need dispatch`, severity: "warning", route: "/calendar?status=queued" });
	}
	const critical = issues.some((issue) => issue.severity === "critical");
	return {
		generatedAt: now,
		windowHours,
		scheduledTotal,
		publishedTotal,
		failedTotal,
		onTime60s,
		lateOver5m,
		successRate,
		onTimeRate,
		driftSeconds: {
			p50: percentile(drifts, 50),
			p95: percentile(drifts, 95),
			p99: percentile(drifts, 99),
			max: drifts.length ? Math.max(...drifts) : 0,
			avg: drifts.length ? Math.round(drifts.reduce((sum, value) => sum + value, 0) / drifts.length) : 0,
		},
		qstashFailures,
		dlqCount: qstashFailures,
		backlogCount,
		impactedAccountIds,
		tone: critical ? "critical" : issues.length > 0 || onTimeRate < 99.9 ? "warning" : "healthy",
		issues,
		trend,
	};
}

export function parseMetaApiUsageHeaders(response: Response | Headers | Record<string, unknown>): MetaApiUsageSnapshot {
	const headers = response instanceof Response ? response.headers : response instanceof Headers ? response : null;
	const get = (name: string): string | null => {
		if (headers) return headers.get(name) ?? headers.get(name.toLowerCase());
		const direct = (response as Record<string, unknown>)[name] ?? (response as Record<string, unknown>)[name.toLowerCase()];
		return typeof direct === "string" ? direct : null;
	};
	const appUsage = parseUsageHeader(get("X-App-Usage"));
	const businessUsage = parseBusinessUsageHeader(get("X-Business-Use-Case-Usage"));
	const retryAfterSeconds = parseRetryAfterSeconds(get("Retry-After"));
	const usagePercent = Math.max(
		0,
		...Object.values(appUsage || {}),
		...Object.values(businessUsage || {}),
	);
	const tone: ReliabilityTone = retryAfterSeconds || usagePercent >= 95 ? "critical" : usagePercent >= 80 ? "warning" : "healthy";
	return {
		status: response instanceof Response ? response.status : null,
		appUsage,
		businessUsage,
		retryAfterSeconds,
		usagePercent,
		tone,
	};
}

export function classifyReliabilityRetry(input: {
	status?: number | null;
	error?: unknown;
	retryAfterSeconds?: number | null;
}): {
	classification: "transient_retry" | "rate_limit_retry" | "definitive_auth_failure" | "permanent_failure" | "manual_recovery";
	retryable: boolean;
	route: "/accounts?status=flagged" | "/admin/dead-letters" | "/settings?tab=ops";
} {
	const message = input.error instanceof Error ? input.error.message : String(input.error ?? "");
	if (input.retryAfterSeconds || input.status === 429) {
		return { classification: "rate_limit_retry", retryable: true, route: "/settings?tab=ops" };
	}
	if (message && isDefinitiveOAuthError(message)) {
		return { classification: "definitive_auth_failure", retryable: false, route: "/accounts?status=flagged" };
	}
	if (isRetryableMetaError(input.status ?? 0, input.error)) {
		return { classification: "transient_retry", retryable: true, route: "/settings?tab=ops" };
	}
	const webhookClass = classifyWebhookError(input.error);
	if (webhookClass === "permanent") {
		return { classification: "permanent_failure", retryable: false, route: "/admin/dead-letters" };
	}
	return { classification: "manual_recovery", retryable: false, route: "/admin/dead-letters" };
}

export async function recordMetaApiUsageSnapshot(
	db: Db,
	input: {
		userId?: string | null;
		workspaceId?: string | null;
		accountId?: string | null;
		platform: "instagram" | "threads" | "meta";
		endpointFamily: string;
		response: Response | Headers | Record<string, unknown>;
		metaCode?: string | number | null;
		metaSubcode?: string | number | null;
		requestId?: string | null;
	},
) {
	const parsed = parseMetaApiUsageHeaders(input.response);
	if (!parsed.appUsage && !parsed.businessUsage && !parsed.retryAfterSeconds) return;
	try {
		await db.from("meta_api_usage_snapshots").insert({
			user_id: input.userId ?? null,
			workspace_id: input.workspaceId ?? null,
			account_id: input.accountId ?? null,
			platform: input.platform,
			endpoint_family: input.endpointFamily,
			status: parsed.status ?? null,
			meta_code: input.metaCode == null ? null : String(input.metaCode),
			meta_subcode: input.metaSubcode == null ? null : String(input.metaSubcode),
			app_usage: parsed.appUsage,
			business_usage: parsed.businessUsage,
			usage_percent: parsed.usagePercent,
			retry_after_seconds: parsed.retryAfterSeconds,
			request_id: input.requestId ?? null,
			tone: parsed.tone,
		});
	} catch (error) {
		logger.warn("[reliability] Failed to record Meta API usage snapshot", { error: String(error) });
	}
}

export async function loadReliabilitySections(db: Db, userId: string, options: { windowHours?: number } = {}): Promise<ReliabilitySections> {
	const windowHours = options.windowHours ?? 24;
	const now = Date.now();
	const windowStart = new Date(now - windowHours * 60 * 60 * 1000).toISOString();
	const tokenSoon = new Date(now + 7 * 24 * 60 * 60 * 1000).toISOString();
	const [posts, queue, snapshots, metaUsage, webhookDeliveries, threadsWebhookDlq, igWebhookDlq, threadTokens, igTokens] = await Promise.all([
		db
			.from("posts")
			.select("id, account_id, instagram_account_id, platform, status, scheduled_for, published_at, error_message, metadata, updated_at")
			.eq("user_id", userId)
			.not("scheduled_for", "is", null)
			.gte("scheduled_for", windowStart)
			.limit(2000),
		db
			.from("auto_post_queue")
			.select("id, workspace_id, group_id, account_id, status, scheduled_for, next_retry_at, dead_letter_at, qstash_message_id")
			.eq("user_id", userId)
			.in("status", ["pending", "queued", "processing", "retrying", "dead_letter"])
			.limit(500),
		db
			.from("reliability_slo_snapshots")
			.select("*")
			.eq("user_id", userId)
			.gte("window_end", new Date(now - 14 * 24 * 60 * 60 * 1000).toISOString())
			.order("window_end", { ascending: true })
			.limit(60),
		db
			.from("meta_api_usage_snapshots")
			.select("id, platform, account_id, endpoint_family, status, usage_percent, retry_after_seconds, tone, captured_at")
			.or(`user_id.eq.${userId},user_id.is.null`)
			.gte("captured_at", windowStart)
			.order("captured_at", { ascending: false })
			.limit(100),
		db
			.from("webhook_deliveries")
			.select("id, event, status, attempts, max_attempts, last_error, next_retry_at, created_at, subscription_id")
			.eq("user_id", userId)
			.in("status", ["failed", "dead_letter"])
			.order("created_at", { ascending: false })
			.limit(100),
		db
			.from("threads_webhook_events")
			.select("id, account_id, dead_letter, dead_letter_at")
			.eq("user_id", userId)
			.eq("dead_letter", true)
			.order("dead_letter_at", { ascending: false })
			.limit(100),
		db
			.from("ig_webhook_events")
			.select("id, ig_account_id, dead_letter, dead_letter_at")
			.eq("user_id", userId)
			.eq("dead_letter", true)
			.order("dead_letter_at", { ascending: false })
			.limit(100),
		db
			.from("accounts")
			.select("id, username, group_id, status, needs_reauth, token_expires_at, consecutive_refresh_failures, updated_at, is_active")
			.eq("user_id", userId)
			.eq("is_active", true)
			.or(`needs_reauth.eq.true,token_expires_at.lte.${tokenSoon}`)
			.limit(200),
		db
			.from("instagram_accounts")
			.select("id, username, group_id, status, needs_reauth, token_expires_at, consecutive_refresh_failures, updated_at, is_active")
			.eq("user_id", userId)
			.eq("is_active", true)
			.or(`needs_reauth.eq.true,token_expires_at.lte.${tokenSoon}`)
			.limit(200),
	]);

	const reliabilitySlo = calculateSchedulingSlo(
		rows(posts),
		rows(queue),
		windowHours,
		rows(snapshots).map((row) => ({
			windowStart: row.window_start,
			windowEnd: row.window_end,
			successRate: numberOrZero(row.success_rate),
			onTimeRate: numberOrZero(row.on_time_rate),
			p95DriftSeconds: numberOrZero(row.p95_drift_seconds),
			failedTotal: numberOrZero(row.failed_total),
			dlqCount: numberOrZero(row.dlq_count),
		})),
	);
	const usageRows = rows(metaUsage);
	const maxUsagePercent = Math.max(0, ...usageRows.map((row) => numberOrZero(row.usage_percent)));
	const retryAfterActiveCount = usageRows.filter((row) => numberOrZero(row.retry_after_seconds) > 0).length;
	const criticalCount = usageRows.filter((row) => row.tone === "critical" || numberOrZero(row.usage_percent) >= 95).length;
	const warningCount = usageRows.filter((row) => row.tone === "warning" || numberOrZero(row.usage_percent) >= 80).length;
	const metaApiUsage: MetaApiUsageSummary = {
		generatedAt: new Date().toISOString(),
		tone: criticalCount > 0 || retryAfterActiveCount > 0 ? "critical" : warningCount > 0 ? "warning" : "healthy",
		latest: usageRows.slice(0, 20),
		maxUsagePercent,
		retryAfterActiveCount,
		warningCount,
		criticalCount,
	};
	const deliveryRows = rows(webhookDeliveries);
	const webhookHealth: WebhookHealthSummary = {
		generatedAt: new Date().toISOString(),
		tone: deliveryRows.some((row) => row.status === "dead_letter") || rows(threadsWebhookDlq).length + rows(igWebhookDlq).length > 0 ? "critical" : deliveryRows.length > 0 ? "warning" : "healthy",
		failedDeliveries: deliveryRows.filter((row) => row.status === "failed").length,
		deadLetterDeliveries: deliveryRows.filter((row) => row.status === "dead_letter").length,
		threadsDeadLetters: rows(threadsWebhookDlq).length,
		instagramDeadLetters: rows(igWebhookDlq).length,
		nextRetryCount: deliveryRows.filter((row) => stringOrNull(row.next_retry_at)).length,
		issues: deliveryRows.slice(0, 10),
	};
	const tokenAccounts: Array<Record<string, unknown> & { platform: "threads" | "instagram" }> = [
		...rows(threadTokens).map((row) => ({ ...row, platform: "threads" as const })),
		...rows(igTokens).map((row) => ({ ...row, platform: "instagram" as const })),
	];
	const expired = tokenAccounts.filter((row) => {
		const expires = stringOrNull(row.token_expires_at);
		return !!expires && Date.parse(expires) <= now;
	}).length;
	const needsReauth = tokenAccounts.filter((row) => row.needs_reauth === true || row.status === "needs_reauth").length;
	const tokenSlo: TokenSloSummary = {
		generatedAt: new Date().toISOString(),
		tone: needsReauth > 0 || expired > 0 ? "critical" : tokenAccounts.length > 0 ? "warning" : "healthy",
		totalIssues: tokenAccounts.length,
		needsReauth,
		expiringSoon: Math.max(0, tokenAccounts.length - needsReauth - expired),
		expired,
		accounts: tokenAccounts.slice(0, 50).map((row) => ({
			id: row.id,
			handle: row.username,
			platform: row.platform,
			group_id: row.group_id,
			status: row.status,
			needs_reauth: row.needs_reauth === true,
			token_expires_at: row.token_expires_at,
			last_token_refresh_at: row.updated_at,
			token_refresh_failures: row.consecutive_refresh_failures,
			route: `/accounts?status=flagged&accountId=${encodeURIComponent(String(row.id))}`,
		})),
	};
	return { reliabilitySlo, metaApiUsage, webhookHealth, tokenSlo };
}

export async function persistReliabilitySloSnapshot(db: Db, userId: string, summary: SchedulingSloSummary) {
	try {
		const windowEnd = new Date().toISOString();
		const windowStart = new Date(Date.now() - summary.windowHours * 60 * 60 * 1000).toISOString();
		await db.from("reliability_slo_snapshots").upsert(
			{
				user_id: userId,
				window_start: windowStart,
				window_end: windowEnd,
				window_hours: summary.windowHours,
				scheduled_total: summary.scheduledTotal,
				published_total: summary.publishedTotal,
				failed_total: summary.failedTotal,
				on_time_60s: summary.onTime60s,
				late_over_5m: summary.lateOver5m,
				success_rate: summary.successRate,
				on_time_rate: summary.onTimeRate,
				p50_drift_seconds: summary.driftSeconds.p50,
				p95_drift_seconds: summary.driftSeconds.p95,
				p99_drift_seconds: summary.driftSeconds.p99,
				max_drift_seconds: summary.driftSeconds.max,
				avg_drift_seconds: summary.driftSeconds.avg,
				qstash_failures: summary.qstashFailures,
				dlq_count: summary.dlqCount,
				backlog_count: summary.backlogCount,
				impacted_account_ids: summary.impactedAccountIds,
				tone: summary.tone,
			},
			{ onConflict: "user_id,window_start,window_end" },
		);
	} catch (error) {
		logger.warn("[reliability] Failed to persist SLO snapshot", { userId, error: String(error) });
	}
}

function percentile(values: number[], pct: number): number {
	if (!values.length) return 0;
	const sorted = [...values].sort((a, b) => a - b);
	const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((pct / 100) * sorted.length) - 1));
	return sorted[index] ?? 0;
}

function roundPct(value: number): number {
	return Math.round(value * 10_000) / 100;
}

function parseUsageHeader(value: string | null): Record<string, number> | null {
	if (!value) return null;
	try {
		const parsed = JSON.parse(value);
		if (!parsed || typeof parsed !== "object") return null;
		return Object.fromEntries(
			Object.entries(parsed)
				.map(([key, raw]) => [key, Number(raw)])
				.filter((entry): entry is [string, number] => Number.isFinite(entry[1])),
		);
	} catch {
		return null;
	}
}

function parseBusinessUsageHeader(value: string | null): Record<string, number> | null {
	if (!value) return null;
	try {
		const parsed = JSON.parse(value);
		const flattened: Record<string, number> = {};
		flattenNumbers(parsed, "", flattened);
		return Object.keys(flattened).length > 0 ? flattened : null;
	} catch {
		return null;
	}
}

function flattenNumbers(value: unknown, prefix: string, out: Record<string, number>) {
	if (!value || typeof value !== "object") return;
	for (const [key, raw] of Object.entries(value)) {
		const nextKey = prefix ? `${prefix}.${key}` : key;
		if (typeof raw === "number" && Number.isFinite(raw)) {
			out[nextKey] = raw;
		} else if (raw && typeof raw === "object") {
			flattenNumbers(raw, nextKey, out);
		}
	}
}

function parseRetryAfterSeconds(value: string | null): number | null {
	if (!value) return null;
	const seconds = Number(value);
	if (Number.isFinite(seconds) && seconds > 0) return Math.ceil(seconds);
	const date = Date.parse(value);
	if (Number.isFinite(date)) return Math.max(0, Math.ceil((date - Date.now()) / 1000));
	return null;
}

function rows(result: { data?: unknown[] | null } | null | undefined): Array<Record<string, unknown>> {
	const data = result?.data;
	return Array.isArray(data) ? (data as Array<Record<string, unknown>>) : [];
}

function stringOrNull(value: unknown): string | null {
	return typeof value === "string" && value.length > 0 ? value : null;
}

function numberOrZero(value: unknown): number {
	const number = Number(value);
	return Number.isFinite(number) ? number : 0;
}
