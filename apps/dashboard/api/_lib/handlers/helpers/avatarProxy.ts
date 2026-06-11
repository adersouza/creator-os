/**
 * Avatar Proxy Factory
 *
 * Shared logic for the Threads and Instagram avatar proxy endpoints.
 * Both endpoints:
 *   1. Check an in-memory cache
 *   2. Try the stored avatar_url (HEAD check for Threads, skip for IG)
 *   3. Fetch a fresh URL from the platform API
 *   4. Update the DB (fire and forget)
 *   5. Fallback gracefully (transparent GIF for Threads, 404 for IG)
 *
 * Usage:
 *   export default createAvatarProxy({ platform: "threads" });
 */

import type { VercelResponse } from "@vercel/node";
import { apiError } from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import {
	fetchAllowedMediaUrl,
	isAllowedPlatformMediaUrl,
	isAllowedSupabasePublicUrl,
} from "../../outboundUrlSecurity.js";
import { getSupabase } from "../../supabase.js";

// Simple in-memory cache (per serverless instance)
const avatarCache = new Map<string, { url: string; expiresAt: number }>();

// 1x1 transparent GIF fallback
const TRANSPARENT_GIF = Buffer.from(
	"R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
	"base64",
);

export interface AvatarProxyConfig {
	platform: "threads" | "instagram";
}

interface ThreadsAccountRow {
	avatar_url: string | null;
	threads_access_token_encrypted: string | null;
	threads_user_id: string | null;
}

interface IgAccountRow {
	avatar_url: string | null;
	instagram_access_token_encrypted: string | null;
	instagram_user_id: string | null;
}

/**
 * Core avatar proxy handler, parameterized by platform.
 * Threads uses withCors (no auth, public profile pics via unguessable UUIDs).
 * Instagram uses withAuth (user-scoped, cache keyed by userId:accountId).
 */
export async function handleAvatarProxy(
	res: VercelResponse,
	accountId: string,
	config: AvatarProxyConfig,
	userId?: string,
): Promise<VercelResponse | undefined> {
	const cacheKey = userId ? `${userId}:${accountId}` : accountId;
	const cached = avatarCache.get(cacheKey);
	if (
		cached &&
		cached.expiresAt > Date.now() &&
		isSafeAvatarRedirect(cached.url)
	) {
		res.setHeader("Cache-Control", "public, max-age=3600");
		return res.redirect(302, cached.url);
	}

	try {
		if (config.platform === "threads") {
			return await handleThreadsAvatar(res, accountId, cacheKey);
		}
		return await handleIgAvatar(res, accountId, cacheKey, userId);
	} catch (err: unknown) {
		logger.error(`[${config.platform}-avatar] Error`, { error: String(err) });
		if (config.platform === "threads") {
			res.setHeader("Content-Type", "image/gif");
			return res.status(200).end(TRANSPARENT_GIF);
		}
		return apiError(res, 500, "Internal error");
	}
}

// ============================================================================
// Threads avatar logic
// ============================================================================

async function handleThreadsAvatar(
	res: VercelResponse,
	accountId: string,
	cacheKey: string,
): Promise<VercelResponse | undefined> {
	const { data: account, error } = await getSupabase()
		.from("accounts")
		.select("threads_user_id, threads_access_token_encrypted, avatar_url")
		.eq("id", accountId)
		.maybeSingle();

	if (error || !account) {
		res.setHeader("Content-Type", "image/gif");
		res.setHeader("Cache-Control", "public, max-age=300");
		return res.status(200).end(TRANSPARENT_GIF);
	}

	const acc = account as unknown as ThreadsAccountRow;

	// Try the stored avatar_url first (quick HEAD check)
	if (acc.avatar_url && isSafeAvatarRedirect(acc.avatar_url)) {
		try {
			const headRes = await fetchAllowedMediaUrl(acc.avatar_url, {
				method: "HEAD",
				signal: AbortSignal.timeout(3000),
			});
			if (headRes?.ok) {
				avatarCache.set(cacheKey, {
					url: acc.avatar_url,
					expiresAt: Date.now() + 3600000,
				});
				res.setHeader("Cache-Control", "public, max-age=3600");
				return res.redirect(302, acc.avatar_url);
			}
		} catch {
			// URL expired or unreachable, try refreshing below
		}
	}

	// Stored URL is expired -- fetch fresh from Threads API
	if (acc.threads_access_token_encrypted && acc.threads_user_id) {
		try {
			const token = decrypt(acc.threads_access_token_encrypted);
			const apiUrl = `https://graph.threads.net/v1.0/${acc.threads_user_id}?fields=threads_profile_picture_url`;
			const apiRes = await fetch(apiUrl, {
				headers: { Authorization: `Bearer ${token}` },
				signal: AbortSignal.timeout(5000),
				redirect: "manual",
			});
			const data = await apiRes.json();

			if (
				data.threads_profile_picture_url &&
				isSafeAvatarRedirect(data.threads_profile_picture_url)
			) {
				const freshUrl = data.threads_profile_picture_url;

				avatarCache.set(cacheKey, {
					url: freshUrl,
					expiresAt: Date.now() + 3600000,
				});

				// Update DB with fresh URL (fire and forget)
				getSupabase()
					.from("accounts")
					.update({ avatar_url: freshUrl })
					.eq("id", accountId)
					.then(() => {});

				res.setHeader("Cache-Control", "public, max-age=3600");
				return res.redirect(302, freshUrl);
			}
		} catch (apiErr) {
			logger.warn("[threads-avatar] API fetch failed", {
				accountId,
				error: String(apiErr),
			});
		}
	}

	// All attempts failed -- transparent GIF
	res.setHeader("Content-Type", "image/gif");
	res.setHeader("Cache-Control", "public, max-age=300");
	return res.status(200).end(TRANSPARENT_GIF);
}

// ============================================================================
// Instagram avatar logic
// ============================================================================

async function handleIgAvatar(
	res: VercelResponse,
	accountId: string,
	cacheKey: string,
	userId?: string,
): Promise<VercelResponse | undefined> {
	// biome-ignore lint/suspicious/noExplicitAny: mixed query builder
	let query: any = getSupabase()
		.from("instagram_accounts")
		.select("instagram_user_id, instagram_access_token_encrypted, avatar_url")
		.eq("id", accountId);

	if (userId) {
		query = query.eq("user_id", userId);
	}

	const { data: account, error } = await query.maybeSingle();

	if (error || !account) {
		return apiError(res, 404, "Account not found");
	}

	const acc = account as unknown as IgAccountRow;

	// Try fetching fresh URL from IG API
	if (acc.instagram_access_token_encrypted && acc.instagram_user_id) {
		try {
			const token = decrypt(acc.instagram_access_token_encrypted);
			const apiUrl = `https://graph.instagram.com/v25.0/${acc.instagram_user_id}?fields=profile_picture_url`;
			const apiRes = await fetch(apiUrl, {
				headers: { Authorization: `Bearer ${token}` },
				signal: AbortSignal.timeout(5000),
				redirect: "manual",
			});
			const data = await apiRes.json();

			if (
				data.profile_picture_url &&
				isSafeAvatarRedirect(data.profile_picture_url)
			) {
				avatarCache.set(cacheKey, {
					url: data.profile_picture_url,
					expiresAt: Date.now() + 3600000,
				});

				// Update DB (fire and forget)
				Promise.resolve(
					getSupabase()
						.from("instagram_accounts")
						.update({ avatar_url: data.profile_picture_url })
						.eq("id", accountId),
				).catch((err: unknown) =>
					logger.warn("[avatar] Failed to update avatar_url", {
						error: String(err),
					}),
				);

				res.setHeader("Cache-Control", "public, max-age=3600");
				return res.redirect(302, data.profile_picture_url);
			}
		} catch (apiErr) {
			logger.warn("[avatar] IG API fetch failed, falling back to stored URL", {
				error: String(apiErr),
			});
		}
	}

	// Fallback to stored URL
	if (acc.avatar_url && isSafeAvatarRedirect(acc.avatar_url)) {
		res.setHeader("Cache-Control", "public, max-age=300");
		return res.redirect(302, acc.avatar_url);
	}

	return apiError(res, 404, "No avatar available");
}

function isSafeAvatarRedirect(url: string): boolean {
	return isAllowedPlatformMediaUrl(url) || isAllowedSupabasePublicUrl(url);
}
