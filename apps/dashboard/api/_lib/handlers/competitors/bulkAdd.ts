// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Handler: POST /api/competitors?action=bulk-add
 *
 * Add multiple competitors in a single request (Threads or Instagram).
 * Resolves circuit-breaker tripping from N sequential add_competitor calls.
 *
 * Body: { accountId?: string, platform: "threads" | "instagram", usernames: string[] }
 * Cap: 50 usernames per request.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { withRetry } from "../../retryUtils.js";
import { z, zEnum } from "../../zodCompat.js";
import { withAuthAndBody } from "../helpers/withAuthAndBody.js";
import {
	calculateIgMetrics,
	db,
	fetchAndStorePosts,
	getAllAccessTokens,
	getIgAccount,
	tryWithFallbackTokens,
} from "./shared.js";

const MAX_USERNAMES = 50;

const BulkAddSchema = z.object({
	accountId: z.string().optional(),
	platform: zEnum(["threads", "instagram"]),
	usernames: z
		.array(z.string().min(1))
		.min(1, "At least 1 username required")
		.max(MAX_USERNAMES, `Max ${MAX_USERNAMES} usernames per request`),
});

interface AddResult {
	username: string;
	competitor?: Record<string, unknown> | undefined;
}
interface FailResult {
	username: string;
	reason: string;
}

// ─── Threads: single competitor lookup + insert ───────────────────────
async function addThreadsCompetitor(
	userId: string,
	username: string,
	tokens: string[],
): Promise<{
	success: boolean;
	competitor?: Record<string, unknown> | undefined;
	error?: string | undefined;
}> {
	const cleanUsername = username.replace(/^@/, "").trim();

	let workingToken = "";
	const result = await tryWithFallbackTokens(tokens, async (accessToken) => {
		const url = `https://graph.threads.net/v1.0/profile_lookup?username=${encodeURIComponent(cleanUsername)}&fields=username,name,profile_picture_url,biography,is_verified,follower_count`;
		const resp = await withRetry(
			() =>
				fetch(url, {
					headers: { Authorization: `Bearer ${accessToken}` },
					signal: AbortSignal.timeout(10000),
				}),
			{ label: `competitorBulkAdd:${cleanUsername}` },
		);
		const data = await resp.json();
		if (data.error) return { data: null, error: data.error.message };
		workingToken = accessToken;
		return { data };
	});

	if (!result.data) {
		return {
			success: false,
			error: result.error || `@${cleanUsername} not found`,
		};
	}

	const p = result.data;
	try {
		const { data: comp, error: insertError } = await db()
			.from("competitors")
			.insert({
				user_id: userId,
				threads_user_id: p.username,
				username: p.username,
				display_name: p.name || p.username,
				avatar_url: p.profile_picture_url || "",
				bio: p.biography || "",
				follower_count: p.follower_count || 0,
				is_verified: p.is_verified || false,
				likes_count_7d: p.likes_count || 0,
				quotes_count_7d: p.quotes_count || 0,
				replies_count_7d: p.replies_count || 0,
				reposts_count_7d: p.reposts_count || 0,
				views_count_7d: p.views_count || 0,
				added_at: new Date().toISOString(),
				last_synced_at: new Date().toISOString(),
			})
			.select()
			.maybeSingle();

		if (insertError) {
			if (insertError.code === "23505")
				return { success: false, error: "Already tracked" };
			return { success: false, error: "DB insert failed" };
		}

		// Fire-and-forget initial post fetch
		if (comp?.id) {
			fetchAndStorePosts(comp.id, p.username, workingToken).catch((err) =>
				logger.error("Bulk add: initial post fetch failed", {
					error: String(err),
				}),
			);
		}

		return { success: true, competitor: comp as Record<string, unknown> };
	} catch {
		return { success: false, error: "DB insert failed" };
	}
}

// ─── Instagram: single competitor lookup + insert ─────────────────────
interface IgMediaPost {
	id: string;
	caption?: string | null | undefined;
	like_count?: number | null | undefined;
	comments_count?: number | null | undefined;
	media_url?: string | null | undefined;
	media_type?: string | null | undefined;
	permalink?: string | null | undefined;
	timestamp?: string | null | undefined;
}

interface IgProfile {
	username: string;
	name?: string | undefined;
	biography?: string | undefined;
	followers_count?: number | undefined;
	media_count?: number | undefined;
	profile_picture_url?: string | undefined;
	website?: string | undefined;
	media?: { data?: IgMediaPost[] | undefined } | undefined;
}

async function addIgCompetitor(
	userId: string,
	username: string,
	accountId: string,
): Promise<{
	success: boolean;
	competitor?: Record<string, unknown> | undefined;
	error?: string | undefined;
}> {
	const cleanUsername = username.replace(/^@/, "").trim();

	const account = await getIgAccount(userId, accountId);
	if (!account) return { success: false, error: "Instagram account not found" };

	const { getBusinessDiscovery } = await import("../../instagramApi.js");
	const result = await getBusinessDiscovery(
		account.instagram_access_token_encrypted as string,
		account.instagram_user_id as string,
		cleanUsername,
		12,
	);

	if (!result.success) {
		return {
			success: false,
			error: result.error || `@${cleanUsername} not found`,
		};
	}

	const profile = result.profile as unknown as IgProfile;

	// Check duplicate
	const { data: existing } = await db()
		.from("competitors")
		.select("id")
		.eq("user_id", userId)
		.eq("platform", "instagram")
		.eq("username", profile.username)
		.maybeSingle();

	if (existing) return { success: false, error: "Already tracked" };

	const media = profile.media?.data || [];
	const { avgLikes, avgComments, engagementRate } = calculateIgMetrics(
		media,
		profile.followers_count || 0,
	);

	const { data: comp, error: insertError } = await db()
		.from("competitors")
		.insert({
			user_id: userId,
			platform: "instagram",
			threads_user_id: profile.username,
			instagram_user_id: profile.username,
			username: profile.username,
			display_name: profile.name || profile.username,
			avatar_url: profile.profile_picture_url || "",
			bio: profile.biography || "",
			follower_count: profile.followers_count || 0,
			media_count: profile.media_count || 0,
			avg_likes: avgLikes,
			avg_comments: avgComments,
			engagement_rate: engagementRate,
			website: profile.website || "",
			is_verified: false,
			added_at: new Date().toISOString(),
			last_synced_at: new Date().toISOString(),
			// biome-ignore lint/suspicious/noExplicitAny: Supabase insert missing columns
		} as any)
		.select()
		.maybeSingle();

	if (insertError) {
		return { success: false, error: "DB insert failed" };
	}
	if (!comp) return { success: false, error: "DB insert returned null" };

	// Store initial snapshot
	const today = new Date().toISOString().split("T")[0]!;
	await db()
		.from("competitor_snapshots")
		.upsert(
			{
				competitor_id: comp.id,
				snapshot_date: today,
				follower_count: profile.followers_count || 0,
				// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert missing columns
			} as any,
			{ onConflict: "competitor_id,snapshot_date" },
		);

	// Store top posts
	if (media.length > 0) {
		const topPosts = (media as IgMediaPost[])
			.sort(
				(a, b) =>
					(b.like_count || 0) +
					(b.comments_count || 0) -
					((a.like_count || 0) + (a.comments_count || 0)),
			)
			.slice(0, 10)
			.map((post) => ({
				competitor_id: comp.id,
				platform: "instagram",
				threads_post_id: post.id,
				content: post.caption || "",
				like_count: post.like_count || 0,
				comments_count: post.comments_count || 0,
				engagement_score:
					(post.like_count || 0) + (post.comments_count || 0) * 3,
				media_url: post.media_url || "",
				media_type: post.media_type || "IMAGE",
				permalink: post.permalink || "",
				published_at: post.timestamp,
				fetched_at: new Date().toISOString(),
			}));

		await db()
			.from("competitor_top_posts")
			// biome-ignore lint/suspicious/noExplicitAny: Supabase insert
			.insert(topPosts as any);
	}

	return { success: true, competitor: comp as Record<string, unknown> };
}

// ─── Main handler ─────────────────────────────────────────────────────
export const handleBulkAdd = withAuthAndBody(
	BulkAddSchema,
	async (user, parsed, _req, res) => {
		const { platform, usernames, accountId } = parsed;
		const rl = await checkRateLimit({
			key: `competitor-bulk-add:${user.id}`,
			limit: 20,
			windowSeconds: 60 * 60,
			failMode: "closed",
		});
		if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

		const uniqueUsernames = [
			...new Set(
				usernames.map((u: string) => u.replace(/^@/, "").trim().toLowerCase()),
			),
		];

		logger.info("Bulk add competitors", {
			platform,
			count: uniqueUsernames.length,
			userId: user.id,
		});

		const added: AddResult[] = [];
		const failed: FailResult[] = [];

		if (platform === "threads") {
			const tokens = await getAllAccessTokens(user.id);
			if (!tokens.length)
				return apiError(res, 400, "No connected Threads account");

			// Process sequentially to avoid rate-limiting Meta API
			for (const username of uniqueUsernames) {
				const result = await addThreadsCompetitor(user.id, username, tokens);
				if (result.success && result.competitor) {
					added.push({ username, competitor: result.competitor });
				} else {
					failed.push({ username, reason: result.error || "Unknown error" });
				}
			}
		} else {
			// Instagram — requires accountId
			if (!accountId)
				return apiError(res, 400, "accountId required for Instagram");

			for (const username of uniqueUsernames) {
				const result = await addIgCompetitor(user.id, username, accountId);
				if (result.success && result.competitor) {
					added.push({ username, competitor: result.competitor });
				} else {
					failed.push({ username, reason: result.error || "Unknown error" });
				}
			}
		}

		return apiSuccess(res, {
			added,
			failed,
			total: uniqueUsernames.length,
			addedCount: added.length,
			failedCount: failed.length,
		});
	},
);
