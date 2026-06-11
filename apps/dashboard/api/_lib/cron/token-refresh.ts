/**
 * Token Refresh Module
 *
 * Refreshes tokens that will expire within the next 10 days.
 * Prevents scheduled posts from failing due to expired tokens.
 *
 * Called as Phase 11 of daily-orchestrator (10-day safety-net refresh).
 * Complements the 5-day (120h) window in daily-maintenance (Phase 2).
 *
 * Features:
 * - Redis dedup: skips accounts already refreshed by daily-maintenance (6h TTL)
 * - Auto-deactivation on auth errors or 3 consecutive failures
 * - PBKDF2 v1→v2 token migration (up to 100 accounts per call)
 * - Discord alerting on per-account refresh failures
 */

import { alertTokenRefreshFailure } from "../alerting.js";
import { logger } from "../logger.js";
import {
	isAuthError as isMetaAuthErrorClassified,
	isTransientMetaError,
} from "../metaErrors.js";
import {
	verifyInstagramScopes,
	verifyThreadsScopes,
} from "../oauthScopeVerifier.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../privilegedDb.js";
import { neqOrNull } from "../supabaseSafe.js";
import {
	createConcurrencyLimiter,
	hasTimeBudget,
	TOKEN_CONCURRENCY_LIMIT,
} from "./daily-maintenance/shared.js";

const REDIS_DEDUP_PREFIX = "token-refreshed:";
const REDIS_DEDUP_TTL_SECONDS = 6 * 60 * 60; // 6 hours
const MAX_CONSECUTIVE_FAILURES = 3;

type AccountRefreshOutcome = "refreshed" | "errored" | "skipped";

type TokenRefreshAccount = {
	id: string;
	user_id?: string | null | undefined;
	username: string | null;
	threads_access_token_encrypted: string;
	updated_at: string | null;
};

type InstagramTokenRefreshAccount = {
	id: string;
	user_id?: string | null | undefined;
	username: string | null;
	instagram_access_token_encrypted: string;
	login_type?: string | null | undefined;
	updated_at: string | null;
};

type RefreshWorkerResult = {
	kind: AccountRefreshOutcome;
};

/**
 * Both helpers below delegate to the canonical Meta error classifier in
 * `metaErrors.ts`. That module is the single source of truth for code-based
 * classification (transient code=1/2, auth code=190/102, rate-limit code=4/32/613).
 *
 * Meta returns transients with the SAME envelope as auth errors
 * (`{ error: { code: 1, type: 'OAuthException' } }` for their 500), so we
 * MUST classify by code, not by message substring. See CLAUDE.md rule #7.
 */
function extractMetaError(errorData: Record<string, unknown>): {
	code?: number | undefined;
	error_subcode?: number | undefined;
	type?: string | undefined;
	message?: string | undefined;
} {
	const errorObj = errorData?.error as
		| Record<string, unknown>
		| null
		| undefined;
	if (!errorObj) {
		return { message: String(errorData?.message || errorData || "") };
	}
	return {
		code: typeof errorObj.code === "number" ? errorObj.code : undefined,
		error_subcode:
			typeof errorObj.error_subcode === "number"
				? errorObj.error_subcode
				: undefined,
		type: typeof errorObj.type === "string" ? errorObj.type : undefined,
		message:
			typeof errorObj.message === "string" ? errorObj.message : undefined,
	};
}

function isMetaTransient(errorData: Record<string, unknown>): boolean {
	return isTransientMetaError(extractMetaError(errorData));
}

function isAuthError(errorData: Record<string, unknown>): boolean {
	return isMetaAuthErrorClassified(extractMetaError(errorData));
}

/**
 * Handle a refresh failure: increment consecutive_refresh_failures,
 * and if it hits the threshold, deactivate + flag needs_reauth + notify user.
 */
async function handleRefreshFailure(
	// biome-ignore lint/suspicious/noExplicitAny: dynamic Supabase client wrapper requires any for table-agnostic operations
	db: { from: (table: string) => any },
	table: "accounts" | "instagram_accounts",
	accountId: string,
	userId: string | undefined,
	username: string,
	_errorMsg: string,
	isAuth: boolean,
	isTransient = false,
): Promise<void> {
	try {
		// Get current failure count
		const { data: row } = await db
			.from(table)
			.select("consecutive_refresh_failures, user_id")
			.eq("id", accountId)
			.maybeSingle();

		// Transient errors (network timeout, Meta 500, rate limit) should not
		// count toward the re-auth threshold — the token itself is likely fine.
		if (isTransient) {
			if ((row?.consecutive_refresh_failures || 0) > 0) {
				await db
					.from(table)
					.update({
						consecutive_refresh_failures: 0,
						updated_at: new Date().toISOString(),
					})
					.eq("id", accountId);
			}
			return;
		}

		const currentFailures = (row?.consecutive_refresh_failures || 0) + 1;
		const effectiveUserId = userId || row?.user_id;

		const updateData: Record<string, unknown> = {
			consecutive_refresh_failures: currentFailures,
			updated_at: new Date().toISOString(),
		};

		// If auth error or too many failures → flag for re-auth and deactivate
		if (isAuth || currentFailures >= MAX_CONSECUTIVE_FAILURES) {
			updateData.needs_reauth = true;
			updateData.is_active = false;
			updateData.status = "needs_reauth";

			logger.warn(
				`[Token Refresh] ${isAuth ? "Auth error" : "Max failures reached"} — deactivating ${table} @${username}`,
				{ accountId, failures: currentFailures },
			);

			// Send user notification (best-effort, 5s timeout to avoid blocking refresh loop)
			if (effectiveUserId) {
				try {
					const { deliverNotification } = await import(
						"../deliverNotification.js"
					);
					const platform = table === "accounts" ? "Threads" : "Instagram";
					await Promise.race([
						deliverNotification({
							userId: effectiveUserId,
							type: "token_reauth_needed",
							title: `${platform} account needs reconnection`,
							message: `Your ${platform} account @${username} has been disconnected because the access token expired. Please reconnect it in Settings.`,
							data: {
								accountId,
								platform: platform.toLowerCase(),
								reason: isAuth ? "auth_error" : "max_failures",
							},
						}),
						new Promise((_, reject) =>
							setTimeout(
								() => reject(new Error("Notification timeout (5s)")),
								5000,
							),
						),
					]);
				} catch (notifErr) {
					logger.warn("Failed to notify user about account deactivation", {
						accountId,
						userId: effectiveUserId,
						error: String(notifErr),
					});
				}
			}
		}

		const { error: updateErr } = await db
			.from(table)
			.update(updateData)
			.eq("id", accountId);
		if (updateErr) {
			logger.error(
				"[token-refresh] Failed to update refresh failure tracking",
				{
					table,
					accountId,
					error: updateErr.message,
				},
			);
		}
	} catch (err) {
		logger.error("[Token Refresh] Failed to handle refresh failure", {
			table,
			accountId,
			error: String(err),
		});
	}
}

/**
 * Reset consecutive failure counter on successful refresh.
 */
async function resetFailureCount(
	// biome-ignore lint/suspicious/noExplicitAny: dynamic Supabase client wrapper requires any for table-agnostic operations
	db: { from: (table: string) => any },
	table: "accounts" | "instagram_accounts",
	accountId: string,
): Promise<void> {
	try {
		const { data: row } = await db
			.from(table)
			.select("consecutive_refresh_failures")
			.eq("id", accountId)
			.maybeSingle();

		if (row?.consecutive_refresh_failures > 0) {
			await db
				.from(table)
				.update({ consecutive_refresh_failures: 0 })
				.eq("id", accountId);
		}
	} catch (err) {
		logger.debug("Failed to reset refresh failure counter", {
			accountId,
			table,
			error: String(err),
		});
	}
}

// ============================================================================
// Core refresh logic
// ============================================================================

interface RefreshResult {
	threadsRefreshed: number;
	threadsErrors: number;
	threadsSkipped: number;
	igRefreshed: number;
	igErrors: number;
	igSkipped: number;
	total: number;
}

export async function refreshAllTokens(): Promise<RefreshResult> {
	const { decrypt, encrypt, needsUpgrade } = await import("../encryption.js");
	const { getRedis } = await import("../redis.js");

	const db = getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.tokenRefresh);
	const redis = getRedis();

	// Pre-flight: proactive alert when many tokens expire within 48h
	try {
		const in48h = new Date(Date.now() + 48 * 60 * 60 * 1000).toISOString();
		const now = new Date().toISOString();

		const [{ count: urgentThreads }, { count: urgentIg }] = await Promise.all([
			neqOrNull(
				db
					.from("accounts")
					.select("id", { count: "exact", head: true })
					.gt("token_expires_at", now)
					.lt("token_expires_at", in48h)
					.eq("is_active", true),
				"needs_reauth",
				true,
			),
			db
				.from("instagram_accounts")
				.select("id", { count: "exact", head: true })
				.gt("token_expires_at", now)
				.lt("token_expires_at", in48h)
				.eq("is_active", true),
		]);

		const totalUrgent = (urgentThreads ?? 0) + (urgentIg ?? 0);
		if (totalUrgent >= 5) {
			const { alert, AlertLevel } = await import("../alerting.js");
			await alert(
				AlertLevel.WARN,
				`Token expiry cluster: ${totalUrgent} tokens expire within 48h`,
				{
					threads: urgentThreads ?? 0,
					instagram: urgentIg ?? 0,
					action:
						"Check token-refresh cron health. Verify Meta refresh endpoint is responding.",
				},
			);
		}
	} catch (err) {
		logger.warn(
			"[token-refresh] Pre-flight expiry check failed (non-blocking)",
			{
				error: String(err),
			},
		);
	}

	// Guardrail: any already-expired token must be marked needs_reauth, even
	// when it is older than the refresh lookback window. This keeps publish and
	// sync paths from silently skipping accounts forever.
	try {
		const now = new Date().toISOString();
		const [threadsExpired, igExpired] = await Promise.all([
			db
				.from("accounts")
				.update({
					needs_reauth: true,
					status: "needs_reauth",
					is_active: false,
					updated_at: now,
				})
				.lt("token_expires_at", now)
				.eq("needs_reauth", false)
				.select("id"),
			db
				.from("instagram_accounts")
				.update({
					needs_reauth: true,
					status: "needs_reauth",
					is_active: false,
					updated_at: now,
				})
				.lt("token_expires_at", now)
				.eq("needs_reauth", false)
				.select("id"),
		]);
		if (threadsExpired.error || igExpired.error) {
			throw new Error(
				[
					threadsExpired.error
						? `threads=${threadsExpired.error.message}`
						: null,
					igExpired.error ? `instagram=${igExpired.error.message}` : null,
				]
					.filter(Boolean)
					.join("; "),
			);
		}
		const repaired =
			(threadsExpired.count ?? threadsExpired.data?.length ?? 0) +
			(igExpired.count ?? igExpired.data?.length ?? 0);
		if (repaired > 0) {
			logger.warn("[token-refresh] Auto-flagged already-expired tokens", {
				threads: threadsExpired.count ?? threadsExpired.data?.length ?? 0,
				instagram: igExpired.count ?? igExpired.data?.length ?? 0,
			});
		}
	} catch (err) {
		logger.error("[token-refresh] Expired-token guard failed", {
			error: String(err),
		});
	}

	// 10-day window (widened from 7d) — safety net for tokens that daily-maintenance missed.
	// Daily-maintenance handles 5-day window; this catches stragglers + accounts added late.
	const tenDaysFromNow = new Date(
		Date.now() + 10 * 24 * 60 * 60 * 1000,
	).toISOString();
	// Include tokens expired up to 24h ago (catches tokens that expired between cron runs)
	const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

	let threadsRefreshed = 0;
	let threadsErrors = 0;
	let threadsSkipped = 0;
	let igRefreshed = 0;
	let igErrors = 0;
	let igSkipped = 0;
	const refreshStartTime = Date.now();
	const limit = createConcurrencyLimiter(TOKEN_CONCURRENCY_LIMIT);

	const summarizeResults = (results: RefreshWorkerResult[]) => {
		return results.reduce(
			(summary, result) => {
				summary[result.kind]++;
				return summary;
			},
			{ refreshed: 0, errored: 0, skipped: 0 } as Record<
				AccountRefreshOutcome,
				number
			>,
		);
	};

	const processThreadsAccount = async (
		account: TokenRefreshAccount,
	): Promise<RefreshWorkerResult> => {
		if (!hasTimeBudget(refreshStartTime)) {
			logger.warn(
				`[Token Refresh] Skipping Threads @${account.username} — time budget exhausted`,
				{ accountId: account.id },
			);
			return { kind: "skipped" };
		}

		// Redis dedup: skip if already refreshed by daily-maintenance
		const dedupKey = `${REDIS_DEDUP_PREFIX}${account.id}`;
		try {
			const alreadyRefreshed = await redis.get(dedupKey);
			if (alreadyRefreshed) {
				logger.info(
					`[Token Refresh] Skipping Threads @${account.username} — already refreshed (dedup)`,
				);
				return { kind: "skipped" };
			}
		} catch (redisErr) {
			// Redis failure is non-fatal — proceed with refresh
			logger.warn("[Token Refresh] Redis dedup check failed", {
				accountId: account.id,
				error: String(redisErr),
			});
		}

		try {
			const currentToken = decrypt(account.threads_access_token_encrypted);

			const refreshResponse = await fetch(
				`https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=${encodeURIComponent(currentToken)}`,
				{
					signal: AbortSignal.timeout(10000),
				},
			);

			const refreshData = await refreshResponse.json();

			if (!refreshResponse.ok || refreshData.error) {
				const errorMsg = String(
					refreshData?.error?.message || refreshData?.error || refreshData,
				);
				logger.error(
					`[Token Refresh] Threads refresh failed for ${account.username}`,
					{ error: errorMsg },
				);

				// Track failure + auto-deactivate on auth errors or consecutive
				// failures. Meta transient (code=1 OAuthException) is a server-side
				// 500 — do NOT increment consecutive count or mark needs_reauth.
				const isAuth = isAuthError(refreshData);
				const isTransient = isMetaTransient(refreshData);
				await handleRefreshFailure(
					db,
					"accounts",
					account.id,
					account.user_id ?? undefined,
					account.username || account.id,
					errorMsg,
					isAuth,
					!isAuth && isTransient,
				);

				// Discord alert
				await alertTokenRefreshFailure(
					"threads",
					account.username || account.id,
					errorMsg,
				);
				return { kind: "errored" };
			}

			let newEncryptedToken: string;
			try {
				newEncryptedToken = encrypt(refreshData.access_token as string);
			} catch (encryptErr) {
				logger.error(
					`[Token Refresh] Encryption failed for Threads @${account.username}`,
					{ error: String(encryptErr) },
				);
				await handleRefreshFailure(
					db,
					"accounts",
					account.id,
					account.user_id ?? undefined,
					account.username || account.id,
					`Encryption failed: ${String(encryptErr)}`,
					false,
				);
				return { kind: "errored" };
			}
			const expiresIn = refreshData.expires_in || 5184000; // 60 days default

			const { data: updatedRows } = await db
				.from("accounts")
				.update({
					threads_access_token_encrypted: newEncryptedToken,
					token_expires_at: new Date(
						Date.now() + expiresIn * 1000,
					).toISOString(),
					updated_at: new Date().toISOString(),
				})
				.eq("id", account.id)
				.eq("updated_at", account.updated_at)
				.select("id");
			const count = updatedRows?.length ?? 0;

			if (count === 0) {
				logger.info(
					`[Token Refresh] Skipping Threads @${account.username} — row updated by another process`,
				);
				return { kind: "skipped" };
			}

			await verifyThreadsScopes(
				refreshData.access_token as string,
				account.id,
				db,
				logger,
			);
			await resetFailureCount(db, "accounts", account.id);
			logger.info(
				`[Token Refresh] Threads token refreshed for ${account.username}`,
			);

			// Set Redis dedup key so daily-maintenance skips this account
			try {
				await redis.set(dedupKey, "1", {
					ex: REDIS_DEDUP_TTL_SECONDS,
				});
			} catch (redisSetErr) {
				logger.warn("[Token Refresh] Redis dedup set failed", {
					accountId: account.id,
					error: String(redisSetErr),
				});
			}
			return { kind: "refreshed" };
		} catch (err) {
			const errorMsg = String(err);
			logger.error(
				`[Token Refresh] Threads refresh error for ${account.username}`,
				{ error: errorMsg },
			);

			// Track failure — outer catch is network/timeout, always transient
			await handleRefreshFailure(
				db,
				"accounts",
				account.id,
				account.user_id ?? undefined,
				account.username || account.id,
				errorMsg,
				false,
				true,
			);

			// Discord alert
			await alertTokenRefreshFailure(
				"threads",
				account.username || account.id,
				errorMsg,
			);
			return { kind: "errored" };
		}
	};

	const processInstagramAccount = async (
		account: InstagramTokenRefreshAccount,
	): Promise<RefreshWorkerResult> => {
		if (!hasTimeBudget(refreshStartTime)) {
			logger.warn(
				`[Token Refresh] Skipping IG @${account.username} — time budget exhausted`,
				{ accountId: account.id },
			);
			return { kind: "skipped" };
		}

		// Redis dedup: skip if already refreshed by daily-maintenance
		const dedupKey = `${REDIS_DEDUP_PREFIX}ig_${account.id}`;
		try {
			const alreadyRefreshed = await redis.get(dedupKey);
			if (alreadyRefreshed) {
				logger.info(
					`[Token Refresh] Skipping IG @${account.username} — already refreshed (dedup)`,
				);
				return { kind: "skipped" };
			}
		} catch (redisErr) {
			logger.warn("[Token Refresh] Redis dedup check failed", {
				accountId: account.id,
				error: String(redisErr),
			});
		}

		try {
			const currentToken = decrypt(account.instagram_access_token_encrypted);
			const loginType = account.login_type || "instagram";

			const { refreshTokenByLoginType } = await import("../tokenRefresh.js");
			const refreshResult = await refreshTokenByLoginType(
				currentToken,
				loginType,
			);
			const refreshData = refreshResult.data;

			if (!refreshResult.ok || refreshData.error) {
				const errorMsg = String(
					refreshData?.error?.message || refreshData?.error || refreshData,
				);
				logger.error(
					`[Token Refresh] IG refresh failed for ${account.username}`,
					{ error: errorMsg },
				);

				// Track failure + auto-deactivate on auth errors or consecutive failures
				const isAuth = isAuthError(refreshData);
				const isTransient = isMetaTransient(refreshData);
				await handleRefreshFailure(
					db,
					"instagram_accounts",
					account.id,
					account.user_id ?? undefined,
					account.username || account.id,
					errorMsg,
					isAuth,
					!isAuth && isTransient,
				);

				// Discord alert
				await alertTokenRefreshFailure(
					"instagram",
					account.username || account.id,
					errorMsg,
				);
				return { kind: "errored" };
			}

			let newEncryptedToken: string;
			try {
				newEncryptedToken = encrypt(refreshData.access_token as string);
			} catch (encryptErr) {
				logger.error(
					`[Token Refresh] Encryption failed for IG @${account.username}`,
					{ error: String(encryptErr) },
				);
				await handleRefreshFailure(
					db,
					"instagram_accounts",
					account.id,
					account.user_id ?? undefined,
					account.username || account.id,
					`Encryption failed: ${String(encryptErr)}`,
					false,
				);
				return { kind: "errored" };
			}
			const expiresIn = refreshData.expires_in || 5184000;

			const updateData: Record<string, unknown> = {
				instagram_access_token_encrypted: newEncryptedToken,
				token_expires_at: new Date(Date.now() + expiresIn * 1000).toISOString(),
				updated_at: new Date().toISOString(),
			};

			// NOTE: Do NOT overwrite facebook_page_access_token_encrypted here.
			// The refreshed token is a user token (from fb_exchange_token grant).
			// Page tokens are separate long-lived tokens obtained via /{page-id}?fields=access_token
			// and should only be set during the initial OAuth callback.

			const { data: igUpdatedRows } = await db
				.from("instagram_accounts")
				.update(updateData)
				.eq("id", account.id)
				.eq("updated_at", account.updated_at)
				.select("id");
			const igCount = igUpdatedRows?.length ?? 0;

			if (igCount === 0) {
				logger.info(
					`[Token Refresh] Skipping IG @${account.username} — row updated by another process`,
				);
				return { kind: "skipped" };
			}

			await verifyInstagramScopes(
				refreshData.access_token as string,
				account.id,
				loginType,
				db,
				logger,
			);
			await resetFailureCount(db, "instagram_accounts", account.id);
			logger.info(`[Token Refresh] IG token refreshed for ${account.username}`);

			// Set Redis dedup key so daily-maintenance skips this account
			try {
				await redis.set(dedupKey, "1", {
					ex: REDIS_DEDUP_TTL_SECONDS,
				});
			} catch (redisSetErr) {
				logger.warn("[Token Refresh] Redis dedup set failed", {
					accountId: account.id,
					error: String(redisSetErr),
				});
			}
			return { kind: "refreshed" };
		} catch (err) {
			const errorMsg = String(err);
			logger.error(`[Token Refresh] IG refresh error for ${account.username}`, {
				error: errorMsg,
			});

			// Track failure — outer catch is network/timeout, always transient
			await handleRefreshFailure(
				db,
				"instagram_accounts",
				account.id,
				account.user_id ?? undefined,
				account.username || account.id,
				errorMsg,
				false,
				true,
			);

			// Discord alert
			await alertTokenRefreshFailure(
				"instagram",
				account.username || account.id,
				errorMsg,
			);
			return { kind: "errored" };
		}
	};

	// 1. Refresh Threads tokens
	try {
		const threadsBase = db
			.from("accounts")
			.select(
				"id, user_id, username, threads_access_token_encrypted, token_expires_at, updated_at",
			)
			.eq("is_active", true)
			.not("threads_access_token_encrypted", "is", null)
			.or(
				`token_expires_at.is.null,and(token_expires_at.lte.${tenDaysFromNow},token_expires_at.gte.${oneDayAgo})`,
			);
		const { data: threadsAccounts } = await neqOrNull(
			threadsBase,
			"needs_reauth",
			true,
		);

		if (threadsAccounts && threadsAccounts.length > 0) {
			logger.info(
				`[Token Refresh] Found ${threadsAccounts.length} Threads tokens to refresh`,
			);

			const threadsResults = await Promise.all(
				(threadsAccounts as TokenRefreshAccount[]).map((account) =>
					limit(() => processThreadsAccount(account)),
				),
			);
			const threadsSummary = summarizeResults(threadsResults);
			threadsRefreshed = threadsSummary.refreshed;
			threadsErrors = threadsSummary.errored;
			threadsSkipped = threadsSummary.skipped;
		}
	} catch (err) {
		logger.error("[Token Refresh] Threads query error", {
			error: String(err),
		});
	}

	// 2. Refresh Instagram tokens
	try {
		const igBase = db
			.from("instagram_accounts")
			.select(
				"id, user_id, username, instagram_access_token_encrypted, facebook_page_access_token_encrypted, login_type, token_expires_at, updated_at",
			)
			.eq("is_active", true)
			.not("instagram_access_token_encrypted", "is", null)
			.or(
				`token_expires_at.is.null,and(token_expires_at.lte.${tenDaysFromNow},token_expires_at.gte.${oneDayAgo})`,
			);
		const { data: igAccounts } = await neqOrNull(igBase, "needs_reauth", true);

		if (igAccounts && igAccounts.length > 0) {
			logger.info(
				`[Token Refresh] Found ${igAccounts.length} Instagram tokens to refresh`,
			);

			const igResults = await Promise.all(
				(igAccounts as InstagramTokenRefreshAccount[]).map((account) =>
					limit(() => processInstagramAccount(account)),
				),
			);
			const igSummary = summarizeResults(igResults);
			igRefreshed = igSummary.refreshed;
			igErrors = igSummary.errored;
			igSkipped = igSummary.skipped;
		}
	} catch (err) {
		logger.error("[Token Refresh] IG query error", {
			error: String(err),
		});
	}

	// =========================================================================
	// 3. Recovery probe: attempt to refresh tokens on needs_reauth accounts
	// where token_expires_at > NOW() (our system flagged them, but the token
	// may still be valid — Meta didn't necessarily revoke it).
	// If refresh succeeds → clear all flags, account is active again.
	// If refresh fails with auth error → set token_expires_at=NOW() so we
	// stop probing (confirmed dead). Max 10 per run.
	// =========================================================================
	let recovered = 0;
	let probesFailed = 0;
	try {
		const { data: reauthAccounts } = await db
			.from("accounts")
			.select(
				"id, user_id, username, threads_access_token_encrypted, token_expires_at, updated_at",
			)
			.eq("needs_reauth", true)
			.not("threads_access_token_encrypted", "is", null)
			.gt("token_expires_at", new Date().toISOString())
			.limit(50);

		if (reauthAccounts && reauthAccounts.length > 0) {
			logger.info(
				`[Token Refresh] Probing ${reauthAccounts.length} needs_reauth accounts with non-expired tokens`,
			);

			for (const account of reauthAccounts) {
				try {
					const currentToken = decrypt(account.threads_access_token_encrypted);
					const refreshResponse = await fetch(
						`https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=${encodeURIComponent(currentToken)}`,
						{ signal: AbortSignal.timeout(10000) },
					);
					const refreshData = await refreshResponse.json();

					if (refreshResponse.ok && refreshData.access_token) {
						// Token still works — recover the account
						// Optimistic lock: only update if still needs_reauth (prevents race with OAuth reconnect)
						const newEncryptedToken = encrypt(
							refreshData.access_token as string,
						);
						const expiresIn = refreshData.expires_in || 5184000;

						await db
							.from("accounts")
							.update({
								threads_access_token_encrypted: newEncryptedToken,
								token_expires_at: new Date(
									Date.now() + expiresIn * 1000,
								).toISOString(),
								needs_reauth: false,
								is_active: true,
								status: "active",
								consecutive_refresh_failures: 0,
								updated_at: new Date().toISOString(),
							})
							.eq("id", account.id)
							.eq("needs_reauth", true);

						recovered++;
						logger.info(
							`[Token Refresh] RECOVERED needs_reauth account @${account.username}`,
							{ accountId: account.id },
						);
					} else {
						// Token truly dead — mark token_expires_at=NOW() so we stop probing
						// Optimistic lock: only update if still needs_reauth
						await db
							.from("accounts")
							.update({
								token_expires_at: new Date().toISOString(),
								updated_at: new Date().toISOString(),
							})
							.eq("id", account.id)
							.eq("needs_reauth", true);

						probesFailed++;
						logger.info(
							`[Token Refresh] Probe confirmed dead token for @${account.username}`,
							{
								accountId: account.id,
								error: String(
									refreshData?.error?.message ||
										refreshData?.error ||
										"unknown",
								),
							},
						);
					}
				} catch (probeErr) {
					// Network/decrypt error — don't mark as dead, retry next run
					probesFailed++;
					logger.warn(`[Token Refresh] Probe error for @${account.username}`, {
						accountId: account.id,
						error: String(probeErr),
					});
				}
			}
		}

		// Same for Instagram accounts
		const { data: reauthIgAccounts } = await db
			.from("instagram_accounts")
			.select(
				"id, user_id, username, instagram_access_token_encrypted, facebook_page_access_token_encrypted, login_type, token_expires_at, updated_at",
			)
			.eq("needs_reauth", true)
			.not("instagram_access_token_encrypted", "is", null)
			.gt("token_expires_at", new Date().toISOString())
			.limit(50);

		if (reauthIgAccounts && reauthIgAccounts.length > 0) {
			logger.info(
				`[Token Refresh] Probing ${reauthIgAccounts.length} needs_reauth IG accounts with non-expired tokens`,
			);

			for (const account of reauthIgAccounts) {
				try {
					const currentToken = decrypt(
						account.instagram_access_token_encrypted,
					);
					const loginType = account.login_type || "instagram";

					// IG via instagram-login uses GET (Meta API constraint, see tokenRefresh.ts).
					// FB-login uses POST + form body so the client_secret never appears in
					// URL/proxy/access logs.
					let refreshResponse: Response;
					if (loginType === "facebook") {
						refreshResponse = await fetch(
							`https://graph.facebook.com/v25.0/oauth/access_token`,
							{
								method: "POST",
								headers: {
									"Content-Type": "application/x-www-form-urlencoded",
								},
								body: new URLSearchParams({
									grant_type: "fb_exchange_token",
									client_id: process.env.FACEBOOK_APP_ID || "",
									client_secret: process.env.FACEBOOK_APP_SECRET || "",
									fb_exchange_token: currentToken,
								}),
								signal: AbortSignal.timeout(10000),
							},
						);
					} else {
						refreshResponse = await fetch(
							`https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=${encodeURIComponent(currentToken)}`,
							{
								signal: AbortSignal.timeout(10000),
							},
						);
					}
					const refreshData = await refreshResponse.json();

					if (refreshResponse.ok && refreshData.access_token) {
						// Optimistic lock: only update if still needs_reauth (prevents race with OAuth reconnect)
						const newEncryptedToken = encrypt(
							refreshData.access_token as string,
						);
						const expiresIn = refreshData.expires_in || 5184000;

						await db
							.from("instagram_accounts")
							.update({
								instagram_access_token_encrypted: newEncryptedToken,
								token_expires_at: new Date(
									Date.now() + expiresIn * 1000,
								).toISOString(),
								needs_reauth: false,
								is_active: true,
								status: "active",
								consecutive_refresh_failures: 0,
								updated_at: new Date().toISOString(),
							})
							.eq("id", account.id)
							.eq("needs_reauth", true);

						recovered++;
						logger.info(
							`[Token Refresh] RECOVERED needs_reauth IG account @${account.username}`,
							{ accountId: account.id },
						);
					} else {
						// Optimistic lock: only update if still needs_reauth
						await db
							.from("instagram_accounts")
							.update({
								token_expires_at: new Date().toISOString(),
								updated_at: new Date().toISOString(),
							})
							.eq("id", account.id)
							.eq("needs_reauth", true);

						probesFailed++;
						logger.info(
							`[Token Refresh] Probe confirmed dead IG token for @${account.username}`,
							{
								accountId: account.id,
								error: String(
									refreshData?.error?.message ||
										refreshData?.error ||
										"unknown",
								),
							},
						);
					}
				} catch (probeErr) {
					probesFailed++;
					logger.warn(
						`[Token Refresh] IG probe error for @${account.username}`,
						{
							accountId: account.id,
							error: String(probeErr),
						},
					);
				}
			}
		}
	} catch (err) {
		logger.error("[Token Refresh] Recovery probe query error", {
			error: String(err),
		});
	}

	const total = threadsRefreshed + igRefreshed;
	const totalErrors = threadsErrors + igErrors;
	const totalSkipped = threadsSkipped + igSkipped;

	// =========================================================================
	// PBKDF2 v1 → v2 migration (600k iterations, OWASP 2023)
	// Re-encrypt up to 100 legacy v1 tokens per run. Tokens already upgraded
	// by the refresh loop above are skipped automatically (needsUpgrade = false).
	// At ~62 active accounts this completes in a single run.
	// =========================================================================
	const migrationStats = await migrateV1Tokens(
		db,
		decrypt,
		encrypt,
		needsUpgrade,
	);

	logger.info("[Token Refresh] Complete", {
		threadsRefreshed,
		threadsErrors,
		threadsSkipped,
		igRefreshed,
		igErrors,
		igSkipped,
		total,
		totalErrors,
		totalSkipped,
		recovered,
		probesFailed,
		migrationUpgraded: migrationStats.upgraded,
		migrationErrors: migrationStats.errors,
		migrationRemaining: migrationStats.remaining,
	});

	return {
		threadsRefreshed,
		threadsErrors,
		threadsSkipped,
		igRefreshed,
		igErrors,
		igSkipped,
		total,
	};
}

const MIGRATION_BATCH_SIZE = 100;

/**
 * Lazily re-encrypts v1 tokens (100k PBKDF2 iterations) to v2 (600k iterations).
 * Processes up to MIGRATION_BATCH_SIZE accounts per cron run to stay within
 * the 60s maxDuration budget. Safe to run repeatedly — already-upgraded tokens
 * are excluded by the DB query.
 *
 * In-flight safety: Supabase .update() is atomic at the row level. If a token
 * is being used concurrently, the active request holds either the old v1 or new
 * v2 value — both are valid since decrypt() handles both formats. The existing
 * retry-on-cache-eviction logic in decrypt() covers any edge-case race.
 */
async function migrateV1Tokens(
	db: ReturnType<typeof getPrivilegedSupabaseAny>,
	decryptFn: (s: string) => string,
	encryptFn: (s: string) => string,
	needsUpgradeFn: (s: string) => boolean,
): Promise<{ upgraded: number; errors: number; remaining: number }> {
	let upgraded = 0;
	let errors = 0;

	// ── Threads accounts ──────────────────────────────────────────────────────
	const { data: threadAccounts, error: taErr } = await db
		.from("accounts")
		.select("id, threads_access_token_encrypted")
		.not("threads_access_token_encrypted", "is", null)
		// v2 tokens start with "v2:" — filter them out using not.like
		.filter("threads_access_token_encrypted", "not.like", "v2:%")
		.limit(MIGRATION_BATCH_SIZE);

	if (taErr) {
		logger.warn("[Token Migration] Failed to query Threads accounts", {
			error: taErr.message,
		});
	} else {
		for (const account of threadAccounts ?? []) {
			try {
				if (!needsUpgradeFn(account.threads_access_token_encrypted)) continue;
				const plaintext = decryptFn(account.threads_access_token_encrypted);
				const upgraded_token = encryptFn(plaintext);
				const { error: updateErr } = await db
					.from("accounts")
					.update({ threads_access_token_encrypted: upgraded_token })
					.eq("id", account.id);
				if (updateErr) throw new Error(updateErr.message);
				upgraded++;
			} catch (err) {
				errors++;
				logger.warn("[Token Migration] Failed to upgrade Threads token", {
					accountId: account.id,
					error: err instanceof Error ? err.message : String(err),
				});
			}
		}
	}

	// ── Instagram accounts ────────────────────────────────────────────────────
	const remaining_budget = MIGRATION_BATCH_SIZE - (threadAccounts?.length ?? 0);
	if (remaining_budget > 0) {
		const { data: igAccounts, error: iaErr } = await db
			.from("instagram_accounts")
			.select("id, instagram_access_token_encrypted")
			.not("instagram_access_token_encrypted", "is", null)
			.filter("instagram_access_token_encrypted", "not.like", "v2:%")
			.limit(remaining_budget);

		if (iaErr) {
			logger.warn("[Token Migration] Failed to query IG accounts", {
				error: iaErr.message,
			});
		} else {
			for (const account of igAccounts ?? []) {
				try {
					if (!needsUpgradeFn(account.instagram_access_token_encrypted))
						continue;
					const plaintext = decryptFn(account.instagram_access_token_encrypted);
					const upgraded_token = encryptFn(plaintext);
					const { error: updateErr } = await db
						.from("instagram_accounts")
						.update({ instagram_access_token_encrypted: upgraded_token })
						.eq("id", account.id);
					if (updateErr) throw new Error(updateErr.message);
					upgraded++;
				} catch (err) {
					errors++;
					logger.warn("[Token Migration] Failed to upgrade IG token", {
						accountId: account.id,
						error: err instanceof Error ? err.message : String(err),
					});
				}
			}
		}
	}

	// Approximate remaining count (post-migration) for logging visibility
	const remaining = Math.max(
		0,
		(threadAccounts?.length ?? 0) - upgraded + errors,
	);

	if (upgraded > 0 || errors > 0) {
		logger.info("[Token Migration] PBKDF2 v1→v2 pass complete", {
			upgraded,
			errors,
			remaining,
		});
	}

	// Alert if the migration is stuck: tokens were picked up but none upgraded.
	// Happens when a legacy row has malformed ciphertext (truncated, wrong key
	// version, etc) that can't be decrypted. Flags a manual-intervention need.
	if (errors > 0 && upgraded === 0) {
		try {
			const { alertWarn } = await import("../alerting.js");
			await alertWarn(
				`Token migration stuck: ${errors} legacy v1 tokens fail to decrypt`,
				{
					errors,
					upgraded: 0,
					action:
						"Manual intervention required — malformed ciphertext or key rotation mismatch. Check logs for failing account IDs; re-auth the accounts or set status=needs_reauth.",
				},
			);
		} catch {
			// Non-blocking — alerting failure shouldn't crash the cron
		}
	}

	return { upgraded, errors, remaining };
}
