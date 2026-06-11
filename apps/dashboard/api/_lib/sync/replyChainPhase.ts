/**
 * Reply Chain Pulse Sync Phase
 *
 * Keeps posts.reply_depth fresh for published Threads posts. Runs as a
 * dedicated phase in sync-orchestrator (every 15 min).
 *
 * Rate-limit budget:
 *   Threads API caps at 250 calls/24h/account. Publishing + reply
 *   harvesting + profile pings all compete for that quota, so this
 *   phase stays tiny inside the 60s sync-orchestrator runtime:
 *   REPLY_CHAIN_CALLS_PER_ACCOUNT_PER_RUN = 1 across at most 4 accounts.
 *   Posts are selected oldest-stale-first so freshness is fair across an
 *   account's publish history.
 *
 * Target freshness: every published post gets a reply_depth refresh
 * at least every 24h. Trending posts (new discussion coming in) get
 * re-checked on their next sync slot — not real-time, but within an
 * hour if the account doesn't have many stale posts.
 */

import { logger, serializeError } from "../logger.js";
import {
	ReplyChainRateLimitError,
	syncReplyChainForPost,
} from "../handlers/threads/replyChainSync.js";
import { hasTimeBudget, DELAY_BETWEEN_ACCOUNTS } from "./shared.js";

// Per-run-per-account ceiling. See budget math in module docstring.
const REPLY_CHAIN_CALLS_PER_ACCOUNT_PER_RUN = 1;

// Cap total work per orchestrator tick so we don't starve other phases.
const MAX_ACCOUNTS_PER_RUN = 4;
const STALE_POST_SELECTION_MULTIPLIER = 10;

interface StalePost {
	id: string;
	threads_post_id: string;
	account_id: string;
	user_id: string;
}

interface AccountToken {
	id: string;
	threads_access_token_encrypted: string | null;
}

interface ChainSyncStats {
	stalePostsFound: number;
	accountsScanned: number;
	accountsConsidered: number;
	accountsWithTokens: number;
	accountsMissingTokens: number;
	postsProcessed: number;
	postsSkipped: number;
	rateLimitedAccounts: number;
	errors: number;
	errorSamples: string[];
	selectError?: string | undefined;
	tokenSelectError?: string | undefined;
}

export async function processReplyChainQueue(): Promise<ChainSyncStats> {
	const stats: ChainSyncStats = {
		stalePostsFound: 0,
		accountsScanned: 0,
		accountsConsidered: 0,
		accountsWithTokens: 0,
		accountsMissingTokens: 0,
		postsProcessed: 0,
		postsSkipped: 0,
		rateLimitedAccounts: 0,
		errors: 0,
		errorSamples: [],
	};

	if (!hasTimeBudget()) {
		logger.info("[replyChainPhase] No time budget — skipping");
		return stats;
	}

	const { getSupabase } = await import("../supabase.js");
	const supabase = getSupabase();

	// Pre-filter to live Threads accounts. Retired/inactive/no-token accounts
	// can have hundreds of un-syncable posts that dominate oldest-stale-first
	// ordering and starve every healthy account in the fleet (e.g. one retired
	// account with empty-string token + 185 NULL-synced posts blocked the
	// entire queue for 10 days). Resolving account-level eligibility up front
	// avoids that whole class of starvation.
	const { data: liveAccounts, error: liveAccountsError } = (await supabase
		.from("accounts")
		.select("id, threads_access_token_encrypted")
		.eq("is_active", true)
		.eq("is_retired", false)
		.not("threads_access_token_encrypted", "is", null)) as {
		data: AccountToken[] | null;
		error: { message: string } | null;
	};

	if (liveAccountsError) {
		logger.error("[replyChainPhase] Failed to select live accounts", {
			error: liveAccountsError.message,
		});
		stats.errors++;
		stats.tokenSelectError = liveAccountsError.message;
		return stats;
	}

	const tokenMap = new Map<string, string>();
	for (const a of liveAccounts ?? []) {
		// Token can also be empty string for partially-disconnected accounts
		// — treat empty as "no token" (JS falsy already does this, but be
		// explicit so future readers don't optimize the truthy check away).
		if (a.threads_access_token_encrypted && a.threads_access_token_encrypted !== "") {
			tokenMap.set(a.id, a.threads_access_token_encrypted);
		}
	}

	if (tokenMap.size === 0) {
		logger.info("[replyChainPhase] No live accounts with usable tokens");
		return stats;
	}

	const liveAccountIds = Array.from(tokenMap.keys());

	// Pull stale posts scoped to live accounts only. Oldest-stale-first remains
	// the rotation rule. Oversample so one trickle-publishing account doesn't
	// starve a busier sibling.
	const hardCap = MAX_ACCOUNTS_PER_RUN * REPLY_CHAIN_CALLS_PER_ACCOUNT_PER_RUN;
	const selectionCap = hardCap * STALE_POST_SELECTION_MULTIPLIER;
	const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

	const { data: stalePosts, error: selectError } = (await supabase
		.from("posts")
		.select("id, threads_post_id, account_id, user_id, reply_chain_synced_at")
		.in("account_id", liveAccountIds)
		.eq("status", "published")
		.not("threads_post_id", "is", null)
		.or(
			`reply_chain_synced_at.is.null,reply_chain_synced_at.lt.${cutoff}`,
		)
		.order("reply_chain_synced_at", { ascending: true, nullsFirst: true })
		.limit(selectionCap)) as {
		data: StalePost[] | null;
		error: { message: string } | null;
	};

	if (selectError) {
		logger.error("[replyChainPhase] Failed to select stale posts", {
			error: selectError.message,
		});
		stats.errors++;
		stats.selectError = selectError.message;
		return stats;
	}
	if (!stalePosts?.length) {
		logger.debug("[replyChainPhase] No stale posts — done");
		return stats;
	}
	stats.stalePostsFound = stalePosts.length;

	// Group by account so we can enforce per-account caps. Account-level
	// eligibility was resolved up front via the live-accounts pre-filter, so
	// every account here is guaranteed to have a usable token.
	const byAccount = new Map<string, StalePost[]>();
	for (const p of stalePosts) {
		const list = byAccount.get(p.account_id);
		if (list) list.push(p);
		else byAccount.set(p.account_id, [p]);
	}
	stats.accountsScanned = byAccount.size;
	stats.accountsWithTokens = tokenMap.size;
	stats.accountsMissingTokens = 0;
	const runnableAccountIds = Array.from(byAccount.keys()).slice(
		0,
		MAX_ACCOUNTS_PER_RUN,
	);
	stats.accountsConsidered = runnableAccountIds.length;

	for (const accountId of runnableAccountIds) {
		if (!hasTimeBudget()) {
			logger.info(
				"[replyChainPhase] Time budget exhausted — stopping account loop",
			);
			break;
		}
		// Token is guaranteed by the live-accounts pre-filter, but keep the
		// non-null read narrow for type safety.
		const token = tokenMap.get(accountId);
		if (!token) continue;

		const posts = byAccount
			.get(accountId)?.slice(0, REPLY_CHAIN_CALLS_PER_ACCOUNT_PER_RUN);

		if (!posts) continue;
		let rateLimited = false;
		for (const post of posts) {
			if (!hasTimeBudget()) break;
			try {
				await syncReplyChainForPost({
					postId: post.id,
					threadsPostId: post.threads_post_id,
					accountId,
					accessTokenEncrypted: token,
				});
				stats.postsProcessed++;
			} catch (err) {
				if (err instanceof ReplyChainRateLimitError) {
					rateLimited = true;
					stats.rateLimitedAccounts++;
					logger.warn("[replyChainPhase] Rate limited — skipping account", {
						accountId,
					});
					break;
				}
				stats.errors++;
				if (stats.errorSamples.length < 5) {
					stats.errorSamples.push(serializeError(err));
				}
				logger.warn("[replyChainPhase] Per-post sync failed", {
					postId: post.id,
					error: serializeError(err),
				});
				// Continue with next post in this account — one bad row doesn't
				// stop the whole batch.
			}
		}

		// Small delay between accounts to be polite + avoid bursty Threads calls.
		if (!rateLimited) {
			await new Promise((r) => setTimeout(r, DELAY_BETWEEN_ACCOUNTS));
		}
	}

	logger.info("[replyChainPhase] Complete", { ...stats });
	return stats;
}
