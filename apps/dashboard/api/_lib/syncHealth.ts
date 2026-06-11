import type { SupabaseClient } from "@supabase/supabase-js";

const DEFAULT_SYNC_MAX_AGE_HOURS = 24;
const COHORT_SYNC_MAX_AGE_HOURS: Record<string, number> = {
	hot: 6,
	warm: 12,
	cold: 30,
	dormant: 54,
};

export type SyncHealthPlatform = "threads" | "instagram";

export interface AccountSyncHealthIssue {
	platform: SyncHealthPlatform;
	accountId: string;
	userId: string | null;
	username: string | null;
	cohort: string | null;
	lastSyncedAt: string | null;
	lastWebhookAt: string | null;
	syncAgeHours: number | null;
	maxAgeHours: number;
	recentWebhookEvents: number;
	priorWebhookEvents: number;
	severity: "warning" | "critical";
	reasons: string[];
}

export interface AccountSyncHealthReport {
	healthy: boolean;
	checkedAt: string;
	totalAccounts: number;
	staleSyncAccounts: number;
	webhookRegressionAccounts: number;
	missingCredentialAccounts: number;
	issues: AccountSyncHealthIssue[];
	byPlatform: Record<
		SyncHealthPlatform,
		{
			totalAccounts: number;
			staleSyncAccounts: number;
			webhookRegressionAccounts: number;
			missingCredentialAccounts: number;
		}
	>;
}

interface ThreadsAccountRow {
	id: string;
	user_id: string | null;
	username: string | null;
	threads_user_id: string | null;
	threads_access_token_encrypted: string | null;
	is_active: boolean | null;
	needs_reauth: boolean | null;
	status: string | null;
	sync_cohort: string | null;
	last_synced_at: string | null;
}

interface InstagramAccountRow {
	id: string;
	user_id: string | null;
	username: string | null;
	instagram_user_id: string | null;
	instagram_access_token_encrypted: string | null;
	facebook_page_access_token_encrypted: string | null;
	login_type: string | null;
	is_active: boolean | null;
	needs_reauth: boolean | null;
	status: string | null;
	sync_cohort: string | null;
	last_synced_at: string | null;
}

interface WebhookEventRow {
	platform_user_id: string | null;
	event_at: string | null;
}

function hoursSince(value: string | null, nowMs: number): number | null {
	if (!value) return null;
	const parsed = Date.parse(value);
	if (!Number.isFinite(parsed)) return null;
	return Math.max(0, (nowMs - parsed) / (60 * 60 * 1000));
}

function maxAgeForCohort(cohort: string | null): number {
	return cohort ? (COHORT_SYNC_MAX_AGE_HOURS[cohort] ?? DEFAULT_SYNC_MAX_AGE_HOURS) : DEFAULT_SYNC_MAX_AGE_HOURS;
}

function eventBuckets(
	rows: WebhookEventRow[],
	cutoff48hMs: number,
): Map<string, { recent: number; prior: number; lastAt: string | null }> {
	const buckets = new Map<string, { recent: number; prior: number; lastAt: string | null }>();
	for (const row of rows) {
		if (!row.platform_user_id || !row.event_at) continue;
		const ts = Date.parse(row.event_at);
		if (!Number.isFinite(ts)) continue;
		const bucket = buckets.get(row.platform_user_id) ?? {
			recent: 0,
			prior: 0,
			lastAt: null,
		};
		if (ts >= cutoff48hMs) bucket.recent++;
		else bucket.prior++;
		if (!bucket.lastAt || ts > Date.parse(bucket.lastAt)) {
			bucket.lastAt = row.event_at;
		}
		buckets.set(row.platform_user_id, bucket);
	}
	return buckets;
}

function emptyPlatformSummary() {
	return {
		totalAccounts: 0,
		staleSyncAccounts: 0,
		webhookRegressionAccounts: 0,
		missingCredentialAccounts: 0,
	};
}

function addIssue(
	report: AccountSyncHealthReport,
	issue: AccountSyncHealthIssue,
) {
	report.issues.push(issue);
	const summary = report.byPlatform[issue.platform];
	if (issue.reasons.includes("sync_stale")) summary.staleSyncAccounts++;
	if (issue.reasons.includes("webhook_regression"))
		summary.webhookRegressionAccounts++;
	if (issue.reasons.includes("missing_credentials"))
		summary.missingCredentialAccounts++;
}

export async function getAccountSyncHealth(
	// biome-ignore lint/suspicious/noExplicitAny: health probes intentionally use loose Supabase typing across many tables
	supabase: SupabaseClient<any>,
	options: { limitIssues?: number } = {},
): Promise<AccountSyncHealthReport> {
	const now = Date.now();
	const cutoff14d = new Date(now - 14 * 24 * 60 * 60 * 1000).toISOString();
	const cutoff48hMs = now - 48 * 60 * 60 * 1000;
	const limitIssues = options.limitIssues ?? 50;

	const [
		{ data: threadsAccounts },
		{ data: instagramAccounts },
		{ data: threadsEventsRaw },
		{ data: igEventsRaw },
	] = await Promise.all([
		supabase
			.from("accounts")
			.select(
				"id, user_id, username, threads_user_id, threads_access_token_encrypted, is_active, needs_reauth, status, sync_cohort, last_synced_at",
			)
			.eq("is_active", true)
			.limit(1000),
		supabase
			.from("instagram_accounts")
			.select(
				"id, user_id, username, instagram_user_id, instagram_access_token_encrypted, facebook_page_access_token_encrypted, login_type, is_active, needs_reauth, status, sync_cohort, last_synced_at",
			)
			.eq("is_active", true)
			.limit(1000),
		supabase
			.from("threads_webhook_events")
			.select("threads_user_id, received_at, created_at")
			.gte("created_at", cutoff14d)
			.limit(5000),
		supabase
			.from("ig_webhook_events")
			.select("ig_user_id, received_at, created_at")
			.gte("created_at", cutoff14d)
			.limit(5000),
	]);

	const threadsEvents = ((threadsEventsRaw ?? []) as Array<{
		threads_user_id: string | null;
		received_at: string | null;
		created_at: string | null;
	}>).map((event) => ({
		platform_user_id: event.threads_user_id,
		event_at: event.received_at ?? event.created_at,
	}));
	const igEvents = ((igEventsRaw ?? []) as Array<{
		ig_user_id: string | null;
		received_at: string | null;
		created_at: string | null;
	}>).map((event) => ({
		platform_user_id: event.ig_user_id,
		event_at: event.received_at ?? event.created_at,
	}));

	const threadsBuckets = eventBuckets(threadsEvents, cutoff48hMs);
	const igBuckets = eventBuckets(igEvents, cutoff48hMs);
	const report: AccountSyncHealthReport = {
		healthy: true,
		checkedAt: new Date(now).toISOString(),
		totalAccounts: 0,
		staleSyncAccounts: 0,
		webhookRegressionAccounts: 0,
		missingCredentialAccounts: 0,
		issues: [],
		byPlatform: {
			threads: emptyPlatformSummary(),
			instagram: emptyPlatformSummary(),
		},
	};

	for (const account of (threadsAccounts ?? []) as ThreadsAccountRow[]) {
		report.totalAccounts++;
		report.byPlatform.threads.totalAccounts++;

		const reasons: string[] = [];
		const maxAgeHours = maxAgeForCohort(account.sync_cohort);
		const lastSyncedAt = account.last_synced_at;
		const syncAgeHours = hoursSince(lastSyncedAt, now);
		const bucket = account.threads_user_id
			? threadsBuckets.get(account.threads_user_id)
			: undefined;
		if (!account.threads_user_id || !account.threads_access_token_encrypted) {
			reasons.push("missing_credentials");
		}
		if (syncAgeHours === null || syncAgeHours > maxAgeHours) {
			reasons.push("sync_stale");
		}
		if ((bucket?.prior ?? 0) > 0 && (bucket?.recent ?? 0) === 0) {
			reasons.push("webhook_regression");
		}
		if (account.needs_reauth || account.status === "needs_reauth") {
			reasons.push("needs_reauth");
		}
		if (reasons.length > 0 && report.issues.length < limitIssues) {
			addIssue(report, {
				platform: "threads",
				accountId: account.id,
				userId: account.user_id,
				username: account.username,
				cohort: account.sync_cohort,
				lastSyncedAt,
				lastWebhookAt: bucket?.lastAt ?? null,
				syncAgeHours,
				maxAgeHours,
				recentWebhookEvents: bucket?.recent ?? 0,
				priorWebhookEvents: bucket?.prior ?? 0,
				severity:
					reasons.includes("missing_credentials") ||
					reasons.includes("needs_reauth")
						? "critical"
						: "warning",
				reasons,
			});
		}
	}

	for (const account of (instagramAccounts ?? []) as InstagramAccountRow[]) {
		report.totalAccounts++;
		report.byPlatform.instagram.totalAccounts++;

		const reasons: string[] = [];
		const maxAgeHours = maxAgeForCohort(account.sync_cohort);
		const syncAgeHours = hoursSince(account.last_synced_at, now);
		const bucket = account.instagram_user_id
			? igBuckets.get(account.instagram_user_id)
			: undefined;
		const hasToken =
			account.login_type === "facebook"
				? !!account.facebook_page_access_token_encrypted
				: !!account.instagram_access_token_encrypted;
		if (!account.instagram_user_id || !hasToken) reasons.push("missing_credentials");
		if (syncAgeHours === null || syncAgeHours > maxAgeHours) {
			reasons.push("sync_stale");
		}
		if ((bucket?.prior ?? 0) > 0 && (bucket?.recent ?? 0) === 0) {
			reasons.push("webhook_regression");
		}
		if (account.needs_reauth || account.status === "needs_reauth") {
			reasons.push("needs_reauth");
		}
		if (reasons.length > 0 && report.issues.length < limitIssues) {
			addIssue(report, {
				platform: "instagram",
				accountId: account.id,
				userId: account.user_id,
				username: account.username,
				cohort: account.sync_cohort,
				lastSyncedAt: account.last_synced_at,
				lastWebhookAt: bucket?.lastAt ?? null,
				syncAgeHours,
				maxAgeHours,
				recentWebhookEvents: bucket?.recent ?? 0,
				priorWebhookEvents: bucket?.prior ?? 0,
				severity:
					reasons.includes("missing_credentials") ||
					reasons.includes("needs_reauth")
						? "critical"
						: "warning",
				reasons,
			});
		}
	}

	report.staleSyncAccounts =
		report.byPlatform.threads.staleSyncAccounts +
		report.byPlatform.instagram.staleSyncAccounts;
	report.webhookRegressionAccounts =
		report.byPlatform.threads.webhookRegressionAccounts +
		report.byPlatform.instagram.webhookRegressionAccounts;
	report.missingCredentialAccounts =
		report.byPlatform.threads.missingCredentialAccounts +
		report.byPlatform.instagram.missingCredentialAccounts;
	report.healthy =
		report.staleSyncAccounts === 0 &&
		report.webhookRegressionAccounts === 0 &&
		report.missingCredentialAccounts === 0;

	return report;
}
