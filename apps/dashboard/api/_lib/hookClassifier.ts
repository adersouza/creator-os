/**
 * First-line hook classifier — bucket the opening line of a caption into a
 * fixed taxonomy so the dashboard can rank reach by hook archetype.
 *
 * Mockup: dashboard-research-validated-2026.html R6 ("First-line hook NLP").
 *
 * Rule-based first (no Gemini cost) — handles ~90% of cases. Falls through
 * to Gemini for ambiguous openers.
 *
 * Persisted via posts.hook_class + hook_class_confidence + hook_classified_at
 * (migration 20260430180200).
 */

import { GoogleGenAI } from "@google/genai";
import {
	buildAICacheKey,
	getCachedAIResponse,
	setCachedAIResponse,
} from "./aiCache.js";
import { trackGeminiResponseCost } from "./aiUsageTracking.js";
import { logger } from "./logger.js";
import { escapeForPrompt } from "./promptUtils.js";

export const HOOK_CLASSES = [
	"question", // "what's your favorite…?"
	"stat", // "73% of creators don't know…"
	"command", // "Stop scrolling. Watch this."
	"list", // "5 things I learned…"
	"story", // "I quit my 9-5…"
	"contrarian", // "Stop posting at 6pm. Here's why."
	"intrigue", // "Here's what nobody tells you…"
	"plain", // default fallback
] as const;

export type HookClass = (typeof HOOK_CLASSES)[number];

export interface HookClassificationResult {
	hookClass: HookClass;
	confidence: number;
	source: "rule" | "ai";
}

const STORY_PRONOUN_RE = /^\s*(?:i\b|my\b|we\b|i'?m\b|i'?ve\b)/i;
const COMMAND_VERB_RE =
	/^\s*(?:stop|start|don'?t|never|always|watch|listen|read|try|do|stop\s|do not|imagine)\b/i;
const CONTRARIAN_RE =
	/^\s*(?:stop|don'?t|nobody|forget|unpopular|hot take|hot-take)\b/i;
const INTRIGUE_RE =
	/^\s*(?:here'?s|the (?:truth|secret|reason|trick|real)|what nobody|what they don'?t|why nobody|the real)/i;
const LIST_PREFIX_RE = /^\s*(?:\d+\s+(?:things|reasons|ways|tips|lessons|signs|mistakes|rules|truths)|top\s+\d+)\b/i;
const STAT_PREFIX_RE = /^\s*\d{1,3}\s*(?:%|percent)\b|^\s*\d{2,}\s+(?:of|out of|million|thousand)/i;

function getFirstLine(caption: string): string {
	const trimmed = (caption || "").trim();
	if (!trimmed) return "";
	// Try sentence-end punctuation first; fall back to newline; cap at 200 chars.
	const sentenceEnd = trimmed.search(/[.!?\n]/);
	const slice = sentenceEnd > 0 ? trimmed.slice(0, sentenceEnd + 1) : trimmed;
	return slice.slice(0, 200).trim();
}

/**
 * Rule-based hook classification. Returns null when the opener is genuinely
 * ambiguous and a Gemini call would help.
 */
function classifyByRules(caption: string): HookClassificationResult | null {
	const first = getFirstLine(caption);
	if (!first) return null;

	// Order matters — list/contrarian/intrigue patterns can also match
	// command/story rules, so check the more specific buckets first.
	if (LIST_PREFIX_RE.test(first)) {
		return { hookClass: "list", confidence: 0.85, source: "rule" };
	}
	if (STAT_PREFIX_RE.test(first)) {
		return { hookClass: "stat", confidence: 0.85, source: "rule" };
	}
	if (CONTRARIAN_RE.test(first) && /\bbut\b|\bbecause\b|\bhere'?s why\b/i.test(first)) {
		return { hookClass: "contrarian", confidence: 0.8, source: "rule" };
	}
	if (INTRIGUE_RE.test(first)) {
		return { hookClass: "intrigue", confidence: 0.8, source: "rule" };
	}
	if (first.endsWith("?") && first.length < 120) {
		return { hookClass: "question", confidence: 0.85, source: "rule" };
	}
	if (COMMAND_VERB_RE.test(first) && first.length < 80) {
		return { hookClass: "command", confidence: 0.7, source: "rule" };
	}
	if (STORY_PRONOUN_RE.test(first)) {
		return { hookClass: "story", confidence: 0.75, source: "rule" };
	}

	// Genuinely ambiguous opener — let Gemini decide.
	return null;
}

const HOOK_CACHE_TTL = 7 * 24 * 3600;
const geminiClients = new Map<string, GoogleGenAI>();

function getGeminiClient(apiKey: string): GoogleGenAI {
	let client = geminiClients.get(apiKey);
	if (!client) {
		client = new GoogleGenAI({ apiKey });
		geminiClients.set(apiKey, client);
	}
	return client;
}

export async function classifyHook(
	apiKey: string,
	caption: string,
	userId: string = "platform",
): Promise<HookClassificationResult> {
	const ruled = classifyByRules(caption);
	if (ruled) return ruled;

	const first = getFirstLine(caption);
	if (!first) {
		// No caption → empty visual post → no hook to classify.
		return { hookClass: "plain", confidence: 0.6, source: "rule" };
	}

	const prompt = `Classify the OPENING LINE of this social post into exactly ONE of: ${HOOK_CLASSES.join(", ")}.

Opening line: "${escapeForPrompt(first)}"

Definitions:
- question: opens with a question to the reader
- stat: opens with a number, percentage, or claim of magnitude
- command: opens with an imperative verb directed at the reader
- list: opens with "5 things", "top 3", "X reasons"
- story: opens with personal narrative ("I", "my", "we")
- contrarian: opens by challenging a popular belief
- intrigue: opens by promising a hidden truth or insider info
- plain: a normal declarative sentence with no specific hook

Respond with ONLY: {"hookClass": "<class>", "confidence": <0.0-1.0>}`;

	const modelId = "gemini-2.0-flash";
	const cacheKey = buildAICacheKey(prompt, modelId, 0.2);
	const cached = await getCachedAIResponse(cacheKey);
	if (cached) {
		try {
			const parsed = JSON.parse(cached) as HookClassificationResult;
			return { ...parsed, source: "ai" };
		} catch {}
	}

	try {
		const client = getGeminiClient(apiKey);
		let response: { text?: string | undefined } = {};
		for (let attempt = 0; attempt < 3; attempt++) {
			try {
				response = await client.models.generateContent({
					model: modelId,
					contents: prompt,
					config: { maxOutputTokens: 80, temperature: 0.2 },
				});
				break;
			} catch (retryErr: unknown) {
				if (attempt === 2) throw retryErr;
				const status = (retryErr as { status?: number | undefined; code?: number | undefined })?.status ??
					(retryErr as { status?: number | undefined; code?: number | undefined })?.code;
				if (status && status !== 429 && status < 500) throw retryErr;
				await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
			}
		}
		trackGeminiResponseCost(
			userId,
			response,
			modelId,
			"hook_classifier",
			"env_fallback",
		);
		const text = (response.text || "").trim();
		const jsonMatch = text.match(/\{[^}]+\}/);
		if (!jsonMatch) {
			return { hookClass: "plain", confidence: 0.4, source: "ai" };
		}
		const parsed = JSON.parse(jsonMatch[0]);
		const cls = (HOOK_CLASSES as readonly string[]).includes(parsed.hookClass)
			? (parsed.hookClass as HookClass)
			: "plain";
		const confidence =
			typeof parsed.confidence === "number"
				? Math.min(1, Math.max(0, parsed.confidence))
				: 0.5;
		const result: HookClassificationResult = {
			hookClass: cls,
			confidence,
			source: "ai",
		};
		await setCachedAIResponse(cacheKey, JSON.stringify(result), HOOK_CACHE_TTL);
		return result;
	} catch (err) {
		logger.warn("[hookClassifier] Gemini classification failed", {
			error: err instanceof Error ? err.message : String(err),
		});
		return { hookClass: "plain", confidence: 0.3, source: "ai" };
	}
}
