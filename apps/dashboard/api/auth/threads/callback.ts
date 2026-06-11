// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Threads OAuth Callback API Route
 *
 * Handles the OAuth callback from Threads:
 * 1. Exchange authorization code for short-lived token
 * 2. Exchange short-lived token for 60-day long-lived token
 * 3. Fetch user profile (username, avatar)
 * 4. Encrypt token with AES-256-GCM
 * 5. Store in Supabase
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

const db = () => getPrivilegedSupabase(PRIVILEGED_DB_REASONS.oauthCallback);

interface ProfileRow {
	subscription_tier: string | null;
	extra_accounts: number | null;
}

// ============================================================================
// Supabase Admin Client (lazy initialization)
// ============================================================================

// ============================================================================
// Types
// ============================================================================

interface Account {
	id: string;
	user_id: string;
	threads_user_id: string | null;
	username: string | null;
	display_name: string | null;
	avatar_url: string | null;
	bio: string | null;
	posting_method: string | null;
	threads_access_token_encrypted: string | null;
	token_expires_at: string | null;
	is_active: boolean;
	status: string | null;
	followers_count: number;
	following_count: number;
	posts_count: number;
	baseline_followers_count: number;
	baseline_following_count: number;
	baseline_posts_count: number;
	last_synced_at: string | null;
	created_at: string;
	updated_at: string;
}

// ============================================================================

const THREADS_APP_ID = process.env.THREADS_CLIENT_ID;
const THREADS_APP_SECRET = process.env.THREADS_CLIENT_SECRET;
const APP_BASE_URL =
	process.env.APP_URL ||
	(process.env.VERCEL_URL
		? `https://${process.env.VERCEL_URL}`
		: "https://juno33.com");
const REDIRECT_URI =
	process.env.THREADS_REDIRECT_URI || `${APP_BASE_URL}/auth/threads/callback`;

interface ThreadsTokenResponse {
	access_token: string;
	user_id: string;
	expires_in?: number | undefined;
	error?: {
        		message: string;
        		type: string;
        		code: number;
        	} | undefined;
}

interface ThreadsUserProfileResponse {
	id: string;
	username: string;
	threads_profile_picture_url?: string | undefined;
	error?: {
        		message: string;
        		type: string;
        		code: number;
        	} | undefined;
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
		key: `auth-ip:threads-callback:ip:${getClientIp(req)}:minute`,
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
			const rlKey = `rl:auth:threads:${clientIp}`;
			const count = await redis.incr(rlKey);
			if (count === 1) await redis.expire(rlKey, 3600);
			if (count > 150) {
				res.setHeader("Retry-After", "3600");
				return apiError(res, 429, "Too many auth attempts. Try again later.");
			}
		} catch {
			/* fail open for auth rate limit */
		}

		const { state } = req.body;
		// Strip trailing #_ that Threads appends to authorization codes (§2)
		const code =
			typeof req.body.code === "string"
				? req.body.code.replace(/#_$/, "")
				: req.body.code;

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
					"[Threads OAuth] State not found in Redis — rejecting (expired or forged)",
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
			logger.warn("[Threads OAuth] Redis unavailable for state verification", {
				error: String(redisErr),
			});
			return apiError(
				res,
				503,
				"Could not verify OAuth state securely. Please try again.",
				{ code: "OAUTH_STATE_UNAVAILABLE" },
			);
		}

		if (!THREADS_APP_SECRET) {
			logger.error("THREADS_CLIENT_SECRET not configured");
			return apiError(res, 500, "Server configuration error");
		}

		// Step 1: Exchange code for short-lived access token
		const tokenUrl = "https://graph.threads.net/oauth/access_token";
		const tokenParams = new URLSearchParams({
			client_id: THREADS_APP_ID || "",
			client_secret: THREADS_APP_SECRET,
			grant_type: "authorization_code",
			redirect_uri: REDIRECT_URI,
			code,
		});

		logger.info("[Threads OAuth] Exchange started");

		const tokenResponse = await fetch(tokenUrl, {
			method: "POST",
			headers: { "Content-Type": "application/x-www-form-urlencoded" },
			body: tokenParams.toString(),
			signal: AbortSignal.timeout(15000),
		});

		const tokenData = (await tokenResponse.json()) as ThreadsTokenResponse;

		if (!tokenResponse.ok || !tokenData.access_token) {
			logger.error("Token exchange error", {
				error: String(tokenData.error?.message || tokenData),
				status: tokenResponse.status,
			});
			return apiError(res, 400, "Failed to exchange authorization code");
		}

		const shortLivedToken = tokenData.access_token;

		// Step 2: Exchange short-lived token for long-lived token (60 days)
		// Per Threads API docs: access_token must be a query parameter, NOT a Bearer header
		const longLivedUrl = `https://graph.threads.net/access_token?grant_type=th_exchange_token&client_secret=${THREADS_APP_SECRET}&access_token=${encodeURIComponent(shortLivedToken)}`;

		const longLivedResponse = await fetch(longLivedUrl, {
			method: "GET",
			signal: AbortSignal.timeout(10000),
		});
		const longLivedData =
			(await longLivedResponse.json()) as ThreadsTokenResponse;

		if (!longLivedResponse.ok || !longLivedData.access_token) {
			logger.error("[Threads OAuth] Long-lived token exchange failed", {
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

		const accessToken = longLivedData.access_token;
		const expiresIn = longLivedData.expires_in || 5184000; // 60 days

		// Step 3: Get user profile info
		const profileUrl = `https://graph.threads.net/v1.0/me?fields=id,username,threads_profile_picture_url`;
		const profileResponse = await fetch(profileUrl, {
			headers: { Authorization: `Bearer ${accessToken}` },
			signal: AbortSignal.timeout(10000),
		});
		const profileData =
			(await profileResponse.json()) as ThreadsUserProfileResponse;

		if (!profileResponse.ok || !profileData.username) {
			logger.error("Profile fetch error", {
				error: String(
					profileData.error?.message || JSON.stringify(profileData),
				),
				status: profileResponse.status,
			});
			return apiError(res, 400, "Failed to fetch user profile");
		}

		// Fetch followers_count separately via insights endpoint
		let followersCount = 0;
		try {
			const insightsUrl = `https://graph.threads.net/v1.0/${profileData.id}/threads_insights?metric=followers_count`;
			const insightsRes = await fetch(insightsUrl, {
				headers: { Authorization: `Bearer ${accessToken}` },
				signal: AbortSignal.timeout(5000),
			});
			if (insightsRes.ok) {
				const insightsData = await insightsRes.json();
				const metric = insightsData?.data?.[0];
				followersCount =
					metric?.total_value?.value ?? metric?.values?.[0]?.value ?? 0;
			}
		} catch {
			// Non-critical — baseline will be 0
		}

		// Step 4: Encrypt access token before storing
		const encryptedAccessToken = encrypt(accessToken);

		// Step 4b: Server-side account limit enforcement
		// Check user's subscription tier and current account count before allowing new connections
		//
		// #682: ACCEPTED RISK — TOCTOU race condition in account limit check.
		// The count query and subsequent insert are not atomic, so two concurrent
		// OAuth callbacks could both pass the limit check and insert. This is acceptable because:
		// (1) The race window is very small (milliseconds between count and insert)
		// (2) OAuth callbacks are user-initiated and serialized by the browser redirect flow
		// (3) Worst case is one extra account, which daily-maintenance cron can clean up
		// (4) A DB-level constraint (CHECK or trigger) would require cross-table logic
		//     (accounts + instagram_accounts) which adds significant complexity
		// (5) The upsert on (user_id, threads_user_id) prevents true duplicates
		const { data: profile } = (await db()
			.from("profiles")
			.select("subscription_tier, extra_accounts")
			.eq("id", userId)
			.maybeSingle()) as { data: ProfileRow | null; error: unknown };

		const userTier = (profile?.subscription_tier || "free").toLowerCase();
		const extraAccounts = profile?.extra_accounts || 0;

		const { getAccountLimit } = await import("../../_lib/billing.js");
		const maxAccounts = getAccountLimit(userTier, extraAccounts);

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

		// Step 5: Check if account with same threadsUserId already exists
		const { data: existingAccounts, error: queryError } = (await db()
			.from("accounts")
			.select("*")
			.eq("user_id", userId)
			.eq("threads_user_id", profileData.id)
			.limit(1)) as unknown as {
			data: Account[] | null;
			error: Error | null;
		};

		if (queryError) {
			logger.error("Database query error", { error: String(queryError) });
			return apiError(res, 500, "Database error");
		}

		let accountId: string;
		let isReconnected = false;

		if (existingAccounts && existingAccounts.length > 0) {
			// Account exists - reuse it to preserve accountId and old posts
			const existingAccount = existingAccounts[0];
			accountId = existingAccount!.id;
			isReconnected = true;

			// Check account limit on reconnection of inactive accounts
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
				.from("accounts")
				.update({
					username: profileData.username,
					display_name: profileData.username,
					avatar_url:
						profileData.threads_profile_picture_url ||
						existingAccount!.avatar_url,
					posting_method: "official",
					threads_access_token_encrypted: encryptedAccessToken,
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
			if (profile && (currentAccountCount || 0) >= maxAccounts) {
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

			// New account - create it with actual follower count as baseline
			const initialFollowers = followersCount;

			// Safety check: if account already exists (race condition / unique constraint),
			// don't overwrite baseline metrics on re-auth
			const { data: existingForBaseline } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", userId)
				.eq("threads_user_id", profileData.id)
				.maybeSingle();

			const baselineFields = existingForBaseline
				? {} // Account exists — preserve existing baselines
				: {
						baseline_followers_count: initialFollowers,
						baseline_following_count: 0,
						baseline_posts_count: 0,
					};

			const { data: newAccount, error: insertError } = (await db()
				.from("accounts")
				.upsert(
					{
						user_id: userId,
						threads_user_id: profileData.id,
						username: profileData.username,
						display_name: profileData.username,
						avatar_url: profileData.threads_profile_picture_url || null,
						posting_method: "official",
						threads_access_token_encrypted: encryptedAccessToken,
						token_expires_at: new Date(
							Date.now() + expiresIn * 1000,
						).toISOString(),
						is_active: true,
						status: "active",
						followers_count: initialFollowers,
						following_count: 0,
						posts_count: 0,
						...baselineFields,
						// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert type mismatch with runtime columns
					} as any,
					{ onConflict: "user_id,threads_user_id" },
				)
				.select()
				.maybeSingle()) as unknown as {
				data: Account | null;
				error: Error | null;
			};

			if (insertError || !newAccount) {
				logger.error("Database insert error", {
					error: JSON.stringify(insertError),
				});
				return apiError(res, 500, "Failed to create account");
			}

			accountId = newAccount.id;
		}

		logAudit(userId, "account.connect", {
			resourceType: "account",
			resourceId: accountId,
			metadata: { platform: "threads", username: profileData.username },
			req,
		});

		// NOTE: Threads webhooks are app-level, configured via Meta App Dashboard.
		// The Threads API does not support programmatic subscription (POST /{app-id}/subscriptions
		// returns "Object does not exist or does not support this operation").

		return apiSuccess(res, {
			accountId,
			username: profileData.username,
			isReconnected,
		});
	} catch (error: unknown) {
		const errMsg = error instanceof Error ? error.message : String(error);
		const errStack = error instanceof Error ? error.stack : undefined;
		logger.error("Error in Threads OAuth callback", {
			error: errMsg,
			stack: errStack,
		});
		return apiError(res, 500, "Internal server error");
	}
}
