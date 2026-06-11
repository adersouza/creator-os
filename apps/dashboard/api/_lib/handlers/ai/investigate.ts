// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
// Meta Platform Terms: Do not send exact API metrics to third-party AI services
/**
 * POST /api/ai?action=investigate — multi-step investigation agent
 *
 * Takes a metric + account + time window, pulls deterministic data from
 * existing endpoints (account_analytics, reach anomalies, content type mix,
 * cross-account insights), and synthesizes a structured transcript via
 * Gemini.
 *
 * This is a one-shot investigation — not streaming — because the LLM call
 * runs after data collection is complete. Data sources that fail are marked
 * as "unavailable" in the transcript rather than blocking the run.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getUserAIConfig } from "../../aiConfig.js";
import { trackAICost } from "../../aiCostTracker.js";
import { checkAIRateLimit } from "../../aiRateLimit.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import {
	sendDone,
	sendError,
	streamGemini,
	writeSseHeaders,
} from "../../geminiStream.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { escapeForPrompt, sanitizeAIOutput } from "../../promptUtils.js";
import { describeAnalyticsTrend, describeValue } from "../../sanitizeForAI.js";
import { getSupabase } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";

type Metric = "reach" | "followers" | "engagement" | "views" | "conversion";

type ResolvedAccount = {
	id: string;
	username: string | null;
	platform: "threads" | "instagram";
};

const METRIC_COLUMNS: Record<Metric, string> = {
	reach: "total_reach",
	followers: "followers_count",
	engagement: "engagement_rate",
	views: "total_views",
	conversion: "total_views", // derives conversion from views + follower_growth
};

const METRIC_LABELS: Record<Metric, string> = {
	reach: "reach",
	followers: "follower growth",
	engagement: "engagement rate",
	views: "post views",
	conversion: "views-to-follower conversion",
};

interface InvestigationSection {
	title: string;
	body: string;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const {
			accountId,
			metric: metricRaw,
			periodDays: periodRaw,
			focusDate,
			hypothesis,
		} = req.body || {};

		if (!accountId || typeof accountId !== "string") {
			return apiError(res, 400, "accountId is required");
		}

		const metric: Metric =
			metricRaw && Object.hasOwn(METRIC_COLUMNS, metricRaw)
				? (metricRaw as Metric)
				: "reach";

		const periodDays = Math.min(Math.max(Number(periodRaw) || 30, 7), 90);

		// Tier gate — investigation is a Pro+ feature
		if (!(await requireMinTier(user.id, "pro", res))) return;

		// Rate limit — reuse copilot limit (investigation is similar cost)
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

		const aiConfig = await getUserAIConfig(user.id);
		if (!aiConfig) {
			return apiError(
				res,
				503,
				"AI features temporarily unavailable. Add your own API key in Settings for immediate access.",
				{ code: "NO_API_KEY" },
			);
		}

		const supabase = getSupabase();
		const dataUsed: string[] = [];
		const contextParts: string[] = [];

		try {
			// 1. Resolve account + verify ownership. The investigation UI can be
			// opened from fleet-level surfaces before a scope is selected, so the
			// chosen id may point at either platform's account table.
			const { data: threadAccount } = (await supabase
				.from("accounts")
				.select("id, username, platform, followers_count")
				.eq("id", accountId)
				.eq("user_id", user.id)
				.maybeSingle()) as {
				data: {
					id: string;
					username: string | null;
					platform: string | null;
					followers_count: number | null;
				} | null;
			};

			let account: ResolvedAccount | null = threadAccount
				? {
						id: threadAccount.id,
						username: threadAccount.username,
						platform: "threads",
					}
				: null;

			if (!account) {
				const { data: instagramAccount } = (await supabase
					.from("instagram_accounts")
					.select("id, username, follower_count")
					.eq("id", accountId)
					.eq("user_id", user.id)
					.maybeSingle()) as {
					data: {
						id: string;
						username: string | null;
						follower_count: number | null;
					} | null;
				};

				if (instagramAccount) {
					account = {
						id: instagramAccount.id,
						username: instagramAccount.username,
						platform: "instagram",
					};
				}
			}

			if (!account) {
				return apiError(res, 404, "Account not found");
			}

			// 2. Pull analytics time series for the period
			const cutoff = new Date();
			cutoff.setDate(cutoff.getDate() - periodDays);
			const cutoffDate = cutoff.toISOString().split("T")[0]!;

			const { data: analytics } = await supabase
				.from("account_analytics")
				.select(
					"date, followers_count, total_views, total_reach, engagement_rate, follower_growth, total_likes, total_replies",
				)
				.eq("account_id", account.id)
				.gte("date", cutoffDate)
				.order("date", { ascending: true });

			const analyticsRows = analytics || [];

			if (analyticsRows.length > 0) {
				dataUsed.push("account_analytics");
				const column = METRIC_COLUMNS[metric];
				const trend = describeAnalyticsTrend(
					analyticsRows as Array<{ [k: string]: unknown; date: string }>,
					column,
				);
				contextParts.push(
					`Primary metric (${METRIC_LABELS[metric]}) over the last ${periodDays} days: ${trend}`,
				);

				// For conversion metric, also describe follower_growth trend
				if (metric === "conversion") {
					const growthTrend = describeAnalyticsTrend(
						analyticsRows as Array<{ [k: string]: unknown; date: string }>,
						"follower_growth",
					);
					contextParts.push(
						`Daily follower growth over the same period: ${growthTrend}`,
					);
				}
			}

			// 3. Content-type mix (if the posts table has ig_media_type / media_type)
			let postsQuery = supabase
				.from("posts")
				.select(
					"media_type, ig_media_type, likes_count, replies_count, views_count, published_at",
				)
				.eq("status", "published")
				.gte("published_at", cutoff.toISOString())
				.order("published_at", { ascending: false })
				.limit(50);

			postsQuery =
				account.platform === "instagram"
					? postsQuery.eq("instagram_account_id", account.id)
					: postsQuery.eq("account_id", account.id);

			const { data: posts } = await postsQuery;

			if (posts && posts.length > 0) {
				dataUsed.push("posts");
				const typeCounts: Record<string, number> = {};
				let totalLikes = 0;
				for (const p of posts as Array<{
					media_type?: string | null | undefined;
					ig_media_type?: string | null | undefined;
					likes_count?: number | null | undefined;
				}>) {
					const type = p.ig_media_type || p.media_type || "text";
					typeCounts[type] = (typeCounts[type] || 0) + 1;
					totalLikes += p.likes_count || 0;
				}
				const mix = Object.entries(typeCounts)
					.map(([t, c]) => `${t}: ${c}`)
					.join(", ");
				contextParts.push(
					`Format mix in period (${posts.length} posts): ${mix}. Total engagement signals: ${describeValue(totalLikes)}.`,
				);
			}

			// 4. Focus date context (if user clicked a specific point)
			if (focusDate && typeof focusDate === "string") {
				const focusRow = analyticsRows.find(
					(r: { date?: string | undefined }) => r.date === focusDate,
				);
				if (focusRow) {
					dataUsed.push("focus_date");
					const rawValue = (
						focusRow as unknown as Record<string, number | null>
					)[METRIC_COLUMNS[metric]];
					const focusDescription = describeValue(Number(rawValue) || 0);
					contextParts.push(
						`User clicked on ${focusDate} specifically — ${METRIC_LABELS[metric]} that day was ${focusDescription}.`,
					);
				}
			}

			// 5. Hypothesis (user-supplied — optional)
			if (hypothesis && typeof hypothesis === "string") {
				contextParts.push(
					`User hypothesis to evaluate: "${escapeForPrompt(hypothesis).slice(0, 500)}"`,
				);
			}

			// 6. Build structured prompt
			const systemPrompt = `You are Juno33's data investigation agent. You have been asked to investigate the ${METRIC_LABELS[metric]} metric for ${account.platform} account @${account.username || "(unknown)"} over the last ${periodDays} days.

Respond with EXACTLY this structure (use these section headers verbatim, as plain text — no Markdown, no bullet symbols, no bold):

SUMMARY
One sentence stating the headline pattern.

OBSERVATIONS
Three to five observations from the data below. One sentence each. Describe directional trends only — never quote raw Meta API numbers.

LIKELY DRIVERS
Two to four hypotheses that could explain the pattern, ranked by how much the data supports them. Each is one sentence.

WHAT TO DO NEXT
Two to three concrete, specific next steps the operator can take this week. One sentence each.

CONFIDENCE
One sentence stating how confident you are (low / medium / high) and why.

Rules:
- Ground every claim in the data provided. If data is missing, say so.
- Do not invent specific numbers. Use the trend descriptions verbatim.
- Keep each section short — no padding, no hedging, no "it's worth noting".
- Do not use Markdown formatting (no **, no ###, no bullet points with - or *).

--- DATA ---
${contextParts.length > 0 ? contextParts.join("\n\n") : "No data available for this period."}
`;

			const model = aiConfig.model || "gemini-2.5-flash";
			const wantStream =
				req.query?.stream === "true" || req.query?.stream === "1";

			// Streaming path: emit tokens as they arrive, then a final `done`
			// event with the parsed sections. The frontend can render the raw
			// text while generation happens and swap to the structured view
			// once the `done` event lands.
			if (wantStream && aiConfig.provider === "gemini") {
				writeSseHeaders(res);
				try {
					const result = await streamGemini(res, {
						apiKey: aiConfig.apiKey,
						model,
						prompt: systemPrompt,
						maxOutputTokens: 900,
						temperature: 0.35,
					});
					const rawText =
						result.text || "Investigation could not be completed.";
					const sections = parseInvestigationTranscript(rawText);
					if (result.usage) {
						await trackAICost(
							user.id,
							result.usage.promptTokenCount || 0,
							result.usage.candidatesTokenCount || 0,
							model,
							"investigate",
							aiConfig.source ?? "user",
						);
					}
					sendDone(res, {
						metric,
						periodDays,
						accountUsername: account.username,
						sections,
						rawTranscript: rawText,
						dataUsed,
					});
					return;
				} catch (streamErr) {
					logger.error("[ai/investigate] Stream failed", {
						userId: user.id,
						accountId,
						error:
							streamErr instanceof Error
								? streamErr.message
								: String(streamErr),
					});
					sendError(res, "Investigation failed");
					return;
				}
			}

			const response = await generateWithProvider(systemPrompt, {
				provider: aiConfig.provider,
				apiKey: aiConfig.apiKey,
				baseUrl: aiConfig.baseUrl,
				model,
				keySource: aiConfig.source,
				ideaCount: 1,
				actionLog: {
					userId: user.id,
					accountId,
					surface: "analytics",
					actionType: "investigate",
					inputText: `${metric}:${hypothesis || ""}`.slice(0, 2000),
					metadata: {
						provider: aiConfig.provider,
						metric,
						periodDays,
						dataUsed,
						streamRequested: wantStream,
					},
				},
			});

			const rawText = sanitizeAIOutput(
				response || "Investigation could not be completed.",
			);

			// 7. Parse structured response into sections
			const sections = parseInvestigationTranscript(rawText);

			if (wantStream) {
				writeSseHeaders(res);
				sendDone(res, {
					metric,
					periodDays,
					accountUsername: account.username,
					sections,
					rawTranscript: rawText,
					dataUsed,
					streamed: false,
				});
				return;
			}

			return apiSuccess(res, {
				metric,
				periodDays,
				accountUsername: account.username,
				sections,
				rawTranscript: rawText,
				dataUsed,
			});
		} catch (err: unknown) {
			logger.error("[ai/investigate] Failed", {
				userId: user.id,
				accountId,
				metric,
				error: err instanceof Error ? err.message : String(err),
			});
			return apiError(res, 502, "Investigation failed");
		}
	},
);

const SECTION_HEADERS = [
	"SUMMARY",
	"OBSERVATIONS",
	"LIKELY DRIVERS",
	"WHAT TO DO NEXT",
	"CONFIDENCE",
] as const;

function parseInvestigationTranscript(text: string): InvestigationSection[] {
	const sections: InvestigationSection[] = [];
	const lines = text.split(/\r?\n/);

	let currentTitle: string | null = null;
	let currentBody: string[] = [];

	const flush = () => {
		if (currentTitle !== null) {
			const body = currentBody.join("\n").trim();
			if (body) sections.push({ title: currentTitle, body });
		}
	};

	for (const rawLine of lines) {
		const line = rawLine.trim();
		const matchedHeader = SECTION_HEADERS.find((h) => line.toUpperCase() === h);
		if (matchedHeader) {
			flush();
			currentTitle = matchedHeader;
			currentBody = [];
		} else if (currentTitle !== null) {
			currentBody.push(rawLine);
		}
	}
	flush();

	// Fallback: if the model ignored the structure, return one section with the raw text
	if (sections.length === 0 && text.trim()) {
		sections.push({ title: "Investigation", body: text.trim() });
	}

	return sections;
}
