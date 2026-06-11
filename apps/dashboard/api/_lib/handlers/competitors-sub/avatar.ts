/**
 * Competitor Avatar Proxy
 *
 * GET /api/competitor-avatar?id=<competitorId>
 *
 * Public endpoint (no auth) — serves profile pictures for <img> tags.
 * Refreshes expired CDN URLs via Threads API using the competitor owner's token.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { withCors } from "../../middleware.js";
import {
	fetchAllowedMediaUrl,
	isAllowedPlatformMediaUrl,
	isAllowedSupabasePublicUrl,
} from "../../outboundUrlSecurity.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

const AvatarQuerySchema = z.object({
	id: z.string().min(1, "id is required"),
});

interface CompetitorRow {
	threads_user_id: string | null;
	avatar_url: string | null;
	user_id: string | null;
}

interface AccountTokenRow {
	threads_access_token_encrypted: string | null;
}

// In-memory cache (per serverless instance)
const avatarCache = new Map<string, { url: string; expiresAt: number }>();

// 1x1 transparent GIF fallback (prevents 404/403 reaching the browser)
const TRANSPARENT_GIF = Buffer.from(
	"R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
	"base64",
);

export default withCors(async (req: VercelRequest, res: VercelResponse) => {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const parsed = parseQueryOrError(res, AvatarQuerySchema, req.query);
	if (!parsed) return;
	const competitorId = parsed.id;

	// Check cache first
	const cached = avatarCache.get(competitorId);
	if (
		cached &&
		cached.expiresAt > Date.now() &&
		isSafeAvatarRedirect(cached.url)
	) {
		res.setHeader("Cache-Control", "public, max-age=3600");
		return res.redirect(302, cached.url);
	}

	try {
		const db = getSupabase();

		// Fetch competitor by ID (public endpoint — competitor IDs are UUIDs)
		const { data: competitor, error } = await db
			.from("competitors")
			.select("threads_user_id, avatar_url, user_id")
			.eq("id", competitorId)
			.maybeSingle();

		if (error || !competitor) {
			res.setHeader("Content-Type", "image/gif");
			res.setHeader("Cache-Control", "public, max-age=300");
			return res.status(200).end(TRANSPARENT_GIF);
		}

		const comp = competitor as CompetitorRow;

		// Try the stored avatar_url first (quick check via HEAD request)
		if (comp.avatar_url && isSafeAvatarRedirect(comp.avatar_url)) {
			try {
				const headRes = await fetchAllowedMediaUrl(comp.avatar_url, {
					method: "HEAD",
					signal: AbortSignal.timeout(3000),
				});
				if (headRes?.ok) {
					avatarCache.set(competitorId, {
						url: comp.avatar_url,
						expiresAt: Date.now() + 3600000, // 1 hour
					});
					res.setHeader("Cache-Control", "public, max-age=3600");
					return res.redirect(302, comp.avatar_url);
				}
			} catch {
				// URL expired or unreachable, try refreshing below
			}
		}

		// Stored URL is expired — try to fetch fresh one from Threads API
		if (comp.threads_user_id && comp.user_id) {
			const { data: account } = await db
				.from("accounts")
				.select("threads_access_token_encrypted")
				.eq("user_id", comp.user_id)
				.not("threads_access_token_encrypted", "is", null)
				.limit(1)
				.maybeSingle();

			if (account) {
				try {
					const token = decrypt(
						(account as AccountTokenRow).threads_access_token_encrypted ?? "",
					);
					const apiRes = await fetch(
						`https://graph.threads.net/v1.0/${comp.threads_user_id}?fields=threads_profile_picture_url`,
						{
							headers: { Authorization: `Bearer ${token}` },
							signal: AbortSignal.timeout(5000),
							redirect: "manual",
						},
					);
					const data = await apiRes.json();

					if (
						data.threads_profile_picture_url &&
						isSafeAvatarRedirect(data.threads_profile_picture_url)
					) {
						const freshUrl = data.threads_profile_picture_url;

						avatarCache.set(competitorId, {
							url: freshUrl,
							expiresAt: Date.now() + 3600000,
						});

						// Update DB with fresh URL (fire and forget)
						db.from("competitors")
							.update({ avatar_url: freshUrl })
							.eq("id", competitorId)
							.then(() => {});

						res.setHeader("Cache-Control", "public, max-age=3600");
						return res.redirect(302, freshUrl);
					}
				} catch (apiErr) {
					logger.warn("[competitor-avatar] API fetch failed", {
						competitorId,
						error: String(apiErr),
					});
				}
			}
		}

		// All attempts failed — return transparent GIF so browser shows no error
		res.setHeader("Content-Type", "image/gif");
		res.setHeader("Cache-Control", "public, max-age=300");
		return res.status(200).end(TRANSPARENT_GIF);
	} catch (err: unknown) {
		logger.error("[competitor-avatar] Error", { error: String(err) });
		res.setHeader("Content-Type", "image/gif");
		return res.status(200).end(TRANSPARENT_GIF);
	}
});

function isSafeAvatarRedirect(url: string): boolean {
	return isAllowedPlatformMediaUrl(url) || isAllowedSupabasePublicUrl(url);
}
