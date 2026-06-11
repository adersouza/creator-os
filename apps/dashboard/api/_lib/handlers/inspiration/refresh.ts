// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Refresh inspiration — scan competitors, generate new AI-adapted ideas.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	badRequest,
	serverError,
} from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getUserTier } from "../../tierGate.js";
import {
	type AccountTokenRow,
	type CompetitorRow,
	db,
	decrypt,
	fetchCompetitorPostsFromDB,
	fetchIGCompetitorPosts,
	generateInspirationIdea,
	getSupabaseAny,
	getUserAIConfig,
	type IgAccountRow,
	type InspirationConfigRow,
	TIER_LIMITS,
} from "./shared.js";

export async function handleRefresh(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	// Check tier for cooldown
	const tier = await getUserTier(userId);
	const limits =
		TIER_LIMITS[tier as keyof typeof TIER_LIMITS] || TIER_LIMITS.free;

	const rl = await checkRateLimit({
		key: `inspiration-refresh:${userId}`,
		limit: 10,
		windowSeconds: 60 * 60,
		failMode: "closed",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Rate limit exceeded");
	}

	// Get user's config to check last scan time and style
	const { data: configRaw } = await db()
		.from("inspiration_config")
		.select("last_scan_at, adaptation_style, ideas_per_competitor")
		.eq("user_id", userId)
		.maybeSingle();

	const config = configRaw as InspirationConfigRow | null;

	if (config?.last_scan_at && limits.manualRefreshCooldown > 0) {
		const lastScan = new Date(config.last_scan_at);
		const cooldownMs = limits.manualRefreshCooldown * 60 * 1000;
		const nextAllowed = new Date(lastScan.getTime() + cooldownMs);

		if (new Date() < nextAllowed) {
			const minutesRemaining = Math.ceil(
				(nextAllowed.getTime() - Date.now()) / 60000,
			);
			return apiError(
				res,
				429,
				`Refresh cooldown: ${minutesRemaining} minutes remaining`,
			);
		}
	}

	// Get user's AI config
	const aiConfig = await getUserAIConfig(userId);
	if (!aiConfig) {
		return badRequest(
			res,
			"Please configure your AI API key in Settings → AI Provider",
		);
	}

	// Get user's connected accounts for API access
	const { data: accountsRaw } = await db()
		.from("accounts")
		.select("id, threads_access_token_encrypted")
		.eq("user_id", userId)
		.not("threads_access_token_encrypted", "is", null);

	const accounts = (accountsRaw || []) as AccountTokenRow[];

	if (!accounts?.length) {
		return badRequest(res, "Please connect a Threads account first");
	}

	// Use accountId from request body if provided, otherwise fall back to first account
	const requestAccountId = req.body?.accountId as string | undefined;
	const targetAccount = requestAccountId
		? accounts.find((a: AccountTokenRow) => a.id === requestAccountId) ||
			accounts[0]
		: accounts[0];

	try {
		decrypt(targetAccount!.threads_access_token_encrypted);
	} catch (err) {
		logger.warn("Failed to decrypt access token for inspiration refresh", {
			accountId: targetAccount!.id,
			error: String(err),
		});
		return serverError(res, "Failed to decrypt access token");
	}

	// Get user's competitors
	const { data: competitorsRaw } = await db()
		.from("competitors")
		.select("id, username, avatar_url, threads_user_id")
		.eq("user_id", userId);

	const competitors = (competitorsRaw || []) as CompetitorRow[];

	if (!competitors?.length) {
		return badRequest(
			res,
			"Please add competitors to track in the Competitors tab",
		);
	}

	const adaptationStyle = config?.adaptation_style || "casual";
	const maxIdeasPerCompetitor = config?.ideas_per_competitor || 5;
	const dailyLimit = limits.dailyIdeas === Infinity ? 100 : limits.dailyIdeas;

	// Check how many ideas generated today
	const today = new Date().toISOString().split("T")[0]!;
	const { count: todayCount } = await db()
		.from("inspiration_ideas")
		.select("*", { count: "exact", head: true })
		.eq("user_id", userId)
		.gte("generated_at", `${today}T00:00:00Z`);

	const remainingQuota = dailyLimit - (todayCount || 0);
	if (remainingQuota <= 0) {
		return apiError(
			res,
			429,
			"Daily idea limit reached. Upgrade your plan or wait until tomorrow.",
		);
	}

	let totalIdeasGenerated = 0;
	let totalPostsFound = 0;
	let totalSkippedExisting = 0;
	let competitorsWithNoPosts = 0;

	// Check for IG accounts (for Business Discovery fallback)
	let igAccount: IgAccountRow | null = null;
	const requestIgAccountId = req.body?.igAccountId as string | undefined;
	try {
		const { data: igAccounts } = await db()
			.from("instagram_accounts")
			.select(
				"id, instagram_user_id, instagram_access_token_encrypted, login_type",
			)
			.eq("user_id", userId)
			.eq("is_active", true)
			.not("instagram_access_token_encrypted", "is", null);
		if (igAccounts?.length) {
			// Use specified IG account if provided, otherwise fall back to first
			igAccount = requestIgAccountId
				? igAccounts.find((a) => a.id === requestIgAccountId) || igAccounts[0]!
				: igAccounts[0]!;
		}
	} catch (err) {
		logger.debug("Failed to fetch IG accounts for inspiration", {
			userId,
			error: String(err),
		});
	}

	// Process each competitor
	for (const competitor of competitors) {
		if (totalIdeasGenerated >= remainingQuota) break;
		if (!competitor.username) continue;

		// Fetch competitor's posts from database (synced by competitors API)
		let posts = await fetchCompetitorPostsFromDB(
			competitor.id,
			maxIdeasPerCompetitor,
		);

		// Fallback: if no DB posts and IG account available, try Business Discovery
		if (!posts.length && igAccount && igAccount.login_type === "facebook") {
			logger.info("[inspiration:ig] Trying IG Business Discovery", {
				username: competitor.username,
			});
			const igPosts = await fetchIGCompetitorPosts(
				igAccount.instagram_access_token_encrypted ?? "",
				igAccount.instagram_user_id ?? "",
				competitor.username,
				maxIdeasPerCompetitor,
				igAccount.login_type ?? undefined,
			);
			if (igPosts.length) posts = igPosts;
		}

		if (!posts.length) {
			competitorsWithNoPosts++;
			continue;
		}
		totalPostsFound += posts.length;

		// Posts are already sorted by engagement score from the DB query
		const topPosts = posts;

		for (const post of topPosts) {
			if (totalIdeasGenerated >= remainingQuota) break;
			if (!post.content || post.content.length < 20) continue;

			// Check if we already have an idea for this post
			const { count: existingCount } = await getSupabaseAny()
				.from("inspiration_ideas")
				.select("*", { count: "exact", head: true })
				.eq("user_id", userId)
				.eq("original_post->id", post.id);

			if (existingCount && existingCount > 0) {
				totalSkippedExisting++;
				continue;
			}

			// Generate AI adaptation
			const idea = await generateInspirationIdea(
				post.content,
				competitor.username,
				adaptationStyle,
				aiConfig,
				userId,
			);

			if (!idea) continue;

			// Store in database
			const engagementScore =
				post.likeCount + post.replyCount * 3 + post.repostCount * 2;

			await db()
				.from("inspiration_ideas")
				.insert({
					user_id: userId,
					workspace_id: null, // Cron context — no workspace scope; NULL = visible to owner in all workspaces
					original_post: {
						id: post.id,
						content: post.content,
						engagementScore,
					},
					competitor_id: competitor.id,
					competitor_username: competitor.username,
					competitor_avatar_url: competitor.avatar_url ?? null,
					adapted_content: idea.content,
					viral_score: idea.viralScore,
					ai_insight: idea.insight,
					topic_tags: idea.tags,
					adaptation_style: adaptationStyle,
					status: "pending",
					generated_at: new Date().toISOString(),
					expires_at: new Date(
						Date.now() + 7 * 24 * 60 * 60 * 1000,
					).toISOString(),
				});

			totalIdeasGenerated++;
		}
	}

	// Update last scan time
	await db().from("inspiration_config").upsert({
		user_id: userId,
		last_scan_at: new Date().toISOString(),
	});

	// Build informative message
	let message = `Generated ${totalIdeasGenerated} new ideas`;
	if (totalIdeasGenerated === 0) {
		if (competitorsWithNoPosts === competitors.length) {
			message =
				"No posts synced for your competitors yet. Go to the Feed tab and sync your competitors first.";
		} else if (totalSkippedExisting > 0) {
			message = `All ${totalSkippedExisting} posts already have ideas. Wait for competitors to post new content.`;
		} else if (totalPostsFound === 0) {
			message = "No posts found. Sync your competitors in the Feed tab first.";
		}
	}

	return apiSuccess(res, {
		message,
		ideasGenerated: totalIdeasGenerated,
		stats: {
			competitorsChecked: competitors.length,
			competitorsWithNoPosts,
			postsFound: totalPostsFound,
			skippedExisting: totalSkippedExisting,
		},
	});
}
