/**
 * Facebook Login OAuth Callback for Instagram Stories
 *
 * Handles the OAuth callback from Facebook:
 * 1. Exchange authorization code for short-lived token
 * 2. Exchange for long-lived token (60 days)
 * 3. Fetch linked Instagram Business/Creator account via Pages
 * 4. Encrypt tokens with AES-256-GCM
 * 5. Store/update in Supabase instagram_accounts table with login_type='facebook'
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	getAuthUserOrError,
	validateOAuthState,
} from "../../_lib/apiResponse.js";
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

const db = () => getPrivilegedSupabase(PRIVILEGED_DB_REASONS.oauthCallback);

interface ProfileRow {
	subscription_tier: string | null;
	extra_accounts: number | null;
}

interface InstagramAccountRow {
	id: string;
	is_active: boolean;
	[key: string]: unknown;
}

// ============================================================================
// Supabase Admin Client (lazy initialization)
// ============================================================================

// ============================================================================

const FACEBOOK_APP_ID = process.env.FACEBOOK_APP_ID;
const FACEBOOK_APP_SECRET = process.env.FACEBOOK_APP_SECRET;
const APP_BASE_URL =
	process.env.APP_URL ||
	(process.env.VERCEL_URL
		? `https://${process.env.VERCEL_URL}`
		: "https://juno33.com");
const REDIRECT_URI =
	process.env.FACEBOOK_REDIRECT_URI || `${APP_BASE_URL}/auth/facebook/callback`;

export default async function handler(req: VercelRequest, res: VercelResponse) {
	// Set CORS headers
	res.setHeader("Access-Control-Allow-Origin", APP_BASE_URL);
	res.setHeader("Access-Control-Allow-Methods", "GET,OPTIONS,POST");
	res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");

	if (req.method === "OPTIONS") {
		return res.status(200).end();
	}

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const ipAllowed = await enforceRouteRateLimit(res, {
		key: `auth-ip:instagram-fb-callback:ip:${getClientIp(req)}:minute`,
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
			const rlKey = `rl:auth:fb:${clientIp}`;
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

		// Authenticate user
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
					"[FB OAuth] State not found in Redis — rejecting (expired or forged)",
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
			logger.warn("[FB OAuth] Redis unavailable for state verification", {
				error: String(redisErr),
			});
			return apiError(
				res,
				503,
				"Could not verify OAuth state securely. Please try again.",
				{ code: "OAUTH_STATE_UNAVAILABLE" },
			);
		}

		if (!FACEBOOK_APP_SECRET || !FACEBOOK_APP_ID) {
			logger.error("Facebook app credentials not configured");
			return apiError(res, 500, "Server configuration error");
		}
		const facebookAppId = FACEBOOK_APP_ID;
		const facebookAppSecret = FACEBOOK_APP_SECRET;

		// Step 1: Exchange code for short-lived token
		// #674: Use POST with form body to avoid leaking app secret in URL/logs
		const tokenResponse = await fetch(
			"https://graph.facebook.com/v25.0/oauth/access_token",
			{
				method: "POST",
				headers: { "Content-Type": "application/x-www-form-urlencoded" },
				body: new URLSearchParams({
					client_id: facebookAppId,
					redirect_uri: REDIRECT_URI,
					client_secret: facebookAppSecret,
					code,
				}).toString(),
				signal: AbortSignal.timeout(10000),
			},
		);
		const tokenData = await tokenResponse.json();

		if (!tokenResponse.ok || !tokenData.access_token) {
			logger.error("Facebook token exchange error", {
				error: String(tokenData.error?.message || tokenData),
			});
			return apiError(res, 400, "Failed to exchange authorization code");
		}

		const shortLivedToken = tokenData.access_token;

		// Step 2: Exchange for long-lived token (60 days)
		// #674: Use POST with form body for long-lived token exchange too
		const longLivedResponse = await fetch(
			"https://graph.facebook.com/v25.0/oauth/access_token",
			{
				method: "POST",
				headers: { "Content-Type": "application/x-www-form-urlencoded" },
				body: new URLSearchParams({
					grant_type: "fb_exchange_token",
					client_id: facebookAppId,
					client_secret: facebookAppSecret,
					fb_exchange_token: shortLivedToken,
				}).toString(),
				signal: AbortSignal.timeout(10000),
			},
		);
		const longLivedData = await longLivedResponse.json();

		if (!longLivedResponse.ok || !longLivedData.access_token) {
			logger.error("[FB Callback] Long-lived token exchange FAILED", {
				error: String(
					longLivedData.error?.message || JSON.stringify(longLivedData),
				),
				status: longLivedResponse.status,
			});
			return apiError(
				res,
				400,
				"Failed to obtain long-lived token. Please try connecting again.",
			);
		}

		const userAccessToken = longLivedData.access_token;
		const expiresIn = longLivedData.expires_in || 5184000; // 60 days default

		// Step 3: Get Facebook Pages the user manages
		const pagesUrl = `https://graph.facebook.com/v25.0/me/accounts?fields=id,name,access_token,instagram_business_account`;
		const pagesResponse = await fetch(pagesUrl, {
			headers: { Authorization: `Bearer ${userAccessToken}` },
			signal: AbortSignal.timeout(10000),
		});
		const pagesData = await pagesResponse.json();

		if (!pagesResponse.ok || !pagesData.data) {
			logger.error("Facebook pages fetch error", {
				error: String(pagesData.error?.message || pagesData),
			});
			return apiError(res, 400, "Failed to fetch Facebook Pages");
		}

		// Step 4: Find page with linked Instagram Business account
		let instagramAccountId: string | null = null;
		let facebookPageId: string | null = null;
		let facebookPageName: string | null = null;
		let pageAccessToken: string | null = null;

		for (const page of pagesData.data) {
			if (page.instagram_business_account) {
				instagramAccountId = page.instagram_business_account.id;
				facebookPageId = page.id;
				facebookPageName = page.name || null;
				pageAccessToken = page.access_token;
				break;
			}
		}

		if (!instagramAccountId || !facebookPageId || !pageAccessToken) {
			return apiError(
				res,
				400,
				"No Instagram Business or Creator account linked to any of your Facebook Pages. Please connect your Instagram account to a Facebook Page first.",
			);
		}

		// Step 5: Get Instagram account profile info
		const igProfileUrl = `https://graph.facebook.com/v25.0/${instagramAccountId}?fields=id,username,name,profile_picture_url,followers_count,follows_count,media_count`;
		const igProfileResponse = await fetch(igProfileUrl, {
			headers: { Authorization: `Bearer ${pageAccessToken}` },
			signal: AbortSignal.timeout(10000),
		});
		const igProfile = await igProfileResponse.json();

		if (!igProfileResponse.ok || !igProfile.username) {
			logger.error("Instagram profile fetch error", {
				error: String(igProfile.error?.message || igProfile),
			});
			return apiError(res, 400, "Failed to fetch Instagram profile");
		}

		// Step 6: Encrypt tokens
		// Store the long-lived USER token (refreshable via fb_exchange_token grant) as the main token.
		// Store the PAGE token separately — page tokens from long-lived user tokens are permanent.
		const encryptedIgToken = encrypt(userAccessToken);
		const encryptedFbPageToken = encrypt(pageAccessToken);

		// Step 6b: Server-side account limit enforcement
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
			.maybeSingle()) as { data: ProfileRow | null; error: unknown };

		const userTier = (profile?.subscription_tier || "free").toLowerCase();
		const extraAccounts = profile?.extra_accounts || 0;

		const { getAccountLimit } = await import("../../_lib/billing.js");
		const maxAccounts = getAccountLimit(userTier, extraAccounts);

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

		// Step 7: Check if account already exists
		const { data: existingAccounts, error: queryError } = await db()
			.from("instagram_accounts")
			.select("*")
			.eq("user_id", userId)
			.eq("instagram_user_id", instagramAccountId)
			.limit(1);

		if (queryError) {
			logger.error("Database query error", { error: String(queryError) });
			return apiError(res, 500, "Database error");
		}

		let accountId: string;
		let isReconnected = false;

		if (existingAccounts && existingAccounts.length > 0) {
			// Update existing account
			const existing = existingAccounts[0] as InstagramAccountRow;
			accountId = existing.id;
			isReconnected = true;

			// Check account limit on reconnection of inactive accounts
			if (
				!existing.is_active &&
				profile &&
				currentAccountCount >= maxAccounts
			) {
				const tierName = userTier.charAt(0).toUpperCase() + userTier.slice(1);
				return res.status(403).json({
					error: `Account limit reached. Your ${tierName} plan allows ${maxAccounts === Infinity ? "unlimited" : maxAccounts} account(s). Please upgrade to reconnect this account.`,
					code: "ACCOUNT_LIMIT_REACHED",
					currentCount: currentAccountCount,
					maxAllowed: maxAccounts,
					tier: userTier,
				});
			}

			const { error: updateError } = await db()
				.from("instagram_accounts")
				.update({
					username: igProfile.username,
					display_name: igProfile.name || igProfile.username,
					avatar_url: igProfile.profile_picture_url || existing.avatar_url,
					account_type: "BUSINESS",
					follower_count: igProfile.followers_count ?? existing.follower_count,
					following_count: igProfile.follows_count ?? existing.following_count,
					media_count: igProfile.media_count ?? existing.media_count,
					instagram_access_token_encrypted: encryptedIgToken,
					facebook_page_id: facebookPageId,
					facebook_page_name: facebookPageName,
					facebook_page_access_token_encrypted: encryptedFbPageToken,
					login_type: "facebook",
					token_expires_at: new Date(
						Date.now() + expiresIn * 1000,
					).toISOString(),
					is_active: true,
					status: "active",
					needs_reauth: false,
					consecutive_refresh_failures: 0,
					updated_at: new Date().toISOString(),
				})
				.eq("id", accountId);

			if (updateError) {
				logger.error("Database update error", { error: String(updateError) });
				return apiError(res, 500, "Failed to update account");
			}
		} else {
			// Enforce account limit for NEW accounts (reconnections are always allowed)
			if (profile && currentAccountCount >= maxAccounts) {
				const tierName = userTier.charAt(0).toUpperCase() + userTier.slice(1);
				return res.status(403).json({
					error: `Account limit reached. Your ${tierName} plan allows ${maxAccounts === Infinity ? "unlimited" : maxAccounts} account(s). Please upgrade to connect more.`,
					code: "ACCOUNT_LIMIT_REACHED",
					currentCount: currentAccountCount,
					maxAllowed: maxAccounts,
					tier: userTier,
				});
			}

			// Create new account
			const initialFollowers = igProfile.followers_count || 0;
			const initialFollowing = igProfile.follows_count || 0;
			const initialMedia = igProfile.media_count || 0;

			const { data: newAccount, error: insertError } = await db()
				.from("instagram_accounts")
				.upsert(
					{
						user_id: userId,
						instagram_user_id: instagramAccountId,
						username: igProfile.username,
						display_name: igProfile.name || igProfile.username,
						avatar_url: igProfile.profile_picture_url || null,
						account_type: "BUSINESS",
						instagram_access_token_encrypted: encryptedIgToken,
						facebook_page_id: facebookPageId,
						facebook_page_name: facebookPageName,
						facebook_page_access_token_encrypted: encryptedFbPageToken,
						login_type: "facebook",
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
					},
					{ onConflict: "user_id,instagram_user_id" },
				)
				.select()
				.maybeSingle();

			if (insertError || !newAccount) {
				logger.error("Database insert error", { error: String(insertError) });
				return apiError(res, 500, "Failed to create account");
			}

			accountId = newAccount.id;
		}

		// Auto-subscribe to webhooks (best-effort, don't fail login on error)
		try {
			const { subscribePageToWebhooks } = await import(
				"../../instagram/webhook-subscribe.js"
			);
			const webhookResult = await subscribePageToWebhooks(
				facebookPageId,
				pageAccessToken,
			);
			if (!webhookResult.success) {
				logger.warn("[fb-callback] Webhook auto-subscribe failed", {
					error: String(webhookResult.error),
				});
			}
		} catch (webhookErr) {
			logger.warn("[fb-callback] Webhook auto-subscribe error", {
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
			logger.warn("[fb-callback] DM backfill dispatch failed", {
				error: String(backfillErr),
			});
		}

		return apiSuccess(res, {
			accountId,
			username: igProfile.username,
			isReconnected,
			loginType: "facebook",
		});
	} catch (error: unknown) {
		logger.error("Error in Facebook Login callback", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
}
