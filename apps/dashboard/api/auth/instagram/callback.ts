// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Instagram OAuth Callback API Route
 *
 * Handles the OAuth callback from Instagram:
 * 1. Exchange authorization code for short-lived token
 * 2. Exchange short-lived token for 60-day long-lived token
 * 3. Fetch user profile
 * 4. Encrypt token with AES-256-GCM
 * 5. Store in Supabase instagram_accounts table
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	getAuthUserOrError,
	validateOAuthState,
} from "../../_lib/apiResponse.js";
import { logAudit } from "../../_lib/auditLog.js";
import { encrypt } from "../../_lib/encryption.js";
import { logger } from "../../_lib/logger.js";
import {
	enforceRouteRateLimit,
	getClientIp,
} from "../../_lib/routeRateLimit.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "../../_lib/privilegedDb.js";
import { subscribeInstagramUserToWebhooks } from "../../instagram/webhook-subscribe.js";

const db = () => getPrivilegedSupabase(PRIVILEGED_DB_REASONS.oauthCallback);

// ============================================================================
// Supabase Admin Client (lazy initialization)
// ============================================================================

// ============================================================================
// Types
// ============================================================================

interface InstagramAccount {
	id: string;
	user_id: string;
	instagram_user_id: string;
	username: string | null;
	display_name: string | null;
	avatar_url: string | null;
	account_type: string | null;
	follower_count: number;
	following_count: number;
	media_count: number;
	instagram_access_token_encrypted: string | null;
	token_expires_at: string | null;
	is_active: boolean;
	status: string | null;
	baseline_follower_count: number;
	baseline_following_count: number;
	baseline_media_count: number;
	last_synced_at: string | null;
	created_at: string;
	updated_at: string;
}

// ============================================================================

const INSTAGRAM_APP_ID = process.env.INSTAGRAM_CLIENT_ID;
const INSTAGRAM_APP_SECRET = process.env.INSTAGRAM_CLIENT_SECRET;
const APP_BASE_URL =
	process.env.APP_URL ||
	(process.env.VERCEL_URL
		? `https://${process.env.VERCEL_URL}`
		: "https://juno33.com");
const REDIRECT_URI =
	process.env.INSTAGRAM_REDIRECT_URI ||
	`${APP_BASE_URL}/auth/instagram/callback`;

interface InstagramShortTokenResponse {
	access_token: string;
	user_id: number;
}

interface InstagramLongTokenResponse {
	access_token: string;
	token_type: string;
	expires_in: number;
}

interface InstagramProfileResponse {
	user_id: string;
	username: string;
	name?: string | undefined;
	account_type?: string | undefined;
	profile_picture_url?: string | undefined;
	followers_count?: number | undefined;
	follows_count?: number | undefined;
	media_count?: number | undefined;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	// Set CORS headers for all requests
	res.setHeader("Access-Control-Allow-Origin", APP_BASE_URL);
	res.setHeader("Access-Control-Allow-Methods", "GET,OPTIONS,POST");
	res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

	// Handle CORS preflight
	if (req.method === "OPTIONS") {
		return res.status(200).end();
	}

	// Only allow POST requests
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const ipAllowed = await enforceRouteRateLimit(res, {
		key: `auth-ip:instagram-callback:ip:${getClientIp(req)}:minute`,
		limit: 5,
		windowSeconds: 60,
		failMode: "closed",
		message: "Too many auth requests. Try again shortly.",
	});
	if (!ipAllowed) return;

	try {
		// Rate limit: max 150 auth attempts per IP per hour
		const clientIp =
			(req.headers["x-forwarded-for"] as string)?.split(",")[0]?.trim() ||
			"unknown";
		try {
			const { getRedis } = await import("../../_lib/redis.js");
			const redis = getRedis();
			const rlKey = `rl:auth:instagram:${clientIp}`;
			const count = await redis.incr(rlKey);
			if (count === 1) await redis.expire(rlKey, 3600);
			if (count > 150) {
				res.setHeader("Retry-After", "3600");
				return apiError(res, 429, "Too many auth attempts. Try again later.");
			}
		} catch {
			/* fail open for auth rate limit */
		}

		const { code, state } = req.body;

		if (!code) {
			return apiError(res, 400, "Authorization code is required");
		}

		// #679: Server-side OAuth state validation (CSRF protection)
		if (!validateOAuthState(state, res)) return;
		// Server-side Redis state verification happens after auth (needs userId)

		// Get user ID from Authorization header
		const user = await getAuthUserOrError(req, res);
		if (!user) return;

		const userId = user.id;

		// Server-side Redis state verification (CSRF protection)
		// Fail-closed on missing state (rejects stale/forged requests).
		// Fail-open only on Redis connection errors (availability > security for infra failures).
		try {
			const { getRedis } = await import("../../_lib/redis.js");
			const redis = getRedis();
			const stateKey = `oauth_state:${userId}:${state}`;
			const stored = await redis.get(stateKey);
			if (stored) {
				// Valid — delete to prevent reuse
				await redis.del(stateKey);
			} else {
				logger.warn(
					"[Instagram OAuth] State not found in Redis — rejecting (expired or forged)",
					{
						userId,
					},
				);
				return apiError(
					res,
					400,
					"OAuth state expired or invalid. Please try connecting again.",
				);
			}
		} catch (redisErr) {
			logger.warn("[Instagram OAuth] Redis unavailable for state verification", {
				error: String(redisErr),
			});
			return apiError(
				res,
				503,
				"Could not verify OAuth state securely. Please try again.",
				{ code: "OAUTH_STATE_UNAVAILABLE" },
			);
		}

		if (!INSTAGRAM_APP_SECRET) {
			logger.error("INSTAGRAM_CLIENT_SECRET not configured");
			return apiError(res, 500, "Server configuration error");
		}

		// Step 1: Exchange code for short-lived access token
		const tokenUrl = "https://api.instagram.com/oauth/access_token";
		const tokenParams = new URLSearchParams({
			client_id: INSTAGRAM_APP_ID || "",
			client_secret: INSTAGRAM_APP_SECRET,
			grant_type: "authorization_code",
			redirect_uri: REDIRECT_URI,
			code,
		});

		logger.info("[Instagram OAuth] Exchange started");

		const tokenResponse = await fetch(tokenUrl, {
			method: "POST",
			headers: { "Content-Type": "application/x-www-form-urlencoded" },
			body: tokenParams.toString(),
			signal: AbortSignal.timeout(15000),
		});

		const tokenData =
			(await tokenResponse.json()) as InstagramShortTokenResponse;

		if (!tokenResponse.ok || !tokenData.access_token) {
			logger.error("Instagram token exchange error", {
				error: String(
					(tokenData as { error_message?: string | undefined }).error_message || tokenData,
				),
				status: tokenResponse.status,
			});
			return apiError(res, 400, "Failed to exchange authorization code");
		}

		const shortLivedToken = tokenData.access_token;

		// Step 2: Exchange short-lived token for long-lived token (60 days)
		// Instagram's ig_exchange_token endpoint only accepts GET
		const longLivedParams = new URLSearchParams({
			grant_type: "ig_exchange_token",
			client_secret: INSTAGRAM_APP_SECRET,
			access_token: shortLivedToken,
		});
		const longLivedResponse = await fetch(
			`https://graph.instagram.com/access_token?${longLivedParams}`,
			{
				method: "GET",
				signal: AbortSignal.timeout(10000),
			},
		);
		const longLivedData =
			(await longLivedResponse.json()) as InstagramLongTokenResponse;

		if (!longLivedResponse.ok || !longLivedData.access_token) {
			logger.error("[IG Callback] Long-lived token exchange FAILED", {
				error: JSON.stringify(longLivedData),
				status: longLivedResponse.status,
			});
			return apiError(
				res,
				400,
				"Failed to obtain long-lived token. Please try connecting again.",
			);
		}

		logger.info("[IG Callback] Long-lived token exchange succeeded", {
			expiresIn: longLivedData.expires_in,
		});

		const accessToken = longLivedData.access_token;
		const expiresIn = longLivedData.expires_in || 5184000; // 60 days

		// Step 3: Get user profile info
		const profileUrl = `https://graph.instagram.com/v25.0/me?fields=user_id,username,name,account_type,profile_picture_url,followers_count,follows_count,media_count`;
		const profileResponse = await fetch(profileUrl, {
			headers: { Authorization: `Bearer ${accessToken}` },
			signal: AbortSignal.timeout(10000),
		});
		const profileData =
			(await profileResponse.json()) as InstagramProfileResponse;

		if (!profileResponse.ok || !profileData.username) {
			logger.error("Instagram profile fetch error", {
				error: String(
					(profileData as { error?: { message?: string | undefined } | undefined }).error?.message ||
						profileData,
				),
			});
			return apiError(res, 400, "Failed to fetch user profile");
		}

		// Step 4: Encrypt access token before storing
		const encryptedAccessToken = encrypt(accessToken);

		// Step 4b: Server-side account limit enforcement
		//
		// #682: ACCEPTED RISK — TOCTOU race condition in account limit check.
		// The count query and subsequent insert are not atomic, so two concurrent
		// OAuth callbacks could both pass the limit check and insert. This is acceptable because:
		// (1) The race window is very small (milliseconds between count and insert)
		// (2) OAuth callbacks are user-initiated and serialized by the browser redirect flow
		// (3) Worst case is one extra account, which daily-maintenance cron can clean up
		// (4) A DB-level constraint (CHECK or trigger) would require cross-table logic
		//     (accounts + instagram_accounts) which adds significant complexity
		// (5) The upsert on (user_id, instagram_user_id) prevents true duplicates
		const { data: profile } = (await db()
			.from("profiles")
			.select("subscription_tier, extra_accounts")
			.eq("id", userId)
			.maybeSingle()) as unknown as {
			data: {
				subscription_tier: string | null;
				extra_accounts: number | null;
			} | null;
		};

		const userTier = (profile?.subscription_tier || "free").toLowerCase();
		const extraAccounts = profile?.extra_accounts || 0;

		const { getAccountLimit } = await import("../../_lib/billing.js");
		const maxAccounts = getAccountLimit(userTier, extraAccounts);

		logger.info("[Instagram OAuth] Tier check", {
			userId,
			userTier,
			maxAccounts,
		});

		// Count ALL active accounts (Threads + Instagram) for this user
		const { count: threadsCount } = await db()
			.from("accounts")
			.select("*", { count: "exact", head: true })
			.eq("user_id", userId)
			.eq("is_active", true);

		const { count: igCount } = await db()
			.from("instagram_accounts")
			.select("*", { count: "exact", head: true })
			.eq("user_id", userId)
			.eq("is_active", true);

		const currentAccountCount = (threadsCount || 0) + (igCount || 0);

		// Step 5: Check if account with same instagram_user_id already exists.
		// instagram_user_id is globally unique; do not upsert a different user_id
		// into an existing provider account row.
		const igUserId = profileData.user_id || String(tokenData.user_id);
		const { data: globalExistingAccount, error: globalQueryError } =
			(await db()
				.from("instagram_accounts")
				.select("id, user_id")
				.eq("instagram_user_id", igUserId)
				.maybeSingle()) as unknown as {
				data: { id: string; user_id: string } | null;
				error: Error | null;
			};

		if (globalQueryError) {
			logger.error("Database global Instagram account query error", {
				error: String(globalQueryError),
			});
			return apiError(res, 500, "Database error");
		}

		if (globalExistingAccount && globalExistingAccount.user_id !== userId) {
			logger.warn("[Instagram OAuth] Account already linked to another user", {
				userId,
				accountId: globalExistingAccount.id,
				igUserId,
			});
			return apiError(
				res,
				409,
				"This Instagram account is already connected to another Juno account.",
				{ code: "ACCOUNT_ALREADY_LINKED" },
			);
		}

		const { data: existingAccounts, error: queryError } = (await db()
			.from("instagram_accounts")
			.select("*")
			.eq("user_id", userId)
			.eq("instagram_user_id", igUserId)
			.limit(1)) as unknown as {
			data: InstagramAccount[] | null;
			error: Error | null;
		};

		if (queryError) {
			logger.error("Database query error", { error: String(queryError) });
			return apiError(res, 500, "Database error");
		}

		let accountId: string;
		let isReconnected = false;

		if (existingAccounts && existingAccounts.length > 0) {
			// Account exists - reuse it to preserve data
			const existingAccount = existingAccounts[0];
			accountId = existingAccount!.id;
			isReconnected = true;

			// Even on reconnection, verify user hasn't exceeded tier limit.
			// An inactive account being reactivated counts towards the limit.
			if (
				!existingAccount!.is_active &&
				profile &&
				currentAccountCount >= maxAccounts
			) {
				const tierName = userTier.charAt(0).toUpperCase() + userTier.slice(1);
				return apiError(
					res,
					403,
					`Account limit reached. Your ${tierName} plan allows ${maxAccounts === Infinity ? "unlimited" : maxAccounts} account(s). Please upgrade to reconnect this account.`,
					{
						code: "ACCOUNT_LIMIT_REACHED",
						extra: {
							currentCount: currentAccountCount,
							maxAllowed: maxAccounts,
							tier: userTier,
						},
					},
				);
			}

			const { error: updateError } = await db()
				.from("instagram_accounts")
				.update({
					username: profileData.username,
					display_name: profileData.name || profileData.username,
					avatar_url:
						profileData.profile_picture_url || existingAccount!.avatar_url,
					account_type:
						profileData.account_type || existingAccount!.account_type,
					follower_count:
						profileData.followers_count ?? existingAccount!.follower_count,
					following_count:
						profileData.follows_count ?? existingAccount!.following_count,
					media_count: profileData.media_count ?? existingAccount!.media_count,
					instagram_access_token_encrypted: encryptedAccessToken,
					token_expires_at: new Date(
						Date.now() + expiresIn * 1000,
					).toISOString(),
					is_active: true,
					status: "active",
					needs_reauth: false,
					consecutive_refresh_failures: 0,
					login_type: "instagram",
					updated_at: new Date().toISOString(),
				})
				.eq("id", accountId);

			if (updateError) {
				logger.error("Database update error", { error: String(updateError) });
				return apiError(res, 500, "Failed to update account");
			}
		} else {
			// Enforce account limit for NEW accounts (reconnections are always allowed)
			// Only enforce if we could actually look up the profile (avoid false "free" on lookup failure)
			if (profile && currentAccountCount >= maxAccounts) {
				const tierName = userTier.charAt(0).toUpperCase() + userTier.slice(1);
				return apiError(
					res,
					403,
					`Account limit reached. Your ${tierName} plan allows ${maxAccounts === Infinity ? "unlimited" : maxAccounts} account(s). Please upgrade to connect more.`,
					{
						code: "ACCOUNT_LIMIT_REACHED",
						extra: {
							currentCount: currentAccountCount,
							maxAllowed: maxAccounts,
							tier: userTier,
						},
					},
				);
			}

			// New account
			const initialFollowers = profileData.followers_count || 0;
			const initialFollowing = profileData.follows_count || 0;
			const initialMedia = profileData.media_count || 0;

			const { data: newAccount, error: insertError } = (await db()
				.from("instagram_accounts")
				.insert({
					user_id: userId,
					instagram_user_id: igUserId,
					username: profileData.username,
					display_name: profileData.name || profileData.username,
					avatar_url: profileData.profile_picture_url || null,
					account_type: profileData.account_type || null,
					instagram_access_token_encrypted: encryptedAccessToken,
					token_expires_at: new Date(
						Date.now() + expiresIn * 1000,
					).toISOString(),
					is_active: true,
					status: "active",
					follower_count: initialFollowers,
					following_count: initialFollowing,
					media_count: initialMedia,
					baseline_follower_count: initialFollowers,
					baseline_following_count: initialFollowing,
					baseline_media_count: initialMedia,
					login_type: "instagram",
					// biome-ignore lint/suspicious/noExplicitAny: Supabase insert type mismatch with runtime columns
				} as any)
				.select()
				.maybeSingle()) as unknown as {
				data: InstagramAccount | null;
				error: Error | null;
			};

			if (insertError || !newAccount) {
				const duplicate =
					(insertError as { code?: string | undefined } | null)?.code ===
						"23505" || /duplicate|unique/i.test(String(insertError));
				if (duplicate) {
					return apiError(
						res,
						409,
						"This Instagram account is already connected to another Juno account.",
						{ code: "ACCOUNT_ALREADY_LINKED" },
					);
				}
				logger.error("Database insert error", {
					error: String(insertError),
					igUserId,
					username: profileData.username,
				});
				return apiError(res, 500, "Failed to create account");
			}

			accountId = newAccount.id;
		}

		logAudit(userId, "account.connect", {
			resourceType: "account",
			resourceId: accountId,
			metadata: { platform: "instagram", username: profileData.username },
			req,
		});

		// Auto-subscribe to IG webhooks (best-effort)
		try {
			const webhookResult = await subscribeInstagramUserToWebhooks(
				igUserId,
				accessToken,
			);
			if (!webhookResult.success) {
				logger.warn("[instagram-callback] Webhook auto-subscribe failed", {
					error: webhookResult.error,
				});
			}
		} catch (webhookErr) {
			logger.warn("[instagram-callback] Webhook auto-subscribe error", {
				error: String(webhookErr),
			});
		}

		// Backfill existing DM conversations into local DB (async, non-blocking)
		try {
			const { getQStashClient } = await import("../../_lib/qstash.js");
			const { RETRIES } = await import("../../_lib/qstashDefaults.js");
			const qstash = getQStashClient();
			await qstash.publishJSON({
				url: `${APP_BASE_URL}/api/instagram/messages?action=sync-inbox`,
				body: { accountId, userId, isBackfill: true },
				retries: RETRIES.BEST_EFFORT,
			});
		} catch (backfillErr) {
			logger.warn("[instagram-callback] DM backfill dispatch failed", {
				error: String(backfillErr),
			});
		}

		return apiSuccess(res, {
			accountId,
			username: profileData.username,
			isReconnected,
		});
	} catch (error: unknown) {
		logger.error("Error in Instagram OAuth callback", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
}
