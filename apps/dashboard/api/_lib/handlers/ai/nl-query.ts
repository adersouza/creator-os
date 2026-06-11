// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
// Meta Platform Terms: Never send raw Meta API numbers to third-party AI.
// This handler uses Gemini only to parse the user's NL prompt into a
// structured query spec. The spec then executes locally against Supabase;
// the LLM never sees the result rows.
/**
 * POST /api/ai?action=nl-query — natural-language → metric registry query
 *
 * Hex "show its work" pattern: LLM parses the prompt into a structured spec,
 * we execute the spec, and the UI renders both the spec (editable) and the
 * result rows. The user can tweak the spec to refine the query without
 * burning another LLM call.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getUserAIConfig } from "../../aiConfig.js";
import { checkAIRateLimit } from "../../aiRateLimit.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { escapeForPrompt, sanitizeAIOutput } from "../../promptUtils.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";
import { verifyWorkspaceAccess } from "../../workspaceAccess.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";

// Mirror of the frontend metric registry's queryable subset.
// Only metrics with a non-empty dbColumn are usable here.
export const METRIC_REGISTRY: Array<{
	key: string;
	dbColumn: string;
	platforms: Array<"threads" | "instagram">;
	aggregation: "sum" | "latest" | "snapshot";
	description: string;
}> = [
	{ key: "totalLikes", dbColumn: "total_likes", platforms: ["threads", "instagram"], aggregation: "latest", description: "Lifetime likes on published posts" },
	{ key: "totalReplies", dbColumn: "total_replies", platforms: ["threads", "instagram"], aggregation: "latest", description: "Lifetime replies on published posts" },
	{ key: "totalViews", dbColumn: "total_views", platforms: ["threads", "instagram"], aggregation: "latest", description: "Lifetime post/video views" },
	{ key: "totalReposts", dbColumn: "total_reposts", platforms: ["threads"], aggregation: "latest", description: "Lifetime reposts (Threads only)" },
	{ key: "totalQuotes", dbColumn: "total_quotes", platforms: ["threads"], aggregation: "latest", description: "Lifetime quote posts (Threads only)" },
	{ key: "totalIgReach", dbColumn: "total_reach", platforms: ["instagram"], aggregation: "snapshot", description: "IG account reach (rolling 28-day window)" },
	{ key: "totalIgSaved", dbColumn: "total_saves", platforms: ["instagram"], aggregation: "latest", description: "IG post saves" },
	{ key: "totalIgShares", dbColumn: "total_shares", platforms: ["instagram"], aggregation: "latest", description: "IG post shares" },
	{ key: "totalFollowers", dbColumn: "followers_count", platforms: ["threads", "instagram"], aggregation: "latest", description: "Current follower count" },
	{ key: "followerGrowth", dbColumn: "follower_growth", platforms: ["threads", "instagram"], aggregation: "sum", description: "Net follower change during the selected period" },
	{ key: "totalClicks", dbColumn: "total_clicks", platforms: ["threads"], aggregation: "latest", description: "Profile clicks from Threads" },
	{ key: "igNewFollows", dbColumn: "ig_new_follows", platforms: ["instagram"], aggregation: "latest", description: "New IG follows (from follows_and_unfollows)" },
	{ key: "igUnfollows", dbColumn: "ig_unfollows", platforms: ["instagram"], aggregation: "latest", description: "IG unfollows" },
	{ key: "igAccountsEngaged", dbColumn: "ig_accounts_engaged", platforms: ["instagram"], aggregation: "snapshot", description: "IG unique accounts engaged" },
	{ key: "igProfileViews", dbColumn: "ig_profile_views", platforms: ["instagram"], aggregation: "snapshot", description: "IG profile views" },
	{ key: "igWebsiteClicks", dbColumn: "ig_website_clicks", platforms: ["instagram"], aggregation: "snapshot", description: "IG website/link-in-bio clicks" },
	{ key: "igNonFollowerReachPct", dbColumn: "ig_non_follower_reach_pct", platforms: ["instagram"], aggregation: "snapshot", description: "Share of IG reach from non-followers" },
];

const METRIC_KEYS = METRIC_REGISTRY.map((m) => m.key);

type Platform = "threads" | "instagram" | "all";
type GroupBy = "account" | "day" | "none";
type AnalyticsRecord = Record<string, number | string | null>;

export interface QuerySpec {
	metric: string;
	timeframeDays: number;
	platform: Platform;
	groupBy: GroupBy;
	limit: number;
	orderBy: "asc" | "desc";
}

export interface QueryRow {
	label: string;
	value: number;
}

interface QueryScope {
	accountId?: string | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
	workspaceId?: string | null | undefined;
	platform?: Platform | undefined;
}

interface LLMSpecResponse {
	metric?: string | undefined;
	timeframeDays?: number | undefined;
	platform?: string | undefined;
	groupBy?: string | undefined;
	limit?: number | undefined;
	orderBy?: string | undefined;
	interpretation?: string | undefined;
}

export function buildSystemPrompt(prompt: string): string {
	const metricList = METRIC_REGISTRY.map(
		(m) => `- ${m.key} (${m.platforms.join("/")}) — ${m.description}`,
	).join("\n");

	return `You are a query planner that converts the user's natural-language prompt into a JSON spec against Juno33's metric registry.

Return ONLY a valid JSON object matching this shape — no prose before or after, no Markdown:
{
  "metric": "<metricKey>",
  "timeframeDays": <7|14|30|60|90>,
  "platform": "threads"|"instagram"|"all",
  "groupBy": "account"|"day"|"none",
  "limit": <1-50>,
  "orderBy": "asc"|"desc",
  "interpretation": "<one sentence plain-English summary of what the query does>"
}

Available metrics:
${metricList}

Rules:
- metric MUST be one of the keys above. If the user asks for a metric not in the list (e.g. "comments"), pick the closest match (e.g. "totalReplies") and say so in interpretation.
- If the user asks how many followers were gained/lost, follower growth, or follower change over a time period, use followerGrowth. Use totalFollowers only for current follower count.
- platform "all" means both threads and instagram.
- If the user mentions a specific platform, set it; otherwise pick the one the metric is available on (or "all" if both).
- If the user asks for "per account", "by account", or "breakdown by account", groupBy = "account".
- If the user asks for "over time", "daily", "trend", groupBy = "day".
- If the user asks for a single aggregate number, groupBy = "none".
- Default timeframeDays: 30 when unclear.
- Default limit: 10 for groupBy "account" or "day", 1 for "none".
- Default orderBy: "desc" (biggest first) unless user asks for smallest.

User prompt: "${escapeForPrompt(prompt).slice(0, 600)}"

Respond with ONLY the JSON object. No Markdown fencing. No commentary.`;
}

export function coerceSpec(raw: LLMSpecResponse): QuerySpec {
	const metric =
		raw.metric && METRIC_KEYS.includes(raw.metric)
			? raw.metric
			: "totalViews";
	const timeframeDays = (() => {
		const n = Number(raw.timeframeDays);
		if (!Number.isFinite(n)) return 30;
		if (n < 7) return 7;
		if (n > 90) return 90;
		return Math.floor(n);
	})();
	const platform: Platform =
		raw.platform === "threads" || raw.platform === "instagram"
			? raw.platform
			: "all";
	const groupBy: GroupBy =
		raw.groupBy === "account" || raw.groupBy === "day" ? raw.groupBy : "none";
	const limit = (() => {
		const n = Number(raw.limit);
		if (!Number.isFinite(n)) return groupBy === "none" ? 1 : 10;
		return Math.max(1, Math.min(50, Math.floor(n)));
	})();
	const orderBy: "asc" | "desc" = raw.orderBy === "asc" ? "asc" : "desc";

	return { metric, timeframeDays, platform, groupBy, limit, orderBy };
}

export function aggregateRowsForSpec(
	spec: QuerySpec,
	metricDef: (typeof METRIC_REGISTRY)[number],
	rows: AnalyticsRecord[],
	accountMap: Map<string, string>,
): { rows: QueryRow[]; aggregate: number } {
	const valueFor = (items: AnalyticsRecord[]): number => {
		const sorted = [...items].sort((a, b) =>
			String(a.date || "").localeCompare(String(b.date || "")),
		);
		const values = sorted
			.map((r) => Number(r[metricDef.dbColumn]) || 0)
			.filter((v) => Number.isFinite(v));
		if (values.length === 0) return 0;
		if (metricDef.aggregation === "sum") {
			return values.reduce((a, b) => a + b, 0);
		}
		return values[values.length - 1]!;
	};

	if (spec.groupBy === "account") {
		const byAccount = new Map<string, AnalyticsRecord[]>();
		for (const r of rows) {
			const aid = String(r.account_id);
			if (!byAccount.has(aid)) byAccount.set(aid, []);
			byAccount.get(aid)?.push(r);
		}
		const resultRows: QueryRow[] = Array.from(byAccount.entries()).map(
			([aid, items]) => ({
				label: accountMap.get(aid) || aid,
				value: valueFor(items),
			}),
		);
		resultRows.sort((a, b) =>
			spec.orderBy === "asc" ? a.value - b.value : b.value - a.value,
		);
		const aggregate = resultRows.reduce((s, r) => s + r.value, 0);
		return {
			rows: resultRows.slice(0, spec.limit),
			aggregate,
		};
	}

	if (spec.groupBy === "day") {
		if (metricDef.aggregation === "sum") {
			const byDay = new Map<string, number>();
			for (const r of rows) {
				const day = String(r.date || "");
				if (!day) continue;
				const val = Number(r[metricDef.dbColumn]) || 0;
				byDay.set(day, (byDay.get(day) || 0) + val);
			}
			const resultRows: QueryRow[] = Array.from(byDay.entries())
				.sort(([a], [b]) => a.localeCompare(b))
				.map(([day, value]) => ({ label: day, value }));
			if (spec.orderBy === "desc") resultRows.reverse();
			const aggregate = resultRows.reduce((s, r) => s + r.value, 0);
			return {
				rows: resultRows.slice(0, spec.limit),
				aggregate,
			};
		}

		const byAccountByDay = new Map<string, Map<string, number>>();
		for (const r of [...rows].sort((a, b) =>
			String(a.date || "").localeCompare(String(b.date || "")),
		)) {
			const day = String(r.date || "");
			const aid = String(r.account_id || "");
			if (!day || !aid) continue;
			const val = Number(r[metricDef.dbColumn]) || 0;
			if (!byAccountByDay.has(aid)) byAccountByDay.set(aid, new Map());
			byAccountByDay.get(aid)?.set(day, val);
		}
		const allDays = new Set<string>();
		for (const dayMap of byAccountByDay.values()) {
			for (const day of dayMap.keys()) allDays.add(day);
		}
		const byDay = new Map<string, number>();
		for (const day of allDays) {
			let total = 0;
			for (const dayMap of byAccountByDay.values()) {
				total += dayMap.get(day) ?? 0;
			}
			byDay.set(day, total);
		}
		const resultRows: QueryRow[] = Array.from(byDay.entries())
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([day, value]) => ({ label: day, value }));
		if (spec.orderBy === "desc") resultRows.reverse();
		const aggregate = resultRows.reduce((s, r) => s + r.value, 0);
		return {
			rows: resultRows.slice(0, spec.limit),
			aggregate,
		};
	}

	if (metricDef.aggregation === "sum") {
		const aggregate = valueFor(rows);
		return {
			rows: [{ label: "Total", value: aggregate }],
			aggregate,
		};
	}

	const byAccount = new Map<string, AnalyticsRecord[]>();
	for (const r of rows) {
		const aid = String(r.account_id || "");
		if (!aid) continue;
		if (!byAccount.has(aid)) byAccount.set(aid, []);
		byAccount.get(aid)?.push(r);
	}
	const aggregate = Array.from(byAccount.values()).reduce(
		(sum, items) => sum + valueFor(items),
		0,
	);
	return {
		rows: [{ label: "Total", value: aggregate }],
		aggregate,
	};
}

async function executeSpec(
	spec: QuerySpec,
	userId: string,
	scope: QueryScope = {},
): Promise<{
	rows: QueryRow[];
	aggregate: number;
	matchedAccounts: number;
	dataThrough: string | null;
	stale: boolean;
}> {
	const metricDef = METRIC_REGISTRY.find((m) => m.key === spec.metric);
	if (!metricDef) throw new Error(`Unknown metric: ${spec.metric}`);
	const supabase = getSupabase();

	if (typeof scope.workspaceId === "string" && scope.workspaceId.length > 0) {
		const allowed = await verifyWorkspaceAccess(
			supabase,
			userId,
			scope.workspaceId,
		);
		if (!allowed) throw new Error("workspace_not_found");
	}

	const cutoff = new Date();
	cutoff.setDate(cutoff.getDate() - spec.timeframeDays);
	const cutoffDate = cutoff.toISOString().split("T")[0]!;

	// Resolve accounts owned by user, filtered by platform
	const tables: Array<{ name: string; platform: "threads" | "instagram" }> =
		(scope.platform === "threads" || scope.platform === "instagram"
			? scope.platform
			: spec.platform) === "instagram"
			? [{ name: "instagram_accounts", platform: "instagram" }]
			: (scope.platform === "threads" || scope.platform === "instagram"
					? scope.platform
					: spec.platform) === "threads"
				? [{ name: "accounts", platform: "threads" }]
				: [
						{ name: "accounts", platform: "threads" },
						{ name: "instagram_accounts", platform: "instagram" },
					];

	const requestedIds = new Set(
		[
			...(typeof scope.accountId === "string" ? [scope.accountId] : []),
			...(Array.isArray(scope.accountIds) ? scope.accountIds : []),
		]
			.filter((id): id is string => typeof id === "string" && id.length > 0)
			.slice(0, 300),
	);
	const accountMap = new Map<string, string>(); // id → username
	for (const t of tables) {
		// Only pull accounts that match this metric's platform eligibility
		if (!metricDef.platforms.includes(t.platform)) continue;
		let accountQuery = getSupabaseAny()
			.from(t.name)
			.select("id, username, group_id")
			.eq("user_id", userId);
		if (typeof scope.workspaceId === "string" && scope.workspaceId.length > 0) {
			accountQuery = accountQuery.eq("workspace_id", scope.workspaceId);
		}
		const { data } = await accountQuery;
		for (const row of (data || []) as Array<{ id: string; username: string | null; group_id?: string | null }>) {
			if (requestedIds.size > 0 && !requestedIds.has(row.id)) continue;
			if (typeof scope.groupId === "string" && row.group_id !== scope.groupId) continue;
			accountMap.set(row.id, row.username || row.id);
		}
	}

	if (accountMap.size === 0) {
		return { rows: [], aggregate: 0, matchedAccounts: 0, dataThrough: null, stale: false };
	}

	if (
		(typeof scope.accountId === "string" || Array.isArray(scope.accountIds)) &&
		requestedIds.size === 0
	) {
		return { rows: [], aggregate: 0, matchedAccounts: 0, dataThrough: null, stale: false };
	}

	const accountIds = Array.from(accountMap.keys());

	// Query account_analytics for the period + chosen metric column
	// biome-ignore lint/suspicious/noExplicitAny: dynamic columns
	const { data: analyticsRows } = (await (supabase as any)
		.from("account_analytics")
		.select(`account_id, date, ${metricDef.dbColumn}`)
		.in("account_id", accountIds)
		.gte("date", cutoffDate)
		.order("date", { ascending: true })) as {
		data: Array<Record<string, number | string | null>> | null;
	};

	const rows = analyticsRows || [];
	const dataThrough = rows.reduce<string | null>((latest, row) => {
		const date = typeof row.date === "string" ? row.date : null;
		if (!date) return latest;
		return latest && latest > date ? latest : date;
	}, null);
	const stale =
		!!dataThrough &&
		Date.now() - new Date(`${dataThrough}T00:00:00.000Z`).getTime() >
			3 * 24 * 60 * 60 * 1000;
	const result = aggregateRowsForSpec(spec, metricDef, rows, accountMap);
	return {
		rows: result.rows,
		aggregate: result.aggregate,
		matchedAccounts: accountMap.size,
		dataThrough,
		stale,
	};
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const {
			prompt,
			specOverride,
			accountId,
			accountIds,
			groupId,
			workspaceId,
			platform,
		} = req.body || {};

		// Tier gate — Pro+ for AI query planning
		if (!(await requireMinTier(user.id, "pro", res))) return;

		// Rate limit (shared with copilot pool)
		const rl = await checkAIRateLimit(user.id, "copilot");
		res.setHeader("X-RateLimit-Limit", String(rl.limit));
		res.setHeader("X-RateLimit-Remaining", String(rl.remaining));
		if (!rl.allowed) {
			return apiError(
				res,
				429,
				"Rate limit exceeded. Please upgrade for higher limits.",
				{ code: "RATE_LIMITED" },
			);
		}

		try {
			let spec: QuerySpec;
			let interpretation: string;
			let usedLLM = false;

			if (specOverride && typeof specOverride === "object") {
				// User edited the spec in the builder view — skip the LLM call,
				// just validate + re-execute.
				spec = coerceSpec(specOverride as LLMSpecResponse);
				interpretation =
					typeof (specOverride as LLMSpecResponse).interpretation === "string"
						? ((specOverride as LLMSpecResponse).interpretation as string)
						: "Manual query spec.";
			} else {
				if (!prompt || typeof prompt !== "string") {
					return apiError(res, 400, "prompt is required");
				}

				const aiConfig = await getUserAIConfig(user.id);
				if (!aiConfig) {
					return apiError(
						res,
						503,
						"AI features temporarily unavailable. Add your own API key in Settings for immediate access.",
						{ code: "NO_API_KEY" },
					);
				}

				const systemPrompt = buildSystemPrompt(prompt);
				const model = aiConfig.model || "gemini-2.5-flash";
				const response = await generateWithProvider(systemPrompt, {
					provider: aiConfig.provider,
					apiKey: aiConfig.apiKey,
					baseUrl: aiConfig.baseUrl,
					model,
					keySource: aiConfig.source,
					ideaCount: 1,
					useStructuredOutput: true,
					structuredOutputSchema: {
						type: "OBJECT",
						properties: {
							metric: { type: "STRING" },
							timeframeDays: { type: "INTEGER" },
							platform: { type: "STRING" },
							groupBy: { type: "STRING" },
							limit: { type: "INTEGER" },
							orderBy: { type: "STRING" },
							interpretation: { type: "STRING" },
						},
						required: ["metric", "timeframeDays", "platform", "groupBy", "limit", "orderBy", "interpretation"],
					},
					actionLog: {
						userId: user.id,
						surface: "analytics",
						actionType: "nl_query_plan",
						inputText: prompt.slice(0, 2000),
						metadata: {
							provider: aiConfig.provider,
							scope: {
								accountId: typeof accountId === "string" ? accountId : null,
								groupId: typeof groupId === "string" ? groupId : null,
								workspaceId:
									typeof workspaceId === "string" ? workspaceId : null,
								accountIds: Array.isArray(accountIds) ? accountIds.length : 0,
							},
						},
					},
				});
				usedLLM = true;
				if (!response) return apiError(res, 502, "Could not plan query");
				const rawText = sanitizeAIOutput(response || "{}");

				let parsed: LLMSpecResponse;
				try {
					parsed = JSON.parse(rawText) as LLMSpecResponse;
				} catch {
					return apiError(res, 502, "Could not parse query spec from AI", {
						details: rawText.slice(0, 300),
					});
				}

				spec = coerceSpec(parsed);
				interpretation =
					typeof parsed.interpretation === "string"
						? parsed.interpretation
						: "Parsed from your prompt.";
			}

			const { rows, aggregate, matchedAccounts, dataThrough, stale } =
				await executeSpec(
				spec,
				user.id,
				{
					accountId: typeof accountId === "string" ? accountId : undefined,
					accountIds: Array.isArray(accountIds)
						? accountIds.filter(
								(id): id is string => typeof id === "string" && id.length > 0,
							)
						: undefined,
					groupId: typeof groupId === "string" ? groupId : null,
					workspaceId:
						typeof workspaceId === "string" ? workspaceId : null,
					platform:
						platform === "threads" || platform === "instagram" || platform === "all"
							? platform
							: undefined,
				},
			);

			return apiSuccess(res, {
				spec,
				interpretation,
				rows,
				aggregate,
				matchedAccounts,
				dataThrough,
				stale,
				usedLLM,
				scope: {
					accountId: typeof accountId === "string" ? accountId : null,
					groupId: typeof groupId === "string" ? groupId : null,
					workspaceId:
						typeof workspaceId === "string" ? workspaceId : null,
					accountCount: matchedAccounts,
				},
				availableMetrics: METRIC_REGISTRY.map((m) => ({
					key: m.key,
					platforms: m.platforms,
					description: m.description,
				})),
			});
		} catch (err: unknown) {
			logger.error("[ai/nl-query] Failed", {
				userId: user.id,
				error: err instanceof Error ? err.message : String(err),
			});
			return apiError(res, 502, "Query execution failed");
		}
	},
);
