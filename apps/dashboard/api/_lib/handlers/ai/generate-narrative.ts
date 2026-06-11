/**
 * POST /api/ai?action=generate-narrative
 *
 * Generates the Analytics hero narrative (spec §3 / §12) — eyebrow, headline,
 * body segments with .ev evidence links. Returns the same
 * shape as hero/narratives.ts so HeroTile can swap between LLM output and
 * the hardcoded fallback without refactoring the renderer.
 *
 * Meta Platform Terms: we never pass raw Meta counts to the LLM. The client
 * sends computed deltas (ratios, counts of user-owned accounts, severity
 * buckets, descriptive phrases) — derived signals that aren't raw API
 * metrics. Each string goes through escapeForPrompt + sanitizeAIOutput.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import type { Infer } from "../../zodCompat.js";
import { checkAIRateLimit } from "../../aiRateLimit.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { escapeForPrompt, sanitizeAIOutput } from "../../promptUtils.js";
import { requireMinTier } from "../../tierGate.js";
import { getUserAIConfig } from "../../aiConfig.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";

const PlatformSchema = z.union([
	z.literal("all"),
	z.literal("ig"),
	z.literal("threads"),
]);

const AnomalyInputSchema = z.object({
	accountLabel: z.string().max(80).optional(),
	reason: z.string().max(120),
	severity: z.union([z.literal("critical"), z.literal("warning")]),
	/** Descriptive, not numeric — e.g. "down sharply", "search surface collapse". */
	description: z.string().max(200).optional(),
});

const BodySchema = z.object({
	platform: PlatformSchema,
	/** Already-computed fleet reach delta percent for the selected window. */
	reachDeltaPct: z.number().nullable().optional(),
	/** Count of user-owned accounts flagged as at-risk (EQS<40). */
	atRiskCount: z.number().int().min(0),
	/** Total in-scope accounts — used to ground language ("6 of 14"). */
	accountCount: z.number().int().min(0),
	/** Count of critical + warning fleet alerts in the current window. */
	anomalyCount: z.number().int().min(0).optional().default(0),
	/** Top 5 concrete anomalies to anchor the narrative in. */
	topAnomalies: z.array(AnomalyInputSchema).max(5).optional().default([]),
	/** Cohort percentile (0-100) for a KPI; undefined when no cohort data. */
	cohortPercentile: z.number().min(0).max(100).nullable().optional(),
	/** "fashion-creator" etc. — used to reference the niche in prose. */
	nicheLabel: z.string().max(64).nullable().optional(),
});

type NarrativeBody = Infer<typeof BodySchema>;

const EvidenceLinkSchema = z.object({
	kind: z.literal("ev"),
	text: z.string().min(1).max(80),
	n: z.number().int().min(1).max(9),
});

const NarrativeResponseSchema = z.object({
	eyebrow: z.string().max(40),
	/** Headline may include literal tokens {{REACH_DELTA}} / {{AT_RISK_COUNT}}
	 * which the frontend renderer fills from live metrics before display. */
	headline: z.string().max(240),
	body: z
		.array(z.union([z.string(), EvidenceLinkSchema]))
		.min(3)
		.max(18),
	anomalyBadge: z.string().max(40),
});

export type NarrativeResponse = Infer<typeof NarrativeResponseSchema>;

function describeReachDelta(
	pct: number | null | undefined,
): "up sharply" | "up" | "flat" | "down" | "down sharply" | "unknown" {
	if (pct === null || pct === undefined || !Number.isFinite(pct))
		return "unknown";
	if (pct > 25) return "up sharply";
	if (pct > 5) return "up";
	if (pct >= -5) return "flat";
	if (pct >= -25) return "down";
	return "down sharply";
}

function describeCohortPercentile(p: number | null | undefined): string {
	if (p === null || p === undefined || !Number.isFinite(p))
		return "unknown percentile";
	if (p >= 80) return `P${Math.round(p)} (top quintile)`;
	if (p >= 60) return `P${Math.round(p)} (above-median)`;
	if (p >= 40) return `P${Math.round(p)} (median band)`;
	if (p >= 20) return `P${Math.round(p)} (below-median)`;
	return `P${Math.round(p)} (bottom quintile)`;
}

/**
 * Meta TOS hygiene: anomaly titles/descriptions are system-generated prose
 * but they interpolate raw counts (e.g. "You lost 237 followers"). Strip any
 * bare integer/float tokens that could carry raw API counts into the LLM
 * context. Percentages and labelled deltas (ratios, P-percentiles) stay — the
 * LLM needs *some* quantitative shape to ground its prose — but absolute
 * counts get buried behind a "(count hidden)" placeholder.
 */
function sanitizeAnomalyText(text: string | undefined): string {
	if (!text) return "";
	return (
		text
			// bare counts: "12345" or "12,345.67" — but leave percentages / P-scores alone
			.replace(/\b\d{2,}(?:[,.]\d+)*(?!\s*[%°])/g, "(count)")
			// trim whitespace introduced by substitution
			.replace(/\s{2,}/g, " ")
			.trim()
	);
}

function buildSystemPrompt(input: NarrativeBody): string {
	const platformName =
		input.platform === "ig"
			? "Instagram"
			: input.platform === "threads"
				? "Threads"
				: "All platforms";

	const reachVerb = describeReachDelta(input.reachDeltaPct);
	const cohort = describeCohortPercentile(input.cohortPercentile ?? null);
	const niche = input.nicheLabel
		? escapeForPrompt(input.nicheLabel).slice(0, 60)
		: "";

	const anomalyLines =
		input.topAnomalies.length > 0
			? input.topAnomalies
					.map((a, i) => {
						const reason = sanitizeAnomalyText(a.reason);
						const desc = sanitizeAnomalyText(a.description);
						return `${i + 1}. [${a.severity}] ${escapeForPrompt(a.accountLabel ?? "account").slice(0, 60)} — ${escapeForPrompt(reason).slice(0, 100)}${
							desc ? ` (${escapeForPrompt(desc).slice(0, 120)})` : ""
						}`;
					})
					.join("\n")
			: "(none)";

	// Few-shot examples use synthetic placeholders only. Do not include concrete
	// dates, external events, or percentages that are not present in input.
	const examples = `EXAMPLE (platform=all):
{
  "eyebrow": "Investigation brief",
  "headline": "Reach is **{{REACH_DELTA}}** across **{{AT_RISK_COUNT}} accounts**, concentrated in the accounts flagged by the evidence grid.",
  "body": [
    "Start with ",
    { "kind": "ev", "text": "the fleet grid", "n": 1 },
    ", then compare discovery and format evidence before changing cadence."
  ],
	  "anomalyBadge": ""
}

EXAMPLE (platform=threads):
{
  "eyebrow": "Investigation brief",
  "headline": "Threads is **steady** overall, but the active warnings point to a narrower execution issue.",
  "body": [
    "Use ",
    { "kind": "ev", "text": "source breakdown", "n": 2 },
    " and ",
    { "kind": "ev", "text": "reply depth", "n": 9 },
    " to confirm whether this is distribution or conversation quality."
  ],
	  "anomalyBadge": ""
}`;

	return `You are writing the hero narrative for a Juno33 fleet analytics dashboard. Tone: direct, operator-facing, no filler. Maximum 3 sentences in the body. Every quantitative claim that deserves a chart drill-in goes in an evidence-link object so the operator can click to the chart.

Return ONLY a valid JSON object matching:
{
  "eyebrow": "Investigation brief",
  "headline": "<sentence with **bold** emphasis on 1-2 spans; may include {{REACH_DELTA}} and {{AT_RISK_COUNT}} token placeholders which the client fills>",
  "body": [ ... ],     // alternating strings and { kind: "ev", text: string, n: 1-9 }
	  "anomalyBadge": ""
}

- body: 3-10 segments total. Strings are prose. Evidence-link objects { kind, text, n } are inline chart links; text is the phrase the reader sees, n is the evidence-section number (1-9) the click scrolls to. Use n=1 for the fleet grid, n=2 for discovery/source, n=3 for format, n=4 for cohort, n=5 for originality/ghost, n=6 for follower attribution, n=7 for forecast, n=8 for funnel/tree, n=9 for reply depth / skip rate.
- headline: ONE sentence. Bold 1-2 substrings with **markdown**. You may reference tokens {{REACH_DELTA}} and {{AT_RISK_COUNT}} — client-side they are replaced with live numbers.
- anomalyBadge: return an empty string. The UI uses the real z-score grid instead of synthetic Sigma labels.
- Never invent facts. If cohortPercentile is unknown, don't mention cohort position. If reach delta is "unknown", don't put a number in the headline.
- Never output raw counts other than account counts; percentages and percentile bands are fine.
- If no anomalies are flagged, write a "fleet looks healthy" narrative that still points to evidence (e.g. top-decile accounts).

Context (do not echo verbatim):
- platform: ${platformName}
- fleet reach trend: ${reachVerb}
- at-risk accounts: ${input.atRiskCount} of ${input.accountCount}
- total anomaly alerts: ${input.anomalyCount}
- cohort standing: ${cohort}
- niche: ${niche || "(unknown)"}
- top anomalies:
${anomalyLines}

${examples}

Respond with ONLY the JSON object. No Markdown fencing. No commentary.`;
}

function fallbackBadge(count: number): string {
	void count;
	return "";
}

function buildFallbackNarrative(input: NarrativeBody): NarrativeResponse {
	const platformName =
		input.platform === "ig"
			? "Instagram"
			: input.platform === "threads"
				? "Threads"
				: "Fleet";
	const reachVerb = describeReachDelta(input.reachDeltaPct);
	const anomaly = input.topAnomalies[0];
	const hasAnomaly =
		!!anomaly || input.anomalyCount > 0 || input.atRiskCount > 0;
	const headline = hasAnomaly
		? `${platformName} needs review: **{{AT_RISK_COUNT}} accounts** are at risk while reach is **${reachVerb}**.`
		: `${platformName} is steady: reach is **${reachVerb}** and no major anomaly cluster is active.`;
	const body: NarrativeResponse["body"] = anomaly
		? [
				"The strongest live signal is ",
				{
					kind: "ev",
					text: sanitizeAnomalyText(anomaly.reason) || "the anomaly grid",
					n: 1,
				},
				". Review the supporting charts before changing cadence.",
			]
		: [
				"Use ",
				{ kind: "ev", text: "fleet evidence", n: 1 },
				" and the forecast rail to confirm whether this is a real shift or normal variance.",
			];
	return {
		eyebrow: "Investigation brief",
		headline,
		body,
		anomalyBadge: fallbackBadge(input.anomalyCount),
	};
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		if (!(await requireMinTier(user.id, "pro", res))) return;

		const parsed = BodySchema.safeParse(req.body ?? {});
		if (!parsed.success) {
			return apiError(res, 400, "Invalid narrative input", {
				details: parsed.error.issues.map((i) => i.message).join(", "),
			});
		}
		const input = parsed.data;

		const rl = await checkAIRateLimit(user.id, "copilot");
		res.setHeader("X-RateLimit-Limit", String(rl.limit));
		res.setHeader("X-RateLimit-Remaining", String(rl.remaining));
		if (!rl.allowed) {
			return apiError(res, 429, "Rate limit exceeded", {
				code: "RATE_LIMITED",
			});
		}

		const aiConfig = await getUserAIConfig(user.id);
		if (!aiConfig) {
			return apiSuccess(res, {
				narrative: buildFallbackNarrative(input),
				fallback: true,
				reason: "NO_API_KEY",
			});
		}

		try {
			const model = aiConfig.model || "gemini-2.5-flash";
			const systemPrompt = buildSystemPrompt(input);
			const response = await generateWithProvider(systemPrompt, {
				provider: aiConfig.provider,
				apiKey: aiConfig.apiKey,
				baseUrl: aiConfig.baseUrl,
				model,
				keySource: aiConfig.source,
				ideaCount: 1,
				actionLog: {
					userId: user.id,
					surface: "analytics",
					actionType: "generate_narrative",
					inputText: systemPrompt.slice(0, 8000),
					metadata: {
						platform: input.platform,
						provider: aiConfig.provider,
						accountCount: input.accountCount,
					},
				},
			});
			const rawText = sanitizeAIOutput(response || "{}");

			let parsedNarrative: unknown;
			try {
				parsedNarrative = JSON.parse(rawText);
			} catch {
				return apiSuccess(res, {
					narrative: buildFallbackNarrative(input),
					fallback: true,
					reason: "PARSE_FAILED",
				});
			}

			const verified = NarrativeResponseSchema.safeParse(parsedNarrative);
			if (!verified.success) {
				logger.warn("[ai/generate-narrative] Narrative failed schema guard", {
					issues: verified.error.issues.map((i) => i.message),
					preview: rawText.slice(0, 200),
				});
				return apiSuccess(res, {
					narrative: buildFallbackNarrative(input),
					fallback: true,
					reason: "SCHEMA_FAILED",
				});
			}

			const narrative: NarrativeResponse = {
				...verified.data,
				anomalyBadge: "",
			};

			return apiSuccess(res, { narrative });
		} catch (err: unknown) {
			logger.error("[ai/generate-narrative] Failed", {
				userId: user.id,
				error: err instanceof Error ? err.message : String(err),
			});
			return apiSuccess(res, {
				narrative: buildFallbackNarrative(input),
				fallback: true,
				reason: "GENERATION_FAILED",
			});
		}
	},
);
