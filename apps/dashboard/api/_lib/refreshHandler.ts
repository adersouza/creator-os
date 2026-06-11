/**
 * Shared token refresh handler factory.
 *
 * Both Threads and Instagram refresh routes follow the same pattern:
 * auth → rate limit → DB lookup → decrypt → refresh API → encrypt → DB update.
 * This factory eliminates the duplication.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "./apiResponse.js";
import { decrypt, encrypt } from "./encryption.js";
import { logger } from "./logger.js";
import {
	verifyInstagramScopes,
	verifyThreadsScopes,
} from "./oauthScopeVerifier.js";
import { enforceRouteRateLimit, getClientIp } from "./routeRateLimit.js";
import { getSupabase } from "./supabase.js";
import { isTokenExpired } from "./tokenRefresh.js";

interface RefreshConfig {
	platform: "threads" | "instagram";
	table: string;
	tokenField: string;
	refreshFn: (
		currentToken: string,
		account: Record<string, unknown>,
	) => Promise<{
		ok: boolean;
		data: {
			access_token?: string | undefined;
			expires_in?: number | undefined;
			error?: Record<string, unknown> | undefined;
		};
	}>;
}

type QueryResult = Promise<{ data: unknown; error: unknown }>;

type DynamicTableQuery = {
	select: (_columns: string) => DynamicTableQuery;
	update: (_values: Record<string, unknown>) => DynamicTableQuery;
	eq: (_column: string, _value: string) => DynamicTableQuery;
	maybeSingle: () => QueryResult;
	then: QueryResult["then"];
	catch: QueryResult["catch"];
	finally: QueryResult["finally"];
};

type DynamicSupabaseClient = {
	from: (_table: string) => DynamicTableQuery;
	auth: ReturnType<typeof getSupabase>["auth"];
};

export function createRefreshHandler(config: RefreshConfig) {
	return async function handler(req: VercelRequest, res: VercelResponse) {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const ipAllowed = await enforceRouteRateLimit(res, {
			key: `auth-ip:${config.platform}-refresh:ip:${getClientIp(req)}:minute`,
			limit: 5,
			windowSeconds: 60,
			failMode: "closed",
			message: "Too many auth requests. Try again shortly.",
		});
		if (!ipAllowed) return;

		try {
			const { accountId } = req.body;
			const supabase = getSupabase() as unknown as DynamicSupabaseClient;

			if (!accountId) {
				return apiError(res, 400, "Account ID is required");
			}

			const authHeader = req.headers.authorization;
			if (!authHeader?.startsWith("Bearer ")) {
				return apiError(res, 401, "Missing or invalid authorization header");
			}

			const token = authHeader.replace("Bearer ", "");
			const {
				data: { user },
				error: authError,
			} = await supabase.auth.getUser(token);

			if (authError || !user) {
				return apiError(res, 401, "Invalid or expired token");
			}

			const userId = user.id;

			// Rate limit: 10 refresh attempts per hour per user
			const userAllowed = await enforceRouteRateLimit(res, {
				key: `refresh:${config.platform}:user:${userId}:hour`,
				limit: 10,
				windowSeconds: 3600,
				failMode: "open",
				message: "Too many refresh attempts. Try again later.",
			});
			if (!userAllowed) return;

			// Get account from database
			// Dynamic table name causes TS2589 with Supabase typed client
			const { data: account, error: queryError } = await supabase
				.from(config.table)
				.select("*")
				.eq("id", accountId)
				.eq("user_id", userId)
				.maybeSingle();

			if (queryError || !account) {
				logger.error(`${config.platform} account query error`, {
					error: String(queryError),
				});
				return apiError(res, 404, "Account not found");
			}

			const encryptedToken = (account as Record<string, unknown>)[
				config.tokenField
			] as string | null;
			if (!encryptedToken) {
				return apiError(res, 400, "No access token found for account");
			}

			if (
				isTokenExpired(
					(account as Record<string, unknown>).token_expires_at as
						| string
						| null
						| undefined,
				)
			) {
				await supabase
					.from(config.table)
					.update({
						needs_reauth: true,
						is_active: false,
						status: "needs_reauth",
						updated_at: new Date().toISOString(),
					})
					.eq("id", accountId);
				return apiError(
					res,
					400,
					"Token has expired. Please reconnect your account.",
				);
			}

			// Decrypt → refresh → encrypt → update
			const currentToken = decrypt(encryptedToken);

			let refreshResult: {
				ok: boolean;
				data: {
					access_token?: string | undefined;
					expires_in?: number | undefined;
					error?: Record<string, unknown> | undefined;
				};
			};
			try {
				refreshResult = await config.refreshFn(
					currentToken,
					account as Record<string, unknown>,
				);
			} catch (err) {
				return apiError(
					res,
					500,
					err instanceof Error ? err.message : "Token refresh failed",
				);
			}

			if (!refreshResult.ok || !refreshResult.data.access_token) {
				logger.error(`${config.platform} token refresh error`, {
					error: String(
						refreshResult.data.error?.message || refreshResult.data,
					),
				});
				return apiError(
					res,
					400,
					"Failed to refresh token. Please try reconnecting your account.",
				);
			}

			const newEncryptedToken = encrypt(refreshResult.data.access_token);

			const { error: updateError } = await supabase
				.from(config.table)
				.update({
					[config.tokenField]: newEncryptedToken,
					token_expires_at: new Date(
						Date.now() + (refreshResult.data.expires_in || 5184000) * 1000,
					).toISOString(),
					updated_at: new Date().toISOString(),
				})
				.eq("id", accountId);

			if (updateError) {
				logger.error("Database update error", { error: String(updateError) });
				return apiError(res, 500, "Failed to update token");
			}

			if (config.platform === "threads") {
				void verifyThreadsScopes(
					refreshResult.data.access_token,
					accountId,
					supabase,
					logger,
				);
			} else {
				void verifyInstagramScopes(
					refreshResult.data.access_token,
					accountId,
					(account as Record<string, unknown>).login_type as string | undefined,
					supabase,
					logger,
				);
			}

			return apiSuccess(res, { message: "Token refreshed successfully" });
		} catch (error: unknown) {
			logger.error(`Error refreshing ${config.platform} token`, {
				error: String(error),
			});
			return apiError(res, 500, "Internal server error");
		}
	};
}
