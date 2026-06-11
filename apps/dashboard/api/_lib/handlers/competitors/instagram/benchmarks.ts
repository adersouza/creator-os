/**
 * Handlers: GET /api/competitors?action=ig-benchmarks
 *           GET /api/competitors?action=ig-content-breakdown
 *
 * Instagram benchmarking and content type breakdown analytics.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	getAuthUserOrError,
} from "../../../apiResponse.js";
import { cached } from "../../../redisCache.js";
import { db } from "../shared.js";

interface IgCompetitorRow {
	id: string;
	username: string;
	follower_count: number | null;
	engagement_rate: number | null;
	avg_likes: number | null;
	avg_comments: number | null;
	media_count: number | null;
}

interface IgAccountRow {
	followers_count?: number | null | undefined;
	engagement_rate?: number | null | undefined;
	avg_likes?: number | null | undefined;
	avg_comments?: number | null | undefined;
	media_count?: number | null | undefined;
}

interface CompetitorIdRow {
	id: string;
}

export async function handleIgBenchmarks(
	req: VercelRequest,
	res: VercelResponse,
) {
	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const accountId = req.query.accountId as string;
	if (!accountId) return apiError(res, 400, "accountId required");

	const result = await cached(
		`competitor-benchmarks:${user.id}:${accountId}`,
		300,
		async () => {
			// Get user's IG account stats
			const { data: igAccount } = (await db()
				.from("instagram_accounts")
				.select("*")
				.eq("id", accountId)
				.eq("user_id", user.id)
				.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

			// Get all IG competitors for this user
			const { data: competitors } = await db()
				.from("competitors")
				.select(
					"id, username, follower_count, engagement_rate, avg_likes, avg_comments, media_count",
				)
				.eq("user_id", user.id)
				.eq("platform", "instagram");

			if (!competitors || competitors.length === 0) {
				return {
					benchmarks: null,
					message: "No IG competitors",
				};
			}

			const typedCompetitors = competitors as IgCompetitorRow[];
			const compCount = typedCompetitors.length;
			const avgFollowers = Math.round(
				typedCompetitors.reduce(
					(s: number, c: IgCompetitorRow) => s + (c.follower_count || 0),
					0,
				) / compCount,
			);
			const avgEngRate =
				Math.round(
					(typedCompetitors.reduce(
						(s: number, c: IgCompetitorRow) => s + (c.engagement_rate || 0),
						0,
					) /
						compCount) *
						100,
				) / 100;
			const avgLikes = Math.round(
				typedCompetitors.reduce(
					(s: number, c: IgCompetitorRow) => s + (c.avg_likes || 0),
					0,
				) / compCount,
			);
			const avgComments = Math.round(
				typedCompetitors.reduce(
					(s: number, c: IgCompetitorRow) => s + (c.avg_comments || 0),
					0,
				) / compCount,
			);
			const avgMediaCount = Math.round(
				typedCompetitors.reduce(
					(s: number, c: IgCompetitorRow) => s + (c.media_count || 0),
					0,
				) / compCount,
			);

			return {
				benchmarks: {
					competitorCount: compCount,
					averages: {
						followers: avgFollowers,
						engagementRate: avgEngRate,
						avgLikes,
						avgComments,
						mediaCount: avgMediaCount,
					},
					userAccount: igAccount
						? {
								followers: igAccount.followers_count || 0,
								engagementRate: igAccount.engagement_rate || 0,
								avgLikes: igAccount.avg_likes || 0,
								avgComments: igAccount.avg_comments || 0,
								mediaCount: igAccount.media_count || 0,
							}
						: null,
					competitors: typedCompetitors.map((c: IgCompetitorRow) => ({
						id: c.id,
						username: c.username,
						followers: c.follower_count || 0,
						engagementRate: c.engagement_rate || 0,
						avgLikes: c.avg_likes || 0,
						avgComments: c.avg_comments || 0,
						mediaCount: c.media_count || 0,
					})),
				},
			};
		},
	);

	return apiSuccess(res, result);
}

export async function handleIgContentBreakdown(
	req: VercelRequest,
	res: VercelResponse,
) {
	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const result = await cached(
		`competitor-content-breakdown:${user.id}`,
		120,
		async () => {
			// Get user's IG competitors
			const { data: competitors } = await db()
				.from("competitors")
				.select("id")
				.eq("user_id", user.id)
				.eq("platform", "instagram");

			if (!competitors || competitors.length === 0) {
				return { breakdown: [] };
			}

			const competitorIds = (competitors as CompetitorIdRow[]).map(
				(c: CompetitorIdRow) => c.id,
			);

			// Get all IG top posts grouped by media_type
			const { data: posts } = await db()
				.from("competitor_top_posts")
				.select("media_type, like_count, comments_count, engagement_score")
				.in("competitor_id", competitorIds)
				.eq("platform", "instagram");

			if (!posts || posts.length === 0) {
				return { breakdown: [] };
			}

			// Group by media_type
			const groups: Record<
				string,
				{
					count: number;
					totalLikes: number;
					totalComments: number;
					totalScore: number;
				}
			> = {};
			for (const post of posts) {
				const type = post.media_type || "IMAGE";
				if (!groups[type]) {
					groups[type] = {
						count: 0,
						totalLikes: 0,
						totalComments: 0,
						totalScore: 0,
					};
				}
				groups[type].count++;
				groups[type].totalLikes += post.like_count || 0;
				groups[type].totalComments += post.comments_count || 0;
				groups[type].totalScore += post.engagement_score || 0;
			}

			const breakdown = Object.entries(groups).map(([mediaType, g]) => ({
				mediaType,
				count: g.count,
				avgLikes: Math.round(g.totalLikes / g.count),
				avgComments: Math.round(g.totalComments / g.count),
				avgEngagementScore: Math.round(g.totalScore / g.count),
			}));

			return { breakdown };
		},
	);

	return apiSuccess(res, result);
}
