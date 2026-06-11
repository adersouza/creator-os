/**
 * Phase 2: Refresh Tokens (Threads + Instagram)
 * Refreshes expiring tokens within a 72-hour window, auto-flags expired tokens,
 * tracks consecutive failures, and deactivates accounts after threshold.
 */

import {
	isAuthError as classifiedIsAuthError,
	isTransientMetaError,
} from "../../metaErrors.js";
import { neqOrNull } from "../../supabaseSafe.js";
import type {
	Account,
	InstagramAccount,
	Logger,
	PhaseMetadata,
	RefreshResult,
	ThreadsTokenResponse,
	TypedSupabaseClient,
} from "./shared.js";
import {
	createConcurrencyLimiter,
	HOURS_BEFORE_EXPIRY,
	hasTimeBudget,
	TOKEN_CONCURRENCY_LIMIT,
} from "./shared.js";

const MAX_CONSECUTIVE_FAILURES = 3;

type MetaErrorShape = {
	code?: number | undefined;
	error_subcode?: number | undefined;
	type?: string | undefined;
	message?: string | undefined;
};

/**
 * Classify a refresh failure. Prefers the structured Meta error envelope
 * (code/subcode/type/message) when available; falls back to message-only.
 *
 * Returns whether the failure is transient (Meta hiccup — should NOT bump
 * consecutive_refresh_failures) vs auth (token dead — flag for reauth).
 */
function classifyRefreshFailure(
	metaError: MetaErrorShape | undefined,
	errorMsg: string,
): { isAuth: boolean; isTransient: boolean } {
	const errInput: string | MetaErrorShape =
		metaError && (metaError.code !== undefined || metaError.message !== undefined)
			? metaError
			: errorMsg;
	const isTransient = isTransientMetaError(errInput);
	const isAuth = !isTransient && classifiedIsAuthError(errInput);
	return { isAuth, isTransient };
}

/**
 * Track refresh failures and auto-deactivate after threshold.
 */
async function trackRefreshFailure(
	supabase: TypedSupabaseClient,
	table: "accounts" | "instagram_accounts",
	accountId: string,
	userId: string | undefined,
	username: string,
	errorMsg: string,
	logger: Logger,
	metaError?: MetaErrorShape | undefined,
): Promise<void> {
	try {
		const { isAuth, isTransient } = classifyRefreshFailure(metaError, errorMsg);

		const { data: row } = await supabase
			.from(table)
			.select("consecutive_refresh_failures, user_id")
			.eq("id", accountId)
			.maybeSingle();

		// Transient (Meta 500, network timeout, rate limit): do NOT bump the
		// failure counter — the token is likely fine. Reset any stale count so
		// a previous transient streak doesn't tip a healthy token over the edge.
		if (isTransient) {
			logger.warn(
				`[daily-maintenance] Transient refresh failure for ${table} @${username} — counter not bumped`,
				{ accountId, error: errorMsg.slice(0, 200) },
			);
			if ((row?.consecutive_refresh_failures || 0) > 0) {
				try {
					// biome-ignore lint/suspicious/noExplicitAny: dynamic Supabase table name requires any cast
					await (supabase.from(table) as any)
						.update({
							consecutive_refresh_failures: 0,
							updated_at: new Date().toISOString(),
						})
						.eq("id", accountId);
				} catch (resetErr) {
					logger.debug(
						"[daily-maintenance] Failed to reset transient failure counter",
						{ table, accountId, error: String(resetErr) },
					);
				}
			}
			return;
		}

		const currentFailures = (row?.consecutive_refresh_failures || 0) + 1;
		const effectiveUserId = userId || row?.user_id;

		const updateData: Record<string, unknown> = {
			consecutive_refresh_failures: currentFailures,
			updated_at: new Date().toISOString(),
		};

		if (isAuth || currentFailures >= MAX_CONSECUTIVE_FAILURES) {
			updateData.needs_reauth = true;
			updateData.is_active = false;
			updateData.status = "needs_reauth";

			logger.warn(
				`[daily-maintenance] ${isAuth ? "Auth error" : "Max failures"} — deactivating ${table} @${username}`,
				{ accountId, failures: currentFailures },
			);

			if (effectiveUserId) {
				try {
					const { deliverNotification } = await import(
						"../../deliverNotification.js"
					);
					const platform = table === "accounts" ? "Threads" : "Instagram";
					await deliverNotification({
						userId: effectiveUserId,
						type: "token_reauth_needed",
						title: `${platform} account needs reconnection`,
						message: `Your ${platform} account @${username} has been disconnected because the access token expired. Please reconnect it in Settings.`,
						data: { accountId, platform: platform.toLowerCase() },
					});
				} catch (notifErr) {
					logger.warn("Failed to deliver token reauth notification", {
						userId: effectiveUserId,
						accountId,
						error: String(notifErr),
					});
				}
			}
		}

		// biome-ignore lint/suspicious/noExplicitAny: dynamic Supabase table name requires any cast
		const { error: updateErr } = await (supabase.from(table) as any)
			.update(updateData)
			.eq("id", accountId);
		if (updateErr) {
			logger.error(
				"[daily-maintenance] Failed to update refresh failure tracking",
				{
					table,
					accountId,
					error: updateErr.message,
				},
			);
		}
	} catch (err) {
		logger.error("[daily-maintenance] Failed to track refresh failure", {
			table,
			accountId,
			error: String(err),
		});
	}
}

/**
 * Reset consecutive failure counter on successful refresh.
 */
async function resetRefreshFailures(
	supabase: TypedSupabaseClient,
	table: "accounts" | "instagram_accounts",
	accountId: string,
	logger: Logger,
): Promise<void> {
	try {
		// biome-ignore lint/suspicious/noExplicitAny: dynamic Supabase table name requires any cast
		await (supabase.from(table) as any)
			.update({ consecutive_refresh_failures: 0 })
			.eq("id", accountId)
			.gt("consecutive_refresh_failures", 0);
	} catch (err) {
		logger.debug("Failed to reset refresh failure counter", {
			table,
			accountId,
			error: String(err),
		});
	}
}

async function refreshThreadsToken(
	supabase: TypedSupabaseClient,
	account: Account,
	encrypt: (v: string) => string,
	decrypt: (v: string) => string,
	logger: Logger,
): Promise<RefreshResult> {
	const result: RefreshResult = {
		accountId: account.id,
		username: account.username,
		success: false,
	};

	try {
		if (!account.threads_access_token_encrypted) {
			result.error = "No encrypted token found";
			return result;
		}

		const currentToken = decrypt(account.threads_access_token_encrypted);
		const refreshUrl = `https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=${encodeURIComponent(currentToken)}`;
		const refreshResponse = await fetch(refreshUrl, {
			method: "GET",
			signal: AbortSignal.timeout(10000),
		});
		const refreshData = (await refreshResponse.json()) as ThreadsTokenResponse;

		if (!refreshResponse.ok || !refreshData.access_token) {
			result.error = refreshData.error?.message || "Refresh API failed";
			if (refreshData.error) {
				result.metaError = refreshData.error;
			}
			return result;
		}

		const encryptedToken = encrypt(refreshData.access_token);
		const newExpiresAt = new Date(
			Date.now() + (refreshData.expires_in || 5184000) * 1000,
		).toISOString();

		const updateQuery = supabase
			.from("accounts")
			.update({
				threads_access_token_encrypted: encryptedToken,
				token_expires_at: newExpiresAt,
				updated_at: new Date().toISOString(),
			})
			.eq("id", account.id);

		if (account.updated_at) {
			updateQuery.eq("updated_at", account.updated_at);
		}

		// Use .select("id") to verify the optimistic lock worked (.count is null without { count: 'exact' })
		const { data: updatedRows, error: updateError } =
			await updateQuery.select("id");

		if (updateError) {
			result.error = `Database update failed: ${updateError.message}`;
			return result;
		}

		if (!updatedRows || updatedRows.length === 0) {
			logger.warn(
				"[daily-maintenance] Token refresh skipped — row updated by another process",
				{
					accountId: account.id,
					username: account.username,
				},
			);
			result.error = "Skipped: row updated by another process";
			return result;
		}

		result.success = true;
		result.newExpiresAt = newExpiresAt;
		return result;
	} catch (error: unknown) {
		result.error =
			(error instanceof Error ? error.message : undefined) || "Unknown error";
		return result;
	}
}

async function refreshInstagramToken(
	supabase: TypedSupabaseClient,
	account: InstagramAccount,
	encrypt: (v: string) => string,
	decrypt: (v: string) => string,
	logger: Logger,
): Promise<RefreshResult> {
	const result: RefreshResult = {
		accountId: account.id,
		username: account.username,
		success: false,
	};

	try {
		if (!account.instagram_access_token_encrypted) {
			result.error = "No encrypted token found";
			return result;
		}

		const currentToken = decrypt(account.instagram_access_token_encrypted);
		const loginType = account.login_type || "instagram";
		const { refreshTokenByLoginType } = await import("../../tokenRefresh.js");
		let refreshResult: Awaited<ReturnType<typeof refreshTokenByLoginType>>;
		try {
			refreshResult = await refreshTokenByLoginType(currentToken, loginType);
		} catch (err) {
			result.error = err instanceof Error ? err.message : String(err);
			return result;
		}
		const refreshData = refreshResult.data as {
			access_token: string;
			token_type: string;
			expires_in: number;
			error?:
				| {
						message: string;
						type?: string | undefined;
						code?: number | undefined;
						error_subcode?: number | undefined;
				  }
				| undefined;
		};

		if (!refreshResult.ok || !refreshData.access_token) {
			result.error =
				refreshData.error?.message || `Refresh API failed (${loginType} login)`;
			if (refreshData.error) {
				result.metaError = refreshData.error;
			}
			return result;
		}

		const encryptedToken = encrypt(refreshData.access_token);
		const newExpiresAt = new Date(
			Date.now() + (refreshData.expires_in || 5184000) * 1000,
		).toISOString();

		const updateQuery = supabase
			.from("instagram_accounts")
			.update({
				instagram_access_token_encrypted: encryptedToken,
				token_expires_at: newExpiresAt,
				updated_at: new Date().toISOString(),
			})
			.eq("id", account.id);

		if (account.updated_at) {
			updateQuery.eq("updated_at", account.updated_at);
		}

		const { data: updatedRows, error: updateError } =
			await updateQuery.select("id");

		if (updateError) {
			result.error = `Database update failed: ${updateError.message}`;
			return result;
		}

		if (!updatedRows || updatedRows.length === 0) {
			logger.warn(
				"[daily-maintenance] IG token refresh skipped — row updated by another process",
				{
					accountId: account.id,
					username: account.username,
				},
			);
			result.error = "Skipped: row updated by another process";
			return result;
		}

		result.success = true;
		result.newExpiresAt = newExpiresAt;
		return result;
	} catch (error: unknown) {
		result.error =
			(error instanceof Error ? error.message : undefined) || "Unknown error";
		return result;
	}
}

export async function phaseRefreshTokens(
	supabase: TypedSupabaseClient,
	logger: Logger,
	startTime: number,
): Promise<PhaseMetadata["refreshTokens"]> {
	const { encrypt, decrypt } = await import("../../encryption.js");
	const { alertTokenRefreshFailure, alertError } = await import(
		"../../alerting.js"
	);
	const { getRedis } = await import("../../redis.js");

	const stats = { refreshed: 0, failed: 0, errors: [] as string[] };

	const expiryThreshold = new Date(
		Date.now() + HOURS_BEFORE_EXPIRY * 60 * 60 * 1000,
	).toISOString();
	const now = new Date().toISOString();

	// --- Auto-flag already-expired tokens (skip futile refresh attempts) ---
	try {
		const expiredThreadsBase = supabase
			.from("accounts")
			.select("id, user_id, username")
			.not("threads_access_token_encrypted", "is", null)
			.lt("token_expires_at", now)
			.eq("is_active", true)
			.limit(200);
		const { data: expiredThreads } = await neqOrNull(
			expiredThreadsBase,
			"needs_reauth",
			true,
		);

		if (expiredThreads?.length) {
			logger.warn(
				`[daily-maintenance] Auto-flagging ${expiredThreads.length} Threads accounts with expired tokens for re-auth`,
			);
			for (const acct of expiredThreads) {
				await supabase
					.from("accounts")
					.update({
						needs_reauth: true,
						is_active: false,
						status: "needs_reauth",
						updated_at: now,
					})
					.eq("id", acct.id);
				// Notify user (best-effort)
				if (acct.user_id) {
					try {
						const { deliverNotification } = await import(
							"../../deliverNotification.js"
						);
						await deliverNotification({
							userId: acct.user_id,
							type: "token_reauth_needed",
							title: "Threads account needs reconnection",
							message: `Your Threads account @${acct.username} has been disconnected because the access token expired. Please reconnect it in Settings.`,
							data: {
								accountId: acct.id,
								platform: "threads",
								reason: "token_expired",
							},
						});
					} catch (notifErr) {
						logger.warn("Failed to deliver Threads reauth notification", {
							userId: acct.user_id,
							accountId: acct.id,
							error: String(notifErr),
						});
					}
				}
			}
			stats.failed += expiredThreads.length;
		}

		const expiredIgBase = supabase
			.from("instagram_accounts")
			.select("id, user_id, username")
			.not("instagram_access_token_encrypted", "is", null)
			.lt("token_expires_at", now)
			.eq("is_active", true)
			.limit(200);
		const { data: expiredIG } = await neqOrNull(
			expiredIgBase,
			"needs_reauth",
			true,
		);

		if (expiredIG?.length) {
			logger.warn(
				`[daily-maintenance] Auto-flagging ${expiredIG.length} Instagram accounts with expired tokens for re-auth`,
			);
			for (const acct of expiredIG) {
				await supabase
					.from("instagram_accounts")
					.update({
						needs_reauth: true,
						is_active: false,
						status: "needs_reauth",
						updated_at: now,
					})
					.eq("id", acct.id);
				if (acct.user_id) {
					try {
						const { deliverNotification } = await import(
							"../../deliverNotification.js"
						);
						await deliverNotification({
							userId: acct.user_id,
							type: "token_reauth_needed",
							title: "Instagram account needs reconnection",
							message: `Your Instagram account @${acct.username} has been disconnected because the access token expired. Please reconnect it in Settings.`,
							data: {
								accountId: acct.id,
								platform: "instagram",
								reason: "token_expired",
							},
						});
					} catch (notifErr) {
						logger.warn("Failed to deliver Instagram reauth notification", {
							userId: acct.user_id,
							accountId: acct.id,
							error: String(notifErr),
						});
					}
				}
			}
			stats.failed += expiredIG.length;
		}
	} catch (err) {
		logger.error("[daily-maintenance] Error flagging expired tokens", {
			error: String(err),
		});
	}

	// --- Threads accounts (not yet expired, expiring within 72h) ---
	const accountsBase = supabase
		.from("accounts")
		.select(
			"id, user_id, username, threads_user_id, threads_access_token_encrypted, token_expires_at, updated_at",
		)
		.not("threads_access_token_encrypted", "is", null)
		.gte("token_expires_at", now)
		.lt("token_expires_at", expiryThreshold)
		.eq("is_active", true)
		.order("token_expires_at", { ascending: true })
		.limit(100);
	const { data: accounts, error: queryError } = await neqOrNull(
		accountsBase,
		"needs_reauth",
		true,
	);

	if (queryError) {
		logger.error("[daily-maintenance] Token refresh query error", {
			error: String(queryError),
		});
		throw new Error(`Failed to query accounts: ${queryError.message}`);
	}

	logger.info("[daily-maintenance] Found Threads accounts needing refresh", {
		count: accounts?.length || 0,
	});

	const limit = createConcurrencyLimiter(TOKEN_CONCURRENCY_LIMIT);

	for (const account of (accounts || []) as Account[]) {
		if (!hasTimeBudget(startTime)) {
			logger.warn(
				"[daily-maintenance] Time budget exhausted during Threads token refresh",
			);
			break;
		}

		const result = await limit(() =>
			refreshThreadsToken(supabase, account, encrypt, decrypt, logger),
		);

		if (result.success) {
			stats.refreshed++;
			logger.info("[daily-maintenance] Threads token refreshed", {
				username: result.username,
				accountId: result.accountId,
			});
			await resetRefreshFailures(supabase, "accounts", account.id, logger);
			// Set Redis dedup key so token-refresh cron (3 AM) skips this account
			try {
				await getRedis().set(`token-refreshed:${account.id}`, "1", {
					ex: 6 * 60 * 60,
				});
			} catch (redisErr) {
				logger.debug("Redis dedup key write failed", {
					accountId: account.id,
					error: String(redisErr),
				});
			}
		} else {
			stats.failed++;
			stats.errors.push(`@${result.username}: ${result.error}`);
			logger.error("[daily-maintenance] Threads token refresh failed", {
				username: result.username,
				error: result.error,
			});
			await trackRefreshFailure(
				supabase,
				"accounts",
				account.id,
				account.user_id,
				account.username || account.id,
				result.error || "Unknown",
				logger,
				result.metaError,
			);
			alertTokenRefreshFailure(
				"threads",
				result.username || result.accountId,
				result.error || "Unknown",
			);
		}
	}

	// --- Instagram accounts ---
	if (hasTimeBudget(startTime)) {
		logger.info("[daily-maintenance] Starting Instagram token refresh pass");

		const igBase = supabase
			.from("instagram_accounts")
			.select(
				"id, user_id, username, instagram_user_id, instagram_access_token_encrypted, token_expires_at, login_type, updated_at",
			)
			.not("instagram_access_token_encrypted", "is", null)
			.gte("token_expires_at", now)
			.lt("token_expires_at", expiryThreshold)
			.eq("is_active", true)
			.order("token_expires_at", { ascending: true })
			.limit(100);
		const { data: igAccounts, error: igQueryError } = await neqOrNull(
			igBase,
			"needs_reauth",
			true,
		);

		if (igQueryError) {
			logger.error("[daily-maintenance] Instagram token refresh query error", {
				error: String(igQueryError),
			});
			stats.errors.push(`Instagram query failed: ${igQueryError.message}`);
		} else {
			logger.info(
				"[daily-maintenance] Found Instagram accounts needing refresh",
				{ count: igAccounts?.length || 0 },
			);

			for (const igAccount of (igAccounts || []) as InstagramAccount[]) {
				if (!hasTimeBudget(startTime)) {
					logger.warn(
						"[daily-maintenance] Time budget exhausted during IG token refresh",
					);
					break;
				}

				const result = await limit(() =>
					refreshInstagramToken(supabase, igAccount, encrypt, decrypt, logger),
				);

				if (result.success) {
					stats.refreshed++;
					logger.info("[daily-maintenance] IG token refreshed", {
						username: result.username,
						accountId: result.accountId,
					});
					await resetRefreshFailures(
						supabase,
						"instagram_accounts",
						igAccount.id,
						logger,
					);
					// Set Redis dedup key so token-refresh cron (3 AM) skips this account
					try {
						await getRedis().set(`token-refreshed:ig_${igAccount.id}`, "1", {
							ex: 6 * 60 * 60,
						});
					} catch (redisErr) {
						logger.debug("Redis dedup key write failed", {
							accountId: igAccount.id,
							error: String(redisErr),
						});
					}
				} else {
					stats.failed++;
					stats.errors.push(`IG @${result.username}: ${result.error}`);
					logger.error("[daily-maintenance] IG token refresh failed", {
						username: result.username,
						error: result.error,
					});
					await trackRefreshFailure(
						supabase,
						"instagram_accounts",
						igAccount.id,
						igAccount.user_id,
						igAccount.username || igAccount.id,
						result.error || "Unknown",
						logger,
						result.metaError,
					);
					alertTokenRefreshFailure(
						"instagram",
						result.username || result.accountId,
						result.error || "Unknown",
					);
				}
			}
		}
	}

	if (stats.failed > 0) {
		alertError("Token refresh batch completed with failures", {
			refreshed: stats.refreshed,
			failed: stats.failed,
			errors: stats.errors.slice(0, 5).join("\n"),
		});
	}

	return { refreshed: stats.refreshed, failed: stats.failed };
}
