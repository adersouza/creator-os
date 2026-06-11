// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Niche Audience Twin Map
 *
 * Uses stored audience_demographics rows to find accounts whose audience shape
 * is similar by age/gender/city/country vectors. This is a current-data v1:
 * no cross-user cohort exposure, no individual peer leakage.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z, zEnum } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

const QuerySchema = z.object({
	platform: zEnum(["all", "instagram", "threads"]).optional().default("all"),
});

// biome-ignore lint/suspicious/noExplicitAny: generated DB types lag analytics tables
const db = (): any => getSupabase();

interface AccountRow {
	id: string;
	username: string | null;
	platform: "threads" | "instagram";
}

interface DemoRow {
	account_id: string | null;
	instagram_account_id: string | null;
	platform: "threads" | "instagram";
	breakdown_type: string;
	breakdown_value: string;
	count: number | string | null;
	percentage: number | string | null;
	fetched_at: string;
}

interface VectorAccount extends AccountRow {
	key: string;
	vector: Map<string, number>;
	sampleSize: number;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { platform } = parsed;

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
			...((threadsRes.data || []) as Array<{ id: string; username: string | null }>).map(
				(a) => ({ ...a, platform: "threads" as const }),
			),
			...((igRes.data || []) as Array<{ id: string; username: string | null }>).map(
				(a) => ({ ...a, platform: "instagram" as const }),
			),
		];
		if (accounts.length < 2) {
			return apiSuccess(res, emptyTwinResponse(platform));
		}

		const threadsIds = accounts
			.filter((account) => account.platform === "threads")
			.map((account) => account.id);
		const igIds = accounts
			.filter((account) => account.platform === "instagram")
			.map((account) => account.id);

		const demoRows: DemoRow[] = [];
		if (threadsIds.length > 0) {
			const { data, error } = await db()
				.from("audience_demographics")
				.select(
					"account_id, instagram_account_id, platform, breakdown_type, breakdown_value, count, percentage, fetched_at",
				)
				.eq("platform", "threads")
				.in("account_id", threadsIds)
				.order("fetched_at", { ascending: false })
				.limit(1200);
			if (error) return apiError(res, 500, "Failed to fetch demographics");
			demoRows.push(...((data || []) as DemoRow[]));
		}
		if (igIds.length > 0) {
			const { data, error } = await db()
				.from("audience_demographics")
				.select(
					"account_id, instagram_account_id, platform, breakdown_type, breakdown_value, count, percentage, fetched_at",
				)
				.eq("platform", "instagram")
				.in("instagram_account_id", igIds)
				.order("fetched_at", { ascending: false })
				.limit(1200);
			if (error) return apiError(res, 500, "Failed to fetch demographics");
			demoRows.push(...((data || []) as DemoRow[]));
		}

		const latestByAccount = new Map<string, string>();
		for (const row of demoRows) {
			const key = rowKey(row);
			if (!key) continue;
			const day = row.fetched_at.slice(0, 10);
			if (!latestByAccount.has(key) || day > (latestByAccount.get(key) || "")) {
				latestByAccount.set(key, day);
			}
		}

		const accountByKey = new Map(
			accounts.map((account) => [`${account.platform}:${account.id}`, account]),
		);
		const vectorByKey = new Map<string, VectorAccount>();
		for (const row of demoRows) {
			const key = rowKey(row);
			if (!key || row.fetched_at.slice(0, 10) !== latestByAccount.get(key)) {
				continue;
			}
			const account = accountByKey.get(key);
			if (!account) continue;
			const existing =
				vectorByKey.get(key) ||
				({
					...account,
					key,
					vector: new Map<string, number>(),
					sampleSize: 0,
				} satisfies VectorAccount);
			const feature = `${row.breakdown_type}:${row.breakdown_value.toLowerCase()}`;
			const value = Number(row.percentage ?? row.count ?? 0);
			if (value > 0) {
				existing.vector.set(feature, value);
				existing.sampleSize += Number(row.count ?? 0);
			}
			vectorByKey.set(key, existing);
		}

		const vectorAccounts = [...vectorByKey.values()].filter(
			(account) => account.vector.size >= 3,
		);
		const source =
			vectorAccounts.length >= 2
				? {
						accounts: vectorAccounts,
						method: "cosine similarity over latest audience demographic vectors",
						minFeaturesPerAccount: 3,
						source: "demographics",
					}
				: await buildContentTwinVectors(db(), user.id, accounts);

		const pairs = buildPairs(source.accounts);

		pairs.sort((a, b) => b.similarity - a.similarity);

		return apiSuccess(res, {
			platform,
			accountsWithDemographics: source.accounts.length,
			totalAccounts: accounts.length,
			coveragePct:
				accounts.length > 0
					? Math.round((source.accounts.length / accounts.length) * 100)
					: 0,
			pairs: pairs.slice(0, 12).map((pair) => ({
				similarity: Number(pair.similarity.toFixed(2)),
				accounts: [toAccountSummary(pair.a), toAccountSummary(pair.b)],
				sharedSignals: pair.sharedSignals,
			})),
			clusters: buildClusters(source.accounts, pairs),
			notes: {
				method: source.method,
				minFeaturesPerAccount: source.minFeaturesPerAccount,
				source: source.source,
			},
		});
	},
);

function buildPairs(accounts: VectorAccount[]) {
	const pairs: Array<{
		a: VectorAccount;
		b: VectorAccount;
		similarity: number;
		sharedSignals: string[];
	}> = [];

	for (let i = 0; i < accounts.length; i++) {
		for (let j = i + 1; j < accounts.length; j++) {
			const a = accounts[i];
			const b = accounts[j];
			const similarity = audienceVectorCosine(a!.vector, b!.vector);
			pairs.push({
				a: a!,
					b: b!,
				similarity,
				sharedSignals: audienceSharedSignals(a!.vector, b!.vector),
			});
		}
	}
	return pairs;
}

async function buildContentTwinVectors(
	db: ReturnType<typeof getSupabase>,
	userId: string,
	accounts: AccountRow[],
) {
	const accountByKey = new Map(
		accounts.map((account) => [`${account.platform}:${account.id}`, account]),
	);
	const cutoff = new Date(Date.now() - 90 * 86_400_000).toISOString();
	const { data } = await db
		.from("posts")
		.select("account_id, instagram_account_id, content, topic_tag, ig_reach, views_count")
		.eq("user_id", userId)
		.eq("status", "published")
		.gte("published_at", cutoff)
		.limit(900);

	const byKey = new Map<string, VectorAccount>();
	for (const post of (data ?? []) as Array<{
		account_id: string | null;
		instagram_account_id: string | null;
		content: string | null;
		topic_tag: string | null;
		ig_reach: number | null;
		views_count: number | null;
	}>) {
		const platform = post.instagram_account_id ? "instagram" : "threads";
		const id = post.instagram_account_id ?? post.account_id;
		if (!id) continue;
		const key = `${platform}:${id}`;
		const account = accountByKey.get(key);
		if (!account) continue;
		const existing =
			byKey.get(key) ||
			({
				...account,
				key,
				vector: new Map<string, number>(),
				sampleSize: 0,
			} satisfies VectorAccount);
		const weight = Math.max(1, Number(post.ig_reach ?? post.views_count ?? 1));
		for (const feature of contentFeatures(post)) {
			existing.vector.set(feature, (existing.vector.get(feature) ?? 0) + weight);
		}
		existing.sampleSize += 1;
		byKey.set(key, existing);
	}

	return {
		accounts: [...byKey.values()].filter((account) => account.vector.size >= 2),
		method: "cosine similarity over 90d topic/content vectors",
		minFeaturesPerAccount: 2,
		source: "content_proxy",
	};
}

function contentFeatures(post: { content: string | null; topic_tag: string | null }) {
	const features = new Set<string>();
	if (post.topic_tag) features.add(`topic:${post.topic_tag.toLowerCase()}`);
	const tokens = (post.content || "")
		.toLowerCase()
		.replace(/https?:\/\/\S+/g, " ")
		.replace(/[@#]\w+/g, " ")
		.replace(/[^\p{L}\p{N}\s]/gu, " ")
		.split(/\s+/)
		.filter((token) => token.length >= 5)
		.slice(0, 20);
	for (const token of tokens) features.add(`term:${token}`);
	return features;
}

function emptyTwinResponse(platform: string) {
	return {
		platform,
		accountsWithDemographics: 0,
		totalAccounts: 0,
		coveragePct: 0,
		pairs: [],
		clusters: [],
		notes: {
			method: "cosine similarity over latest audience demographic vectors",
			minFeaturesPerAccount: 3,
		},
	};
}

function rowKey(row: DemoRow): string | null {
	const id =
		row.platform === "instagram" ? row.instagram_account_id : row.account_id;
	return id ? `${row.platform}:${id}` : null;
}

export function audienceVectorCosine(a: Map<string, number>, b: Map<string, number>): number {
	let dot = 0;
	let aNorm = 0;
	let bNorm = 0;
	for (const value of a.values()) aNorm += value * value;
	for (const value of b.values()) bNorm += value * value;
	for (const [feature, value] of a) {
		dot += value * (b.get(feature) ?? 0);
	}
	if (aNorm === 0 || bNorm === 0) return 0;
	return dot / (Math.sqrt(aNorm) * Math.sqrt(bNorm));
}

export function audienceSharedSignals(a: Map<string, number>, b: Map<string, number>): string[] {
	return [...a.entries()]
		.filter(([feature]) => b.has(feature))
		.map(([feature, value]) => ({
			feature,
			strength: Math.min(value, b.get(feature) ?? 0),
		}))
		.sort((x, y) => y.strength - x.strength)
		.slice(0, 3)
		.map(({ feature }) => feature.replace(":", " · "));
}

function toAccountSummary(account: VectorAccount) {
	return {
		id: account.id,
		username: account.username,
		platform: account.platform,
		sampleSize: Math.round(account.sampleSize),
	};
}

function buildClusters(
	accounts: VectorAccount[],
	pairs: Array<{
		a: VectorAccount;
		b: VectorAccount;
		similarity: number;
		sharedSignals: string[];
	}>,
) {
	const used = new Set<string>();
	const clusters: Array<{
		label: string;
		accounts: ReturnType<typeof toAccountSummary>[];
		avgSimilarity: number;
		signals: string[];
	}> = [];

	for (const pair of pairs.filter((p) => p.similarity >= 0.72)) {
		if (used.has(pair.a.key) || used.has(pair.b.key)) continue;
		const members = [pair.a, pair.b];
		used.add(pair.a.key);
		used.add(pair.b.key);
		for (const account of accounts) {
			if (used.has(account.key)) continue;
			const avg =
				members.reduce(
					(sum, member) => sum + audienceVectorCosine(member.vector, account.vector),
					0,
				) / members.length;
			if (avg >= 0.72 && members.length < 5) {
				members.push(account);
				used.add(account.key);
			}
		}
		clusters.push({
			label: `Twin cluster ${clusters.length + 1}`,
			accounts: members.map(toAccountSummary),
			avgSimilarity: Number(pair.similarity.toFixed(2)),
			signals: pair.sharedSignals,
		});
	}

	return clusters.slice(0, 4);
}
