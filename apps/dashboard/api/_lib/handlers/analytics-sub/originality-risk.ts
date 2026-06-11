// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Originality risk — derived from recent fleet post reuse.
 *
 * Meta does not expose a public originality penalty signal. This v1 uses
 * existing post text + recycling metadata to surface accounts approaching the
 * "too much reused content" danger zone without pretending to inspect media
 * fingerprints or native-only ranking signals.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { perceptualHashSimilarity } from "../../originalitySignals.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { z, zEnum } from "../../zodCompat.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	periodDays: z.coerce.number().int().min(14).max(90).optional().default(30),
	platform: zEnum(["all", "instagram", "threads"]).optional().default("all"),
});

// biome-ignore lint/suspicious/noExplicitAny: generated DB types lag analytics columns
const db = (): any => getSupabase();

interface AccountRow {
	id: string;
	username: string | null;
	platform: "threads" | "instagram";
}

interface PostRow {
	id: string;
	content: string | null;
	account_id: string | null;
	instagram_account_id: string | null;
	published_at: string | null;
	recycle_count: number | null;
	recycled_from_id: string | null;
	last_recycled_at: string | null;
	views_count: number | null;
	ig_reach: number | null;
	media_urls: string[] | null;
	metadata: Record<string, unknown> | null;
}

interface SignalRow {
	post_id: string;
	text_hash: string | null;
	media_url_hashes: string[] | null;
	perceptual_hashes: string[] | null;
	watermark_applied: boolean | null;
}

interface AnalyzedPost extends PostRow {
	accountKey: string;
	accountId: string;
	platform: "threads" | "instagram";
	username: string | null;
	normalized: string;
	shingles: Set<string>;
	signals: SignalRow | null;
}

const HIGH_SIMILARITY = 0.78;
const MEDIUM_SIMILARITY = 0.64;
const META_THRESHOLD_POSTS = 10;

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds, periodDays, platform } = parsed;
		const requestedAccountIds = new Set(
			(accountIds ?? "")
				.split(",")
				.map((id) => id.trim())
				.filter(Boolean),
		);

		const [threadsRes, igRes] = await Promise.all([
			platform === "instagram"
				? Promise.resolve({ data: [] })
				: db()
						.from("accounts")
						.select("id, username")
						.eq("user_id", user.id)
						.eq("is_active", true)
						.eq("is_retired", false),
			platform === "threads"
				? Promise.resolve({ data: [] })
				: db()
						.from("instagram_accounts")
						.select("id, username")
						.eq("user_id", user.id)
						.eq("is_active", true),
		]);

		const accounts: AccountRow[] = [
			...(
				(threadsRes.data || []) as Array<{
					id: string;
					username: string | null;
				}>
			).map((a) => ({ ...a, platform: "threads" as const })),
			...(
				(igRes.data || []) as Array<{ id: string; username: string | null }>
			).map((a) => ({ ...a, platform: "instagram" as const })),
		];

		const accountByKey = new Map(
			accounts.map((account) => [`${account.platform}:${account.id}`, account]),
		);
		let scopedKeys = new Set(accountByKey.keys());
		if (accountId && accountId !== "ALL") {
			scopedKeys = new Set(
				[...accountByKey.keys()].filter((key) => key.endsWith(`:${accountId}`)),
			);
		} else if (requestedAccountIds.size > 0) {
			scopedKeys = new Set(
				[...accountByKey.keys()].filter((key) => {
					const [, id] = key.split(":");
					return id ? requestedAccountIds.has(id) : false;
				}),
			);
		}

		if (scopedKeys.size === 0) {
			return apiSuccess(res, emptyResponse(periodDays, platform));
		}

		const cutoff = new Date(Date.now() - periodDays * 86_400_000).toISOString();
		const { data: rows, error } = await db()
			.from("posts")
			.select(
				"id, content, account_id, instagram_account_id, published_at, recycle_count, recycled_from_id, last_recycled_at, views_count, ig_reach, media_urls, metadata",
			)
			.eq("user_id", user.id)
			.eq("status", "published")
			.gte("published_at", cutoff)
			.order("published_at", { ascending: false })
			.limit(500);

		if (error) {
			return apiError(res, 500, "Failed to compute originality risk");
		}
		const postRows = (rows || []) as PostRow[];
		const signalMap = await loadOriginalitySignals(
			postRows,
			platform,
			accountByKey,
			scopedKeys,
		);

		const analyzed = postRows
			.map((post): AnalyzedPost | null => {
				const platformGuess = post.instagram_account_id
					? "instagram"
					: "threads";
				const id = post.instagram_account_id ?? post.account_id;
				if (!id) return null;
				const key = `${platformGuess}:${id}`;
				const account = accountByKey.get(key);
				if (!account || !scopedKeys.has(key)) return null;
				const normalized = normalizeOriginalityContent(post.content || "");
				if (normalized.length < 18 && !post.recycled_from_id) return null;
				return {
					...post,
					accountKey: key,
					accountId: id,
					platform: platformGuess,
					username: account.username,
					normalized,
					shingles: originalityShingles(normalized),
					signals: signalMap.get(post.id) ?? null,
				};
			})
			.filter((post): post is AnalyzedPost => Boolean(post));

		const riskyPostIds = new Set<string>();
		const pairs: Array<{
			a: AnalyzedPost;
			b: AnalyzedPost;
			similarity: number;
			severity: "high" | "medium";
		}> = [];

		for (let i = 0; i < analyzed.length; i++) {
			for (let j = i + 1; j < analyzed.length; j++) {
				const a = analyzed[i];
				const b = analyzed[j];
				if (a!.accountKey === b!.accountKey) continue;
				const similarity = similarityScore(a!, b!);
				if (similarity < MEDIUM_SIMILARITY) continue;
				const severity = similarity >= HIGH_SIMILARITY ? "high" : "medium";
				pairs.push({ a: a!, b: b!, similarity, severity });
				riskyPostIds.add(a!.id);
				riskyPostIds.add(b!.id);
			}
		}

		for (const post of analyzed) {
			if (
				(post.recycle_count ?? 0) > 0 ||
				post.recycled_from_id ||
				(post.signals?.watermark_applied ?? false)
			) {
				riskyPostIds.add(post.id);
			}
		}

		const accountRisk = new Map<
			string,
			{
				accountId: string;
				platform: "threads" | "instagram";
				username: string | null;
				riskyPosts: number;
				totalPosts: number;
				highestSimilarity: number;
			}
		>();
		for (const post of analyzed) {
			const existing = accountRisk.get(post.accountKey) || {
				accountId: post.accountId,
				platform: post.platform,
				username: post.username,
				riskyPosts: 0,
				totalPosts: 0,
				highestSimilarity: 0,
			};
			existing.totalPosts++;
			if (riskyPostIds.has(post.id)) existing.riskyPosts++;
			accountRisk.set(post.accountKey, existing);
		}
		for (const pair of pairs) {
			const a = accountRisk.get(pair.a.accountKey);
			const b = accountRisk.get(pair.b.accountKey);
			if (a)
				a.highestSimilarity = Math.max(a.highestSimilarity, pair.similarity);
			if (b)
				b.highestSimilarity = Math.max(b.highestSimilarity, pair.similarity);
		}

		const riskPostCount = riskyPostIds.size;
		const highRiskPairCount = pairs.filter(
			(pair) => pair.severity === "high",
		).length;
		const riskScore = Math.min(
			100,
			Math.round(
				(riskPostCount / META_THRESHOLD_POSTS) * 72 +
					(highRiskPairCount / Math.max(1, analyzed.length)) * 28,
			),
		);

		return apiSuccess(res, {
			periodDays,
			platform,
			totalPosts: analyzed.length,
			riskPostCount,
			riskScore,
			severity: riskScore >= 70 ? "crit" : riskScore >= 38 ? "warn" : "good",
			countdownToThreshold: Math.max(0, META_THRESHOLD_POSTS - riskPostCount),
			highRiskPairs: pairs
				.sort((a, b) => b.similarity - a.similarity)
				.slice(0, 8)
				.map((pair) => ({
					similarity: Number(pair.similarity.toFixed(2)),
					severity: pair.severity,
					posts: [toPostSummary(pair.a), toPostSummary(pair.b)],
				})),
			accountRisk: [...accountRisk.values()]
				.sort(
					(a, b) =>
						b.riskyPosts - a.riskyPosts ||
						b.highestSimilarity - a.highestSimilarity,
				)
				.slice(0, 8)
				.map((row) => ({
					...row,
					highestSimilarity: Number(row.highestSimilarity.toFixed(2)),
				})),
			notes: {
				method:
					"text similarity + recycle metadata + captured media fingerprints when present",
				metaThresholdPosts: META_THRESHOLD_POSTS,
				highSimilarity: HIGH_SIMILARITY,
				mediaFingerprintCoverage: analyzed.filter(
					(post) =>
						(post.signals?.perceptual_hashes?.length ?? 0) > 0 ||
						(post.signals?.media_url_hashes?.length ?? 0) > 0,
				).length,
			},
		});
	},
);

async function loadOriginalitySignals(
	posts: PostRow[],
	platform: string,
	accountByKey: Map<string, AccountRow>,
	scopedKeys: Set<string>,
): Promise<Map<string, SignalRow>> {
	const scopedPosts = posts.filter((post) => {
		const platformGuess = post.instagram_account_id ? "instagram" : "threads";
		if (platform !== "all" && platform !== platformGuess) return false;
		const id = post.instagram_account_id ?? post.account_id;
		return (
			!!id &&
			accountByKey.has(`${platformGuess}:${id}`) &&
			scopedKeys.has(`${platformGuess}:${id}`)
		);
	});
	if (scopedPosts.length === 0) return new Map();

	const postIds = scopedPosts.map((post) => post.id);
	const { data: existing } = await db()
		.from("post_originality_signals")
		.select(
			"post_id, text_hash, media_url_hashes, perceptual_hashes, watermark_applied",
		)
		.in("post_id", postIds);
	const map = new Map(
		((existing || []) as SignalRow[]).map((row) => [row.post_id, row]),
	);

	return map;
}

function emptyResponse(periodDays: number, platform: string) {
	return {
		periodDays,
		platform,
		totalPosts: 0,
		riskPostCount: 0,
		riskScore: 0,
		severity: "good",
		countdownToThreshold: META_THRESHOLD_POSTS,
		highRiskPairs: [],
		accountRisk: [],
		notes: {
			method:
				"text similarity + recycle metadata + captured media fingerprints",
			metaThresholdPosts: META_THRESHOLD_POSTS,
		},
	};
}

export function normalizeOriginalityContent(content: string): string {
	return content
		.toLowerCase()
		.replace(/https?:\/\/\S+/g, " ")
		.replace(/[@#]\w+/g, " ")
		.replace(/[^\p{L}\p{N}\s]/gu, " ")
		.replace(/\s+/g, " ")
		.trim();
}

export function originalityShingles(content: string): Set<string> {
	const tokens = content.split(/\s+/).filter((token) => token.length > 2);
	if (tokens.length <= 4) return new Set(tokens);
	const out = new Set<string>();
	for (let i = 0; i <= tokens.length - 3; i++) {
		out.add(tokens.slice(i, i + 3).join(" "));
	}
	return out;
}

export function originalitySetSimilarity(
	a: Set<string>,
	b: Set<string>,
): number {
	const smaller = a.size <= b.size ? a : b;
	const larger = smaller === a ? b : a;
	if (smaller.size === 0 || larger.size === 0) return 0;
	let intersection = 0;
	for (const value of smaller) {
		if (larger.has(value)) intersection++;
	}
	const union = a.size + b.size - intersection;
	return union > 0 ? intersection / union : 0;
}

function similarityScore(a: AnalyzedPost, b: AnalyzedPost): number {
	if (a.recycled_from_id && a.recycled_from_id === b.recycled_from_id) return 1;
	if (a.recycled_from_id && a.recycled_from_id === b.id) return 1;
	if (b.recycled_from_id && b.recycled_from_id === a.id) return 1;
	if (a.signals?.text_hash && a.signals.text_hash === b.signals?.text_hash) {
		return 1;
	}
	for (const ah of a.signals?.media_url_hashes ?? []) {
		if ((b.signals?.media_url_hashes ?? []).includes(ah)) return 1;
	}
	for (const ah of a.signals?.perceptual_hashes ?? []) {
		for (const bh of b.signals?.perceptual_hashes ?? []) {
			const sim = perceptualHashSimilarity(ah, bh);
			if (sim >= 0.9) return sim;
		}
	}
	if (a.normalized && a.normalized === b.normalized) return 1;

	return originalitySetSimilarity(a.shingles, b.shingles);
}

function toPostSummary(post: AnalyzedPost) {
	return {
		id: post.id,
		accountId: post.accountId,
		platform: post.platform,
		username: post.username,
		publishedAt: post.published_at,
		preview: (post.content || "").slice(0, 120),
		reach: post.ig_reach ?? post.views_count ?? 0,
	};
}
