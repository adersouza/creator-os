/**
 * Competitor pattern benchmark — corpus intelligence, not fake impressions.
 *
 * GET /api/analytics?action=competitor-pattern-benchmark&days=30&accountId=optional
 *
 * Threads competitor post-level stats are not reliable from the official API.
 * This endpoint benchmarks observable content patterns instead.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabaseAny } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { classifyCompetitorPattern } from "../competitors/metricQuality.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	days: z.coerce.number().int().min(7).max(180).optional().default(30),
	limit: z.coerce.number().int().min(1).max(20).optional().default(10),
});

const db = () => getSupabaseAny();

type Distribution = Array<{ key: string; count: number; pct: number }>;

interface CorpusRow {
	content: string | null;
	media_type: string | null;
	published_at: string | null;
	scraped_at: string | null;
	hook_type: string | null;
	topic_label: string | null;
	format_type: string | null;
	emotional_frame: string | null;
	cta_style: string | null;
	content_length_bucket: string | null;
	media_style: string | null;
	posting_hour: number | null;
	controversy_level: string | null;
	reply_mechanism: string | null;
	account_size_bucket: string | null;
	metric_quality: string | null;
}

interface OwnPostRow {
	content: string | null;
	media_type: string | null;
	published_at: string | null;
	topic_tag: string | null;
}

function keyOrUnknown(value: string | null | undefined): string {
	const trimmed = value?.trim();
	return trimmed || "unknown";
}

function distribution(values: string[], limit: number): Distribution {
	const counts = new Map<string, number>();
	for (const value of values) counts.set(value, (counts.get(value) || 0) + 1);
	const total = values.length || 1;
	return [...counts.entries()]
		.sort((a, b) => b[1] - a[1])
		.slice(0, limit)
		.map(([key, count]) => ({
			key,
			count,
			pct: Math.round((count / total) * 1000) / 10,
		}));
}

function hourOf(row: {
	published_at?: string | null;
	scraped_at?: string | null;
}) {
	const raw = row.published_at || row.scraped_at;
	if (!raw) return "unknown";
	const date = new Date(raw);
	if (!Number.isFinite(date.getTime())) return "unknown";
	return String(date.getUTCHours()).padStart(2, "0");
}

function storedHourOf(row: {
	posting_hour?: number | null;
	published_at?: string | null;
	scraped_at?: string | null;
}) {
	if (Number.isInteger(row.posting_hour)) {
		return String(row.posting_hour).padStart(2, "0");
	}
	return hourOf(row);
}

function cadencePerDay(rows: CorpusRow[], days: number): number {
	if (days <= 0) return 0;
	return Math.round((rows.length / days) * 100) / 100;
}

function underusedPatterns(
	competitorDist: Distribution,
	ownDist: Distribution,
	limit: number,
) {
	const ownByKey = new Map(ownDist.map((item) => [item.key, item.pct]));
	return competitorDist
		.map((item) => ({
			key: item.key,
			competitorPct: item.pct,
			ourPct: ownByKey.get(item.key) || 0,
			gapPct: Math.round((item.pct - (ownByKey.get(item.key) || 0)) * 10) / 10,
		}))
		.filter((item) => item.gapPct > 0)
		.sort((a, b) => b.gapPct - a.gapPct)
		.slice(0, limit);
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, days, limit } = parsed;

		if (accountId) {
			const account = await verifyAccountOwnership(res, accountId, user.id);
			if (!account) return;
		}

		const cutoff = new Date(Date.now() - days * 86_400_000).toISOString();

		const { data: competitors } = await db()
			.from("competitors")
			.select("id")
			.eq("user_id", user.id)
			.or("sync_status.eq.active,sync_status.is.null");

		const competitorIds = (competitors || []).map((c: { id: string }) => c.id);
		if (competitorIds.length === 0) {
			return apiSuccess(res, {
				periodDays: days,
				competitorPostCount: 0,
				message: "No tracked competitors available.",
			});
		}

		const { data: corpusRows, error: corpusError } = await db()
			.from("competitor_top_posts")
			.select(
				"content, media_type, published_at, scraped_at, hook_type, topic_label, format_type, emotional_frame, cta_style, content_length_bucket, media_style, posting_hour, controversy_level, reply_mechanism, account_size_bucket, metric_quality",
			)
			.in("competitor_id", competitorIds)
			.gte("scraped_at", cutoff)
			.not("content", "is", null)
			.neq("content", "");

		if (corpusError) {
			return apiError(res, 500, "Failed to fetch competitor corpus", {
				details: corpusError.message,
			});
		}

		let ownQuery = db()
			.from("posts")
			.select("content, media_type, published_at, topic_tag")
			.eq("user_id", user.id)
			.gte("published_at", cutoff)
			.not("content", "is", null);
		if (accountId) ownQuery = ownQuery.eq("account_id", accountId);
		const { data: ownRows } = await ownQuery;

		const corpus = (corpusRows || []) as CorpusRow[];
		const ownPosts = ((ownRows || []) as OwnPostRow[]).map((post) => ({
			...post,
			...classifyCompetitorPattern({
				content: post.content,
				topicTag: post.topic_tag,
				mediaType: post.media_type,
				publishedAt: post.published_at,
			}),
		}));

		const competitor = {
			postingHours: distribution(corpus.map(storedHourOf), limit),
			cadencePerDay: cadencePerDay(corpus, days),
			hookDistribution: distribution(
				corpus.map((row) => keyOrUnknown(row.hook_type)),
				limit,
			),
			formatDistribution: distribution(
				corpus.map((row) => keyOrUnknown(row.format_type)),
				limit,
			),
			topicDistribution: distribution(
				corpus.map((row) => keyOrUnknown(row.topic_label)),
				limit,
			),
			mediaDistribution: distribution(
				corpus.map((row) => keyOrUnknown(row.media_type || "TEXT")),
				limit,
			),
			mediaStyleDistribution: distribution(
				corpus.map((row) => keyOrUnknown(row.media_style)),
				limit,
			),
			lengthDistribution: distribution(
				corpus.map((row) => keyOrUnknown(row.content_length_bucket)),
				limit,
			),
			emotionalFrameDistribution: distribution(
				corpus.map((row) => keyOrUnknown(row.emotional_frame)),
				limit,
			),
			ctaDistribution: distribution(
				corpus.map((row) => keyOrUnknown(row.cta_style)),
				limit,
			),
			replyMechanismDistribution: distribution(
				corpus.map((row) => keyOrUnknown(row.reply_mechanism)),
				limit,
			),
			metricQualityDistribution: distribution(
				corpus.map((row) => keyOrUnknown(row.metric_quality)),
				limit,
			),
		};

		const ours = {
			postingHours: distribution(ownPosts.map(storedHourOf), limit),
			cadencePerDay: cadencePerDay(ownPosts as unknown as CorpusRow[], days),
			hookDistribution: distribution(
				ownPosts.map((row) => keyOrUnknown(row.hook_type)),
				limit,
			),
			formatDistribution: distribution(
				ownPosts.map((row) => keyOrUnknown(row.format_type)),
				limit,
			),
			topicDistribution: distribution(
				ownPosts.map((row) => keyOrUnknown(row.topic_label)),
				limit,
			),
			mediaDistribution: distribution(
				ownPosts.map((row) => keyOrUnknown(row.media_type || "TEXT")),
				limit,
			),
			mediaStyleDistribution: distribution(
				ownPosts.map((row) => keyOrUnknown(row.media_style)),
				limit,
			),
			lengthDistribution: distribution(
				ownPosts.map((row) => keyOrUnknown(row.content_length_bucket)),
				limit,
			),
		};

		return apiSuccess(res, {
			periodDays: days,
			accountId: accountId || null,
			competitorPostCount: corpus.length,
			ourPostCount: ownPosts.length,
			metricWarning:
				"Competitor Threads post-level views are not reliable; this report benchmarks observable patterns, not impressions.",
			competitor,
			ours,
			underusedPatterns: {
				hooks: underusedPatterns(
					competitor.hookDistribution,
					ours.hookDistribution,
					limit,
				),
				topics: underusedPatterns(
					competitor.topicDistribution,
					ours.topicDistribution,
					limit,
				),
				lengths: underusedPatterns(
					competitor.lengthDistribution,
					ours.lengthDistribution,
					limit,
				),
				formats: underusedPatterns(
					competitor.formatDistribution,
					ours.formatDistribution,
					limit,
				),
				mediaTypes: underusedPatterns(
					competitor.mediaDistribution,
					ours.mediaDistribution,
					limit,
				),
				mediaStyles: underusedPatterns(
					competitor.mediaStyleDistribution,
					ours.mediaStyleDistribution,
					limit,
				),
				postingHours: underusedPatterns(
					competitor.postingHours,
					ours.postingHours,
					limit,
				),
			},
			recommendations: underusedPatterns(
				competitor.hookDistribution,
				ours.hookDistribution,
				5,
			).map((item) => ({
				pattern: item.key,
				reason: `Competitors use this hook ${item.gapPct}% more often in the observed corpus.`,
			})),
		});
	},
);
