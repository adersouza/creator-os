/**
 * LLM Quality Judge — batched 5-dim provider-routed judge for autoposter content.
 *
 * Replaces the rolled-back regex scorer's hard floor with a richer pass.
 * Five dimensions, each scored 1–5:
 *   hook    — does the first line make a reader stop scrolling?
 *   voice   — does it sound like a real person, not AI?
 *   safety  — is it free of slurs, harassment, claims of harm?
 *   quality — is the writing crisp and specific, not generic?
 *   novelty — is the angle distinctive vs. boilerplate niche posts?
 *
 * Composite: weighted mean (hook 25, voice 25, safety 20, quality 15, novelty 15).
 * A score of 1 on safety vetoes regardless of composite (any safety risk fails).
 *
 * Pipeline contract: the batch layer returns `{ skipped: true, reason }` for
 * LLM/provider failures. The caller decides whether that is fail-open or
 * fail-closed; the autoposter queue-fill path treats enabled judge skips as
 * blocks.
 *
 * Batched in a single provider call so a fill of 20 candidates is one API hit
 * instead of 20. Posts come in indexed; the judge returns an array preserving
 * order and length so the caller can zip results back to candidates safely.
 */

import { logger } from "../../logger.js";
import { z } from "../../zodCompat.js";
import type { Infer } from "../../zodCompat.js";
import { generateWithProvider } from "./aiProviders.js";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface JudgeCandidate {
	/** Stable index — used to align response order with input. */
	index: number;
	content: string;
}

export interface JudgeDimensions {
	hook: number;
	voice: number;
	safety: number;
	quality: number;
	novelty: number;
}

export type JudgeVerdict =
	| {
			index: number;
			passed: true;
			score: number;
			dimensions: JudgeDimensions;
			rationale?: string | undefined;
	  }
	| {
			index: number;
			passed: false;
			score: number;
			dimensions: JudgeDimensions;
			rejectReason: string;
			rationale?: string | undefined;
	  }
	| {
			index: number;
			skipped: true;
			reason: string;
	  };

export interface JudgeBatchOptions {
	apiKey: string;
	/** gemini, xai, openai, anthropic. Defaults to gemini for legacy callers. */
	provider?: string | undefined;
	/** Caller may override with a configured model. */
	model?: string | undefined;
	/** Composite threshold below which a post is rejected. 1.0–5.0. */
	minScore: number;
	/** Optional voice context — short string injected into the rubric so the
	 *  judge can score "voice" against the group's persona, not a generic ideal. */
	voiceProfileHint?: string | undefined;
	/** Hard timeout in ms. Default 20s — batches of 20 typically resolve <5s. */
	timeoutMs?: number | undefined;
	/** When set, the judge attributes Gemini token cost to this user. */
	costAttribution?: {
        		userId: string;
        		source: "user" | "env_fallback";
        	} | undefined;
	workspaceId?: string | undefined;
	groupId?: string | undefined;
}

// ---------------------------------------------------------------------------
// Internal: response schema
// ---------------------------------------------------------------------------

const DimensionSchema = z
	.number()
	.int()
	.min(1)
	.max(5);

const VerdictItemSchema = z.object({
	i: z.number().int().min(0),
	hook: DimensionSchema,
	voice: DimensionSchema,
	safety: DimensionSchema,
	quality: DimensionSchema,
	novelty: DimensionSchema,
	rationale: z.string().max(160).optional(),
});

const BatchResponseSchema = z.object({
	verdicts: z.array(VerdictItemSchema).min(1),
});

type VerdictItem = Infer<typeof VerdictItemSchema>;

// ---------------------------------------------------------------------------
// Compose composite — weighted mean, with a safety veto.
// Weights anchor to "hook + voice are why a post earns reach; quality and
// novelty are tiebreakers; safety is a binary risk floor".
// ---------------------------------------------------------------------------

const WEIGHTS = {
	hook: 0.25,
	voice: 0.25,
	safety: 0.2,
	quality: 0.15,
	novelty: 0.15,
} as const;

export function composeScore(d: JudgeDimensions): number {
	const raw =
		d.hook * WEIGHTS.hook +
		d.voice * WEIGHTS.voice +
		d.safety * WEIGHTS.safety +
		d.quality * WEIGHTS.quality +
		d.novelty * WEIGHTS.novelty;
	return Math.round(raw * 10) / 10;
}

// ---------------------------------------------------------------------------
// Prompt
// ---------------------------------------------------------------------------

function buildJudgePrompt(
	candidates: JudgeCandidate[],
	voiceProfileHint?: string,
): string {
	const voiceLine = voiceProfileHint?.trim()
		? `\nGroup voice (score "voice" against THIS, not a generic ideal):\n"${voiceProfileHint.replace(/"/g, "'").slice(0, 400)}"\n`
		: "";

	const items = candidates
		.map(
			(c) =>
				`#${c.index} | ${c.content.replace(/\s+/g, " ").trim().slice(0, 400)}`,
		)
		.join("\n");

	return `You are a strict content quality judge for a Threads/Instagram autoposter.
Score each post on FIVE dimensions, integer 1-5:

  hook    — does the first line stop a scroll? (1 = generic, 5 = compels click)
  voice   — does it sound like a real person, not an AI? (1 = corporate AI, 5 = unmistakably human)
  safety  — free of slurs, harassment, self-harm claims, defamation? (1 = clear violation, 5 = totally safe)
  quality — crisp, specific, not generic? (1 = platitude, 5 = sharp & specific)
  novelty — distinctive angle vs. niche boilerplate? (1 = "Mondays am I right", 5 = unique take)

Calibration anchors:
  HOOK: "I almost cried at the airport today" → 5. "Just thinking about life" → 1.
  VOICE: "ok actually idc what u say, i cried" → 5. "Embracing the journey of growth" → 1.
  SAFETY: any explicit slur, harassment, or harm claim → 1. Mild edge / dark humor → 3-4. Pure neutral → 5.
  QUALITY: "I spent 3 hours on Pinterest and built nothing" → 5. "Productivity is a mindset" → 1.
  NOVELTY: angle a niche peer has not posted this week → 4-5. Boilerplate format/topic → 1-2.
${voiceLine}
Posts (one per line, prefixed with #INDEX):
${items}

Return ONLY a JSON object with this exact shape — no Markdown fence, no commentary:
{
  "verdicts": [
    { "i": <index>, "hook": 1-5, "voice": 1-5, "safety": 1-5, "quality": 1-5, "novelty": 1-5, "rationale": "<<=120 chars>" }
  ]
}

Rules:
- One verdict object per post, same indexes as input.
- rationale: ONE short clause naming the strongest signal. Optional. Skip if obvious.
- Be calibrated: a 5 means top-decile, not "fine". A 3 is "competent but unremarkable".`;
}

// ---------------------------------------------------------------------------
// Public: judgeBatch
// ---------------------------------------------------------------------------

/**
 * Judge a batch of candidate posts. Returns a JudgeVerdict for each input,
 * preserving order. On any LLM/parse failure, returns `skipped: true` for
 * every input — pipeline treats those as passes so a degraded judge never
 * stalls the queue.
 */
export async function judgeBatch(
	candidates: JudgeCandidate[],
	options: JudgeBatchOptions,
): Promise<JudgeVerdict[]> {
	if (candidates.length === 0) return [];

	const {
		apiKey,
		provider = "gemini",
		model,
		minScore,
		voiceProfileHint,
		timeoutMs = 20_000,
		costAttribution,
		workspaceId,
		groupId,
	} = options;

	const skipAll = (reason: string): JudgeVerdict[] =>
		candidates.map((c) => ({
			index: c.index,
			skipped: true,
			reason,
		}));

	if (!apiKey) return skipAll("no_api_key");

	let rawText: string;
	try {
		const prompt = buildJudgePrompt(candidates, voiceProfileHint);

		// Capture the timeout handle so we can cancel it once the LLM
		// resolves first — leaving the timer running would keep the Vercel
		// Fluid Compute function alive past its useful work.
		let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
		const timeoutPromise = new Promise<never>((_, reject) => {
			timeoutHandle = setTimeout(
				() => reject(new Error("judge_timeout")),
				timeoutMs,
			);
		});

		try {
			const responseText = await Promise.race([
				generateWithProvider(prompt, {
					provider,
					apiKey,
					model,
					ideaCount: candidates.length,
					allowProviderFallback: false,
					useStructuredOutput: provider === "gemini",
					structuredOutputSchema:
						provider === "gemini"
							? {
									type: "OBJECT",
									properties: {
										verdicts: {
											type: "ARRAY",
											items: {
												type: "OBJECT",
												properties: {
													i: { type: "INTEGER" },
													hook: { type: "INTEGER" },
													voice: { type: "INTEGER" },
													safety: { type: "INTEGER" },
													quality: { type: "INTEGER" },
													novelty: { type: "INTEGER" },
													rationale: { type: "STRING" },
												},
												required: [
													"i",
													"hook",
													"voice",
													"safety",
													"quality",
													"novelty",
												],
											},
										},
									},
									required: ["verdicts"],
								}
							: undefined,
					systemInstruction:
						"You are a strict social-content quality judge. Return JSON only.",
					actionLog: costAttribution
						? {
								userId: costAttribution.userId,
								surface: "autopilot",
								actionType: "autopost_judge",
								metadata: {
									workspaceId,
									groupId,
									provider,
								},
							}
						: undefined,
					keySource: costAttribution?.source,
				}),
				timeoutPromise,
			]);
			rawText = (responseText || "").trim();
		} finally {
			if (timeoutHandle !== undefined) clearTimeout(timeoutHandle);
		}

		if (!rawText) return skipAll("empty_response");
	} catch (err) {
		const reason =
			err instanceof Error && err.message === "judge_timeout"
				? "timeout"
				: "llm_error";
		logger.warn("[llmJudge] LLM call failed", {
			provider,
			reason,
			error: err instanceof Error ? err.message : String(err),
			batchSize: candidates.length,
		});
		return skipAll(reason);
	}

	let parsed: unknown;
	try {
		parsed = JSON.parse(rawText);
	} catch {
		// Some models occasionally wrap JSON in fences despite responseMimeType.
		const match = rawText.match(/\{[\s\S]*\}/);
		if (!match) return skipAll("parse_error");
		try {
			parsed = JSON.parse(match[0]);
		} catch {
			return skipAll("parse_error");
		}
	}

	const verified = BatchResponseSchema.safeParse(parsed);
	if (!verified.success) {
		logger.warn("[llmJudge] Schema validation failed — failing open", {
			issues: verified.error.issues.map((i) => i.message).slice(0, 3),
			preview: rawText.slice(0, 200),
		});
		return skipAll("schema_error");
	}

	const byIndex = new Map<number, VerdictItem>();
	for (const v of verified.data.verdicts) byIndex.set(v.i, v);

	return candidates.map<JudgeVerdict>((c) => {
		const v = byIndex.get(c.index);
		if (!v) {
			return {
				index: c.index,
				skipped: true,
				reason: "missing_verdict",
			};
		}

		const dimensions: JudgeDimensions = {
			hook: v.hook,
			voice: v.voice,
			safety: v.safety,
			quality: v.quality,
			novelty: v.novelty,
		};
		const score = composeScore(dimensions);

		// Safety veto: a post the judge flags as outright unsafe (1) is rejected
		// regardless of the composite — even if hook/voice/quality compensate.
		if (dimensions.safety <= 1) {
			return {
				index: c.index,
				passed: false,
				score,
				dimensions,
				rejectReason: "safety_veto",
				rationale: v.rationale,
			};
		}

		if (score < minScore) {
			return {
				index: c.index,
				passed: false,
				score,
				dimensions,
				rejectReason: `below_threshold_${score}`,
				rationale: v.rationale,
			};
		}

		return {
			index: c.index,
			passed: true,
			score,
			dimensions,
			rationale: v.rationale,
		};
	});
}
