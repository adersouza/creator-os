/**
 * Media Proxy API Route
 * GET /api/media/:id
 *
 * Proxies post media server-side to eliminate CDN 403 console errors.
 * 1. Looks up the post's media URL from DB
 * 2. If Supabase URL (permanent) → 302 redirect
 * 3. If CDN URL → fetch server-side and stream back
 * 4. If CDN 403 → re-fetch from platform API, update DB, stream fresh media
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "../_lib/apiResponse.js";
import { logger } from "../_lib/logger.js";
import { withAuth } from "../_lib/middleware.js";
import {
	fetchAllowedMediaUrl,
	isAllowedPlatformMediaUrl,
	isAllowedSupabasePublicUrl,
} from "../_lib/outboundUrlSecurity.js";
import {
	getPrivilegedSupabase,
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";

const db = () => getPrivilegedSupabase(PRIVILEGED_DB_REASONS.mediaProxy);
const dbAny = () => getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.mediaProxy);

async function refreshMediaUrl(post: {
	id: string;
	user_id: string;
	account_id: string;
	instagram_account_id: string | null;
	threads_post_id: string | null;
	instagram_post_id: string | null;
	platform: string | null;
}): Promise<string | null> {
	const { decrypt } = await import("../_lib/encryption.js");

	const isInstagramPost =
		post.platform === "instagram" || !!post.instagram_post_id;
	const platformPostId = isInstagramPost
		? post.instagram_post_id
		: post.threads_post_id;

	if (!platformPostId) return null;

	let accessToken: string;
	let apiHost: string;

	if (isInstagramPost) {
		const igAccountId = post.instagram_account_id || post.account_id;
		const { data: igAccount } = await db()
			.from("instagram_accounts")
			.select("id, instagram_access_token_encrypted, login_type")
			.eq("id", igAccountId)
			.eq("user_id", post.user_id)
			.maybeSingle();

		if (!igAccount?.instagram_access_token_encrypted) return null;

		try {
			accessToken = decrypt(igAccount.instagram_access_token_encrypted);
		} catch {
			return null;
		}

		const loginType = igAccount.login_type || "instagram";
		apiHost =
			loginType === "facebook"
				? "graph.facebook.com/v25.0"
				: "graph.instagram.com/v25.0";
	} else {
		const { data: account } = await db()
			.from("accounts")
			.select("id, threads_access_token_encrypted")
			.eq("id", post.account_id)
			.eq("user_id", post.user_id)
			.maybeSingle();

		if (
			!(account as { threads_access_token_encrypted?: string | undefined })
				?.threads_access_token_encrypted
		)
			return null;

		try {
			accessToken = decrypt(
				(account as { threads_access_token_encrypted: string })
					.threads_access_token_encrypted,
			);
		} catch {
			return null;
		}

		apiHost = "graph.threads.net/v1.0";
	}

	const apiUrl = `https://${apiHost}/${platformPostId}?fields=id,media_url,media_type,thumbnail_url`;
	const response = await fetch(apiUrl, {
		headers: { Authorization: `Bearer ${accessToken}` },
		signal: AbortSignal.timeout(10000),
	});
	if (!response.ok) return null;

	const data = await response.json();
	const freshUrl = data.media_url || data.thumbnail_url;

	if (freshUrl && isAllowedPlatformMediaUrl(freshUrl)) {
		// Update the post with the fresh URL
		await dbAny()
			.from("posts")
			.update({ media_urls: [freshUrl] })
			.eq("id", post.id);
	}

	return freshUrl && isAllowedPlatformMediaUrl(freshUrl) ? freshUrl : null;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		// Auth: verify the requesting user owns this post
		const userId = user.id;

		const postId = req.query.id as string;
		const mediaIndex = parseInt((req.query.index as string) || "0", 10);

		if (!postId) {
			return apiError(res, 400, "Missing post ID");
		}

		try {
			// Look up post — scoped to authenticated user
			const { data: post, error } = await db()
				.from("posts")
				.select(
					"id, user_id, account_id, instagram_account_id, threads_post_id, instagram_post_id, platform, media_urls",
				)
				.eq("id", postId)
				.eq("user_id", userId)
				.maybeSingle();

			if (error || !post) {
				return apiError(res, 404, "Post not found");
			}

			const mediaUrls = (post.media_urls as string[]) || [];
			const targetUrl = mediaUrls[mediaIndex];

			if (!targetUrl) {
				return apiError(res, 404, "No media at this index");
			}

			// If already a permanent Supabase URL, redirect
			if (isAllowedSupabasePublicUrl(targetUrl)) {
				res.setHeader("Cache-Control", "public, max-age=86400");
				return res.redirect(302, targetUrl);
			}

			// Try fetching the CDN URL server-side
			if (isAllowedPlatformMediaUrl(targetUrl)) {
				const cdnResponse = await fetchAllowedMediaUrl(targetUrl, {
					signal: AbortSignal.timeout(10000),
				});

				if (cdnResponse?.ok) {
					// Stream back the media without buffering entire response
					const contentType =
						cdnResponse.headers.get("content-type") || "image/jpeg";
					const contentLength = cdnResponse.headers.get("content-length");

					res.setHeader("Content-Type", contentType);
					if (contentLength) {
						res.setHeader("Content-Length", contentLength);
					}
					res.setHeader("Cache-Control", "public, max-age=86400");
					res.setHeader("X-Content-Type-Options", "nosniff");
					res.setHeader("Content-Disposition", "inline");
					res.status(200);

					if (cdnResponse.body) {
						const { Readable } = await import("node:stream");
						const readable = Readable.fromWeb(
							cdnResponse.body as Parameters<typeof Readable.fromWeb>[0],
						);
						readable.pipe(res);
						return;
					}
					// Fallback if body stream not available
					const buffer = Buffer.from(await cdnResponse.arrayBuffer());
					res.setHeader("Content-Length", buffer.length.toString());
					return res.end(buffer);
				}

				// CDN returned 403 or other error — try refreshing from platform API
				logger.info("[media-proxy] CDN failed, refreshing from API", {
					postId,
					status: cdnResponse?.status ?? "blocked",
				});

				const freshUrl = await refreshMediaUrl(
					post as Parameters<typeof refreshMediaUrl>[0],
				);
				if (freshUrl) {
					// Fetch the fresh URL
					const freshResponse = await fetchAllowedMediaUrl(freshUrl, {
						signal: AbortSignal.timeout(10000),
					});
					if (freshResponse?.ok) {
						const contentType =
							freshResponse.headers.get("content-type") || "image/jpeg";
						const contentLength = freshResponse.headers.get("content-length");

						res.setHeader("Content-Type", contentType);
						if (contentLength) {
							res.setHeader("Content-Length", contentLength);
						}
						res.setHeader("Cache-Control", "public, max-age=86400");
						res.setHeader("X-Content-Type-Options", "nosniff");
						res.setHeader("Content-Disposition", "inline");
						res.status(200);

						if (freshResponse.body) {
							const { Readable } = await import("node:stream");
							const readable = Readable.fromWeb(
								freshResponse.body as Parameters<typeof Readable.fromWeb>[0],
							);
							readable.pipe(res);
							return;
						}
						// Fallback if body stream not available
						const buffer = Buffer.from(await freshResponse.arrayBuffer());
						res.setHeader("Content-Length", buffer.length.toString());
						return res.end(buffer);
					}
				}
			}

			// Fallback: return 1x1 transparent GIF instead of redirecting to an
			// expired CDN URL (which would 403 and pollute the browser console)
			const TRANSPARENT_GIF = Buffer.from(
				"R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
				"base64",
			);
			res.setHeader("Content-Type", "image/gif");
			res.setHeader("Cache-Control", "no-cache");
			return res.status(200).end(TRANSPARENT_GIF);
		} catch (err) {
			logger.error("[media-proxy] Error", { error: String(err) });
			return apiError(res, 500, "Internal server error");
		}
	},
);
