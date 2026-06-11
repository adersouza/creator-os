// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * POST /api/onboarding/instant-analysis
 *
 * Analyzes user's last 5 posts and returns instant insights:
 * - Best post with viral score
 * - CES baseline
 * - Best posting time
 * - Top quick win recommendation
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabaseAny } from "../../supabase.js";

const db = () => getSupabaseAny();

const DAYS = [
	"Sunday",
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
];

function formatHour(h: number): string {
	if (h === 0) return "12:00 AM";
	if (h === 12) return "12:00 PM";
	return h < 12 ? `${h}:00 AM` : `${h - 12}:00 PM`;
}

/**
 * Simplified viral score for onboarding — inline to avoid import issues.
 * Uses content heuristics only (no historical data needed).
 */
function quickViralScore(post: Record<string, unknown>, platform: string) {
	const content = String(post.content || post.text || post.caption || "");
	// Reply potential
	let replyScore = 5;
	const firstLine = content.split("\n")[0] || "";
	if (
		firstLine.endsWith("?") ||
		/^(what|why|how|who|when|where|which|do you)/i.test(firstLine)
	) {
		replyScore += 3;
	}
	if (
		/\b(thoughts|agree|what do you think|tell me|hot take)\b/i.test(content)
	) {
		replyScore += 2;
	}
	replyScore = Math.min(10, Math.max(1, replyScore));

	// Completion signal
	let completionScore = 5;
	const lines = content.split("\n").filter((l: string) => l.trim());
	if (lines.length >= 3) completionScore += 1;
	if (
		/^(I |Here's|The truth|Most people|Nobody|Everyone|Stop|Don't|[0-9]+ )/i.test(
			content.trim(),
		)
	) {
		completionScore += 1;
	}
	completionScore = Math.min(10, Math.max(1, completionScore));

	// Timing (neutral without best-times data)
	const timingScore = 5;

	// Type score
	const hasMedia =
		post.media_type === "IMAGE" ||
		post.media_type === "VIDEO" ||
		post.media_type === "CAROUSEL_ALBUM";
	const typeScore = hasMedia ? 7 : 5;

	// Caption
	const captionLen = content.length;
	const optimalMin = platform === "threads" ? 50 : 100;
	const optimalMax = platform === "threads" ? 280 : 500;
	let captionScore = 5;
	if (captionLen >= optimalMin && captionLen <= optimalMax) captionScore = 9;
	else if (captionLen > 0 && captionLen < optimalMin)
		captionScore = Math.max(3, Math.round((captionLen / optimalMin) * 7));
	else if (captionLen > optimalMax)
		captionScore = Math.max(4, 9 - Math.floor((captionLen - optimalMax) / 100));
	else captionScore = 2;

	// Hashtags
	const hashtags = content.match(/#[\w]+/g) || [];
	let hashtagScore = platform === "threads" ? 6 : 3;
	if (hashtags.length > 0) {
		const optimal = platform === "threads" ? 3 : 8;
		const countScore = Math.max(
			0,
			1 - Math.abs(hashtags.length - optimal) / optimal,
		);
		hashtagScore = Math.min(10, Math.max(1, Math.round(countScore * 10)));
	}

	const weighted =
		replyScore * 0.3 +
		completionScore * 0.2 +
		timingScore * 0.2 +
		typeScore * 0.15 +
		captionScore * 0.1 +
		hashtagScore * 0.05;

	const finalScore = Math.min(10, Math.max(1, Math.round(weighted * 10) / 10));

	return {
		score: finalScore,
		breakdown: {
			replyPotential: replyScore,
			completionSignal: completionScore,
			timing: timingScore,
			type: typeScore,
			caption: captionScore,
			hashtags: hashtagScore,
		},
		confidence: "low" as const,
		confidenceLabel: "Early data",
	};
}

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const { accountId, platform } = req.body || {};
	if (!accountId || !platform) {
		return apiError(res, 400, "accountId and platform are required");
	}

	try {
		// #589: Check Redis cache first — 1-hour TTL so new data is picked up frequently.
		// If confidence is "low" (<10 posts), we skip caching so it refreshes immediately
		// when the user posts more content.
		const cacheKey = `instant-analysis:${accountId}:${platform}`;
		try {
			const { getRedis } = await import("../../redis.js");
			const redis = getRedis();
			const cachedRaw = await redis.get(`cache:${cacheKey}`);
			if (cachedRaw) {
				const cachedData =
					typeof cachedRaw === "string" ? JSON.parse(cachedRaw) : cachedRaw;
				// Only serve from cache if confidence is not "low"
				if (cachedData?.data?.confidence !== "low") {
					logger.info("[instant-analysis] Serving from cache", {
						accountId,
						platform,
						confidence: cachedData?.data?.confidence,
					});
					return apiSuccess(res, cachedData);
				}
				// Low confidence — skip cache, re-compute
			}
		} catch {
			// Redis unavailable — proceed with fresh computation
		}

		// Verify account ownership
		const accountTable =
			platform === "instagram" ? "instagram_accounts" : "accounts";
		const { data: account } = await db()
			.from(accountTable)
			.select("id")
			.eq("id", accountId)
			.eq("user_id", user.id)
			.single();

		if (!account) {
			return apiError(res, 404, "Account not found");
		}

		// 1. Fetch last 5 posts
		const postsTable = platform === "instagram" ? "instagram_posts" : "posts";
		const accountCol =
			platform === "instagram" ? "instagram_account_id" : "account_id";

		const { data: posts, error: postsErr } = await db()
			.from(postsTable)
			.select("*")
			.eq(accountCol, accountId)
			.not("published_at", "is", null)
			.order("published_at", { ascending: false })
			.limit(5);

		if (postsErr) {
			logger.error("[instant-analysis] Posts fetch error", {
				error: String(postsErr),
			});
			return apiError(res, 500, "Failed to fetch posts");
		}

		const postCount = posts?.length || 0;

		if (!posts || posts.length === 0) {
			return apiSuccess(res, {
				data: {
					bestPost: null,
					cesScore: 0,
					bestTime: null,
					topQuickWin: null,
					postCount: 0,
					avgEngagementRate: 0,
				},
			});
		}

		// 2. Calculate viral score for each post, find best
		let bestPost = null;
		let bestScore = -1;

		for (const post of posts) {
			const vs = quickViralScore(post, platform);
			if (vs.score > bestScore) {
				bestScore = vs.score;
				bestPost = {
					id: post.id,
					content: post.content || post.text || post.caption || "",
					thumbnailUrl: post.media_url || post.thumbnail_url || null,
					viralScore: vs,
					views: post.views || 0,
					likes: post.likes || 0,
					replies: post.replies_count || post.replies || post.comments || 0,
				};
			}
		}

		// 3. Calculate CES (Creator Efficiency Score)
		let totalEngagement = 0;
		let totalReach = 0;
		for (const post of posts) {
			const likes = post.likes || 0;
			const replies = post.replies_count || post.replies || post.comments || 0;
			const reposts = post.reposts || post.shares || 0;
			totalEngagement += likes + replies + reposts;
			totalReach += post.views || post.reach || 0;
		}
		const cesScore =
			totalReach > 0
				? Math.round((totalEngagement / totalReach) * 1000) / 10
				: 0;

		// 4. Find best posting time
		const engagementBySlot: Record<
			string,
			{ total: number; count: number; day: string; hour: string }
		> = {};
		for (const post of posts) {
			if (!post.published_at) continue;
			const d = new Date(post.published_at);
			const day = DAYS[d.getDay()];
			const hour = formatHour(d.getHours());
			const key = `${day}-${hour}`;
			const eng =
				(post.likes || 0) +
				(post.replies_count || post.replies || post.comments || 0);
			if (!engagementBySlot[key])
				engagementBySlot[key] = { total: 0, count: 0, day: day!, hour };
			engagementBySlot[key]!.total += eng;
			engagementBySlot[key]!.count++;
		}

		let bestTime = null;
		let bestTimeScore = -1;
		for (const slot of Object.values(engagementBySlot)) {
			const avg = slot.total / slot.count;
			if (avg > bestTimeScore) {
				bestTimeScore = avg;
				bestTime = {
					day: slot.day,
					hour: slot.hour,
					score: Math.min(10, Math.round(avg)),
				};
			}
		}

		// 5. Get top quick win
		let topQuickWin = null;
		try {
			const { getLowHangingFruit } = await import("../../lowHangingFruit.js");
			const result = await getLowHangingFruit(user.id, accountId, platform);
			if (result.recommendations.length > 0) {
				const rec = result.recommendations[0];
				topQuickWin = {
					title: rec!.title,
					description: rec!.description,
					icon: rec!.icon,
					impactScore: rec!.impactScore,
				};
			}
		} catch (e) {
			logger.warn("[instant-analysis] Quick win lookup failed", {
				error: String(e),
			});
		}

		// 6. Avg engagement rate
		const avgEngagementRate =
			totalReach > 0 ? (totalEngagement / totalReach) * 100 : 0;

		// #586: Flag low confidence when <10 posts — best posting time is unreliable
		const confidence =
			postCount >= 20 ? "high" : postCount >= 10 ? "medium" : "low";
		const confidenceNote =
			confidence === "low"
				? "Based on limited data — results will improve as you post more."
				: confidence === "medium"
					? "Moderate confidence — keep posting for better insights."
					: undefined;

		const responseData = {
			data: {
				bestPost,
				cesScore,
				bestTime,
				topQuickWin,
				postCount,
				avgEngagementRate: Math.round(avgEngagementRate * 100) / 100,
				confidence,
				confidenceNote,
			},
		};

		// #589: Cache the result in Redis — but only if confidence is not "low".
		// Low confidence (<10 posts) should re-compute immediately when user adds more posts.
		if (confidence !== "low") {
			try {
				const { getRedis } = await import("../../redis.js");
				const redis = getRedis();
				await redis.set(
					`cache:${cacheKey}`,
					JSON.stringify(responseData),
					{ ex: 3600 }, // 1-hour TTL
				);
			} catch {
				// Redis unavailable — non-critical
			}
		}

		return apiSuccess(res, responseData);
	} catch (err) {
		logger.error("[instant-analysis] Unhandled error", { error: String(err) });
		return apiError(res, 500, "Internal server error");
	}
});
