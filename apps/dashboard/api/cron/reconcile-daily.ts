// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Daily Reconciliation Cron — /api/cron/reconcile-daily
 *
 * Closes the webhook-loss gap (1-5% of Meta webhooks silently fail to deliver
 * per Meta's published SLAs). Rather than adding retry infrastructure, we
 * reconcile daily per platform: for every active account, list the most
 * recent Meta posts and detect orphans — posts that exist on Meta but not
 * in our posts table. Orphans happen when:
 *   (a) a publish webhook was lost after auto-post delivered to Meta
 *   (b) the user posted manually via the Meta app
 *   (c) a delayed publish succeeded after we marked it failed
 *
 * Scope: both platforms — Threads phase then Instagram phase, each with its
 * own reconciliation_runs row for per-platform observability. Metric drift
 * (likes, views, etc.) is already handled by analyticsSync every 15 min —
 * this job does NOT touch metrics, only detects missing posts.
 *
 * Scheduled daily at 03:30 UTC (after daily-orchestrator-late at 01:30).
 * Budget: 300s. Parallelism: bounded stale-first batches per platform.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure, alertWarn } from "../_lib/alerting.js";
import { verifyCronAuth } from "../_lib/apiResponse.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { getUserMedia } from "../_lib/instagram/media.js";
import type { IGMediaItem } from "../_lib/instagram/shared.js";
import { logger } from "../_lib/logger.js";
import { getSupabase, getSupabaseAny } from "../_lib/supabase.js";
import { neqOrNull } from "../_lib/supabaseSafe.js";
import { getProfilePosts } from "../_lib/threadsApi.js";

const PARALLEL_CHUNK_SIZE = 5;
const POSTS_PER_ACCOUNT = 25;
const DEFAULT_ACCOUNT_LIMIT = 200;
const DEFAULT_ORPHAN_MAX_AGE_HOURS = 72;
const configuredAccountLimit = Number(
	process.env.RECONCILE_DAILY_ACCOUNT_LIMIT,
);
const ACCOUNT_LIMIT = Number.isFinite(configuredAccountLimit)
	? Math.max(1, configuredAccountLimit)
	: DEFAULT_ACCOUNT_LIMIT;
const configuredOrphanMaxAgeHours = Number(
	process.env.RECONCILE_DAILY_ORPHAN_MAX_AGE_HOURS,
);
const ORPHAN_MAX_AGE_MS =
	(Number.isFinite(configuredOrphanMaxAgeHours)
		? Math.max(1, configuredOrphanMaxAgeHours)
		: DEFAULT_ORPHAN_MAX_AGE_HOURS) *
	60 *
	60 *
	1000;

interface ThreadsMetaPost {
	id: string;
	text?: string | undefined;
	timestamp?: string | undefined;
	permalink?: string | undefined;
	media_type?: string | undefined;
}

interface ThreadsAccountRow {
	id: string;
	user_id: string;
	username: string;
	threads_access_token_encrypted: string;
	is_active?: boolean | undefined;
	needs_reauth?: boolean | undefined;
}

interface InstagramAccountRow {
	id: string;
	user_id: string;
	username: string;
	instagram_user_id: string;
	instagram_access_token_encrypted: string;
	login_type?: string | null | undefined;
	is_active?: boolean | undefined;
	needs_reauth?: boolean | undefined;
}

interface PhaseStats {
	accountsChecked: number;
	accountsErrored: number;
	orphansInserted: number;
	postsChecked: number;
	durationMs: number;
}

export function isRecentReconcileOrphan(
	timestamp: string | null | undefined,
	nowMs = Date.now(),
	maxAgeMs = ORPHAN_MAX_AGE_MS,
): boolean {
	if (!timestamp) return true;
	const publishedMs = Date.parse(timestamp);
	if (!Number.isFinite(publishedMs)) return true;
	return nowMs - publishedMs <= maxAgeMs;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST" && req.method !== "GET") {
		return res.status(405).json({ error: "Method not allowed" });
	}
	if (!verifyCronAuth(req, res)) return;

	const supabase = getSupabase();

	const lockResult = await withCronLock(
		supabase,
		"reconcile-daily",
		async () => {
			return trackCronRun(supabase, "reconcile-daily", async () => {
				const db = getSupabaseAny();

				const threads = await runThreadsPhase(db);
				const instagram = await runInstagramPhase(db);

				const totalAccountsChecked =
					threads.accountsChecked + instagram.accountsChecked;
				const totalOrphansInserted =
					threads.orphansInserted + instagram.orphansInserted;

				logger.info("[reconcile-daily] all phases complete", {
					threads,
					instagram,
				});

				return {
					itemsProcessed: totalAccountsChecked,
					metadata: {
						threads,
						instagram,
						orphansInserted: totalOrphansInserted,
					},
				};
			});
		},
	);

	if (lockResult === null) {
		return res
			.status(200)
			.json({ ok: true, skipped: true, reason: "lock already held" });
	}
	return res.status(200).json({ ok: true, ...lockResult });
}

// ---------------------------------------------------------------------------
// Per-platform phases
// ---------------------------------------------------------------------------

// biome-ignore lint/suspicious/noExplicitAny: supabase any client for table-agnostic access
async function runThreadsPhase(db: any): Promise<PhaseStats> {
	return runPhase(
		"threads",
		db,
		async () => {
			// `.neq("needs_reauth", true)` would silently drop rows where
			// needs_reauth is NULL — the same trap that masked accounts during
			// the April outage. Use neqOrNull so newly-created rows (NULL flag)
			// remain in the reconcile set.
			let q = db
				.from("accounts")
				.select("id, user_id, username, threads_access_token_encrypted")
				.eq("is_active", true);
			q = neqOrNull(q, "needs_reauth", true);
			const { data, error } = await q
				.not("threads_access_token_encrypted", "is", null)
				.order("last_synced_at", { ascending: true, nullsFirst: true })
				.order("id", { ascending: true })
				.limit(ACCOUNT_LIMIT);
			if (error) throw new Error(`accounts query: ${error.message}`);
			return (data ?? []) as ThreadsAccountRow[];
		},
		reconcileThreadsAccount,
	);
}

// biome-ignore lint/suspicious/noExplicitAny: supabase any client for table-agnostic access
async function runInstagramPhase(db: any): Promise<PhaseStats> {
	return runPhase(
		"instagram",
		db,
		async () => {
			// Same `neq`/NULL trap fix as runThreadsPhase above.
			let q = db
				.from("instagram_accounts")
				.select(
					"id, user_id, username, instagram_user_id, instagram_access_token_encrypted, login_type",
				)
				.eq("is_active", true);
			q = neqOrNull(q, "needs_reauth", true);
			const { data, error } = await q
				.not("instagram_access_token_encrypted", "is", null)
				.not("instagram_user_id", "is", null)
				.order("last_synced_at", { ascending: true, nullsFirst: true })
				.order("id", { ascending: true })
				.limit(ACCOUNT_LIMIT);
			if (error) throw new Error(`instagram_accounts query: ${error.message}`);
			return (data ?? []) as InstagramAccountRow[];
		},
		reconcileInstagramAccount,
	);
}

async function runPhase<A extends { id: string; username: string }>(
	platform: "threads" | "instagram",
	// biome-ignore lint/suspicious/noExplicitAny: supabase any client
	db: any,
	fetchAccounts: () => Promise<A[]>,
	processAccount: (
		account: A,
		// biome-ignore lint/suspicious/noExplicitAny: supabase any client
		db: any,
	) => Promise<{ postsChecked: number; orphansInserted: number }>,
): Promise<PhaseStats> {
	const startTime = Date.now();

	const { data: runRow } = await db
		.from("reconciliation_runs")
		.insert({ platform, status: "running" })
		.select("id")
		.single();
	const runId = runRow?.id as string | undefined;

	let accountsChecked = 0;
	let accountsErrored = 0;
	let orphansInserted = 0;
	let postsChecked = 0;
	const errors: string[] = [];

	try {
		const accounts = await fetchAccounts();
		logger.info(`[reconcile-daily] ${platform} phase starting`, {
			accountCount: accounts.length,
		});

		for (let i = 0; i < accounts.length; i += PARALLEL_CHUNK_SIZE) {
			const chunk = accounts.slice(i, i + PARALLEL_CHUNK_SIZE);
			const results = await Promise.allSettled(
				chunk.map((a) => processAccount(a, db)),
			);
			for (let j = 0; j < results.length; j++) {
				const r = results[j];
				const account = chunk[j];
				if (r!.status === "fulfilled") {
					accountsChecked++;
					postsChecked += r!.value.postsChecked;
					orphansInserted += r!.value.orphansInserted;
				} else {
					accountsErrored++;
					errors.push(
						`${account!.username}: ${String(r!.reason).slice(0, 120)}`,
					);
				}
			}
		}

		const durationMs = Date.now() - startTime;

		if (runId) {
			await db
				.from("reconciliation_runs")
				.update({
					completed_at: new Date().toISOString(),
					duration_ms: durationMs,
					accounts_checked: accountsChecked,
					accounts_errored: accountsErrored,
					orphans_inserted: orphansInserted,
					posts_checked: postsChecked,
					status: "completed",
					error_summary: errors.length ? errors.slice(0, 20).join("; ") : null,
				})
				.eq("id", runId);
		}

		if (orphansInserted >= 5) {
			try {
				const { data: recentRuns } = await db
					.from("reconciliation_runs")
					.select("started_at, orphans_inserted")
					.eq("platform", platform)
					.eq("status", "completed")
					.gte(
						"started_at",
						new Date(Date.now() - 4 * 24 * 60 * 60 * 1000).toISOString(),
					)
					.order("started_at", { ascending: false })
					.limit(4);
				const daysWithOrphans = (recentRuns ?? []).filter(
					(row: { orphans_inserted?: number | null }) =>
						(row.orphans_inserted ?? 0) >= 5,
				).length;
				await alertWarn(
					`reconcile-daily found ${orphansInserted} ${platform} orphan posts`,
					{
						platform,
						accountsChecked,
						postsChecked,
						durationMs,
						daysWithOrphans,
						severity:
							daysWithOrphans >= 3
								? "persistent_orphan_signal"
								: "first_or_recent_orphan_signal",
						action:
							daysWithOrphans >= 3
								? "Persistent 3+ day signal. Review Meta webhook subscription health and whether reconciliation is backfilling stale historical media."
								: "Webhook-loss signal. If this persists >3 days, review Meta webhook subscription health.",
					},
				);
			} catch {
				// Alerting is non-blocking
			}
		}

		logger.info(`[reconcile-daily] ${platform} phase complete`, {
			accountsChecked,
			accountsErrored,
			orphansInserted,
			postsChecked,
			durationMs,
		});

		return {
			accountsChecked,
			accountsErrored,
			orphansInserted,
			postsChecked,
			durationMs,
		};
	} catch (err) {
		const errorMsg = err instanceof Error ? err.message : String(err);
		logger.error(`[reconcile-daily] ${platform} phase fatal`, {
			error: errorMsg,
		});
		if (runId) {
			await db
				.from("reconciliation_runs")
				.update({
					completed_at: new Date().toISOString(),
					duration_ms: Date.now() - startTime,
					status: "failed",
					error_summary: errorMsg.slice(0, 500),
				})
				.eq("id", runId);
		}
		try {
			await alertCronFailure(
				`reconcile-daily:${platform}`,
				errorMsg,
				Date.now() - startTime,
			);
		} catch {
			// Alerting is non-blocking
		}
		// Don't rethrow — let the other phase still run.
		return {
			accountsChecked,
			accountsErrored,
			orphansInserted,
			postsChecked,
			durationMs: Date.now() - startTime,
		};
	}
}

// ---------------------------------------------------------------------------
// Per-account reconciliation
// ---------------------------------------------------------------------------

async function reconcileThreadsAccount(
	account: ThreadsAccountRow,
	// biome-ignore lint/suspicious/noExplicitAny: supabase client lacks precise generics here
	db: any,
): Promise<{ postsChecked: number; orphansInserted: number }> {
	let postsChecked = 0;
	let orphansInserted = 0;

	// Fetch recent Meta posts for this account
	const profileData = await getProfilePosts(
		account.threads_access_token_encrypted,
		account.username,
		POSTS_PER_ACCOUNT,
	);
	const metaPosts: ThreadsMetaPost[] = Array.isArray(profileData?.data)
		? (profileData.data as ThreadsMetaPost[])
		: [];
	postsChecked = metaPosts.length;

	if (metaPosts.length === 0) {
		return { postsChecked, orphansInserted };
	}

	// Look up which of these are already in our posts table for this account
	const metaPostIds = metaPosts.map((p) => p.id).filter(Boolean);
	const { data: known, error: knownErr } = await db
		.from("posts")
		.select("threads_post_id")
		.eq("account_id", account.id)
		.in("threads_post_id", metaPostIds);

	if (knownErr) {
		throw new Error(`posts lookup: ${knownErr.message}`);
	}

	const knownIds = new Set(
		(known ?? [])
			.map((r: { threads_post_id: string | null }) => r.threads_post_id)
			.filter(Boolean),
	);

	// Any recent Meta post not in knownIds is an orphan → insert. Older
	// historical media is backfill/noise for this webhook-loss sentinel.
	const orphans = metaPosts.filter(
		(p) =>
			p.id &&
			!knownIds.has(p.id) &&
			isRecentReconcileOrphan(p.timestamp),
	);
	if (orphans.length === 0) {
		return { postsChecked, orphansInserted: 0 };
	}

	const rows = orphans.map((p) => ({
		user_id: account.user_id,
		account_id: account.id,
		threads_post_id: p.id,
		content: p.text ?? "",
		status: "published" as const,
		platform: "threads" as const,
		published_at: p.timestamp ?? new Date().toISOString(),
	}));

	const { error: insertErr } = await db.from("posts").insert(rows);
	if (insertErr) {
		throw new Error(`orphan insert: ${insertErr.message}`);
	}
	orphansInserted = rows.length;

	logger.info("[reconcile-daily] orphans detected", {
		platform: "threads",
		accountId: account.id,
		username: account.username,
		orphansInserted,
	});
	return { postsChecked, orphansInserted };
}

async function reconcileInstagramAccount(
	account: InstagramAccountRow,
	// biome-ignore lint/suspicious/noExplicitAny: supabase client lacks precise generics here
	db: any,
): Promise<{ postsChecked: number; orphansInserted: number }> {
	let postsChecked = 0;
	let orphansInserted = 0;

	// Fetch recent Meta media for this IG account
	const result = await getUserMedia(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		POSTS_PER_ACCOUNT,
		account.login_type ?? undefined,
	);
	if (!result.success) {
		throw new Error(`getUserMedia: ${result.error ?? "unknown error"}`);
	}
	const metaPosts: IGMediaItem[] = Array.isArray(result.media)
		? result.media
		: [];
	postsChecked = metaPosts.length;

	if (metaPosts.length === 0) {
		return { postsChecked, orphansInserted };
	}

	// Look up which of these are already in our posts table for this IG account
	const metaPostIds = metaPosts.map((p) => p.id).filter(Boolean);
	const { data: known, error: knownErr } = await db
		.from("posts")
		.select("instagram_post_id")
		.eq("instagram_account_id", account.id)
		.in("instagram_post_id", metaPostIds);

	if (knownErr) {
		throw new Error(`posts lookup: ${knownErr.message}`);
	}

	const knownIds = new Set(
		(known ?? [])
			.map((r: { instagram_post_id: string | null }) => r.instagram_post_id)
			.filter(Boolean),
	);

	// Any recent Meta post not in knownIds is an orphan → insert. Older
	// historical media is backfill/noise for this webhook-loss sentinel.
	const orphans = metaPosts.filter(
		(p) =>
			p.id &&
			!knownIds.has(p.id) &&
			isRecentReconcileOrphan(p.timestamp),
	);
	if (orphans.length === 0) {
		return { postsChecked, orphansInserted: 0 };
	}

	const rows = orphans.map((p) => ({
		user_id: account.user_id,
		instagram_account_id: account.id,
		instagram_post_id: p.id,
		content: p.caption ?? "",
		status: "published" as const,
		platform: "instagram" as const,
		published_at: p.timestamp ?? new Date().toISOString(),
		ig_media_type: p.media_type ?? null,
		permalink: p.permalink ?? null,
	}));

	const { error: insertErr } = await db.from("posts").insert(rows);
	if (insertErr) {
		throw new Error(`orphan insert: ${insertErr.message}`);
	}
	orphansInserted = rows.length;

	logger.info("[reconcile-daily] orphans detected", {
		platform: "instagram",
		accountId: account.id,
		username: account.username,
		orphansInserted,
	});
	return { postsChecked, orphansInserted };
}
