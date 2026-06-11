// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * AI Cost Tracker — Estimates and tracks Gemini API spending per user per day.
 *
 * Populates three Redis key families that ai-cost-report.ts reads:
 *   ai_cost:{userId}:{date}           — total micro-USD per user per day
 *   ai_cost_endpoint:{feature}:{date} — total micro-USD per feature per day
 *   ai_model_calls:{flash|pro}:{date} — call count per model class per day
 *
 * Fire-and-forget — never throws or blocks the request.
 */

import { logger } from "./logger.js";
import { getRedis } from "./redis.js";

export const PRICING: Record<
	string,
	{ input: number; output: number; thinking?: number | undefined }
> = {
	"gemini-2.5-flash": { input: 0.15, output: 0.6, thinking: 3.5 },
	"gemini-2.5-flash-lite": { input: 0.075, output: 0.3 },
	"gemini-2.0-flash": { input: 0.075, output: 0.3 },
	"gemini-2.0-flash-lite": { input: 0.04, output: 0.15 },
	"gemini-1.5-flash": { input: 0.075, output: 0.3 },
	"gemini-2.5-pro": { input: 1.25, output: 10.0, thinking: 10.0 },
	"gemini-2.0-pro": { input: 1.25, output: 5.0 },
	"gemini-1.5-pro": { input: 1.25, output: 5.0 },
	// xAI Grok 4.1 Fast — preferred writing model + W3 hero-post router target.
	// Pricing per production_playbook_2026.md / x.ai/api.
	"grok-4-1-fast": { input: 0.2, output: 0.5 },
	"grok-4-1-fast-reasoning": { input: 0.2, output: 0.5 },
	// OpenAI pricing, per official API pricing page (USD / 1M tokens).
	"gpt-4o": { input: 2.5, output: 10.0 },
	"gpt-4o-mini": { input: 0.15, output: 0.6 },
	"gpt-4.1-mini": { input: 0.4, output: 1.6 },
	// Anthropic pricing, per official Claude model/pricing pages (USD / 1M tokens).
	"claude-haiku-4.5": { input: 1.0, output: 5.0 },
	"claude-haiku-4-5": { input: 1.0, output: 5.0 },
	"claude-haiku-4-5-20251001": { input: 1.0, output: 5.0 },
	"claude-sonnet-4.5": { input: 3.0, output: 15.0 },
	"claude-sonnet-4-5": { input: 3.0, output: 15.0 },
	"claude-sonnet-4.6": { input: 3.0, output: 15.0 },
	"claude-sonnet-4-6": { input: 3.0, output: 15.0 },
	"claude-opus-4.7": { input: 5.0, output: 25.0 },
	"claude-opus-4-7": { input: 5.0, output: 25.0 },
};

const TTL_SECONDS = 8 * 24 * 60 * 60; // 8 days — enough for weekly report

function getDateKey(): string {
	return new Date().toISOString().slice(0, 10); // YYYY-MM-DD
}

function redisKey(userId: string, date: string): string {
	return `ai_cost:${userId}:${date}`;
}

export function normalizeAIModelName(model: string): string {
	return model.toLowerCase().replace(/^models\//, "").replace(/_/g, "-");
}

export function estimateAICostUsd(
	model: string,
	inputTokens: number,
	outputTokens: number,
	thinkingTokens: number = 0,
): number {
	const normalizedModel = normalizeAIModelName(model);
	const pricing =
		PRICING[normalizedModel] ??
		PRICING[
			Object.keys(PRICING).find((key) => normalizedModel.startsWith(key)) ?? ""
		] ??
		PRICING["gemini-2.0-flash"];
	const inputCost = (inputTokens / 1_000_000) * pricing!.input;
	const outputCost = (outputTokens / 1_000_000) * pricing!.output;
	const thinkingCost = pricing!.thinking
		? (thinkingTokens / 1_000_000) * pricing!.thinking
		: 0;
	return inputCost + outputCost + thinkingCost;
}

function modelCallClass(model: string): string {
	const normalizedModel = normalizeAIModelName(model);
	if (normalizedModel.includes("pro") || normalizedModel.includes("opus")) {
		return "pro";
	}
	if (normalizedModel.includes("sonnet")) return "sonnet";
	if (normalizedModel.includes("haiku")) return "haiku";
	if (normalizedModel.includes("gpt")) return "openai";
	if (normalizedModel.includes("grok")) return "grok";
	return "flash";
}

/**
 * Track estimated cost for a Gemini call.
 * @param feature - Which AI feature triggered the call (e.g. "content_generation")
 * @param keySource - "user" if using user's own key, "env_fallback" if using platform key
 * @param thinkingTokens - Thinking tokens (gemini-2.5-* only, $3.50/M for flash, $10/M for pro)
 */
export async function trackAICost(
	userId: string,
	inputTokens: number,
	outputTokens: number,
	model: string,
	feature: string = "generate",
	keySource?: "user" | "env_fallback",
	thinkingTokens: number = 0,
): Promise<void> {
	try {
		const normalizedModel = normalizeAIModelName(model);
		const totalCost = estimateAICostUsd(
			normalizedModel,
			inputTokens,
			outputTokens,
			thinkingTokens,
		);

		if (totalCost <= 0) return;

		const redis = getRedis();
		const date = getDateKey();
		const userKey = redisKey(userId, date);
		const endpointKey = `ai_cost_endpoint:${feature}:${date}`;
		const modelClass = modelCallClass(normalizedModel);
		const modelKey = `ai_model_calls:${modelClass}:${date}`;

		// Increment by cost in microdollars (avoid floating point issues)
		const microCost = Math.round(totalCost * 1_000_000);

		const ops: Promise<unknown>[] = [
			redis
				.incrby(userKey, microCost)
				.then(() => redis.expire(userKey, TTL_SECONDS)),
			redis
				.incrby(endpointKey, microCost)
				.then(() => redis.expire(endpointKey, TTL_SECONDS)),
			redis.incr(modelKey).then(() => redis.expire(modelKey, TTL_SECONDS)),
		];

		// Track platform key cost separately so we know platform vs user spend
		if (keySource === "env_fallback") {
			const platformKey = `ai_cost:platform:${date}`;
			ops.push(
				redis
					.incrby(platformKey, microCost)
					.then(() => redis.expire(platformKey, TTL_SECONDS)),
			);
		}

		await Promise.all(ops);

		logger.info("[aiCostTracker] Tracked", {
			userId: userId.slice(0, 8),
			model: normalizedModel,
			feature,
			inputTokens,
			outputTokens,
			costUsd: totalCost.toFixed(6),
		});
	} catch (err) {
		// Fire-and-forget — never let cost tracking break the request
		logger.warn("[aiCostTracker] cost tracking failed", { error: String(err) });
	}
}

/**
 * Get estimated AI cost today for a user (in USD).
 */
export async function getAICostToday(userId: string): Promise<number> {
	try {
		const redis = getRedis();
		const key = redisKey(userId, getDateKey());
		const microCost = (await redis.get(key)) as number | null;
		return microCost ? microCost / 1_000_000 : 0;
	} catch (err) {
		logger.warn("[aiCostTracker] Failed to fetch AI cost from Redis for user", {
			userId,
			error: String(err),
		});
		return 0;
	}
}

// ---------------------------------------------------------------------------
// Daily spend limit — blocks all Gemini calls when platform spend exceeds cap
// ---------------------------------------------------------------------------

/** Daily platform spend cap in USD. Env-configurable, defaults to $2/day. */
const DAILY_SPEND_LIMIT_USD = Number(
	process.env.AI_DAILY_SPEND_LIMIT_USD || "2",
);

/** In-memory cache so we don't hit Redis on every single call */
let _limitCache: { blocked: boolean; checkedAt: number; spentUsd: number } = {
	blocked: false,
	checkedAt: 0,
	spentUsd: 0,
};
const LIMIT_CACHE_TTL_MS = 60_000; // re-check Redis every 60s

/**
 * Check if the platform daily spend limit has been reached.
 * Returns { allowed: true } or { allowed: false, spentUsd, limitUsd }.
 * Fail-open: if Redis is down, allow the call.
 */
export async function checkDailySpendLimit(): Promise<{
	allowed: boolean;
	spentUsd: number;
	limitUsd: number;
}> {
	const limitUsd = DAILY_SPEND_LIMIT_USD;

	// Return cached result if fresh enough
	if (Date.now() - _limitCache.checkedAt < LIMIT_CACHE_TTL_MS) {
		return {
			allowed: !_limitCache.blocked,
			spentUsd: _limitCache.spentUsd,
			limitUsd,
		};
	}

	try {
		const redis = getRedis();
		const date = getDateKey();
		const platformKey = `ai_cost:platform:${date}`;
		const microCost = (await redis.get(platformKey)) as number | null;
		const spentUsd = microCost ? microCost / 1_000_000 : 0;
		const blocked = spentUsd >= limitUsd;

		_limitCache = { blocked, checkedAt: Date.now(), spentUsd };

		if (blocked) {
			logger.warn("[aiCostTracker] Daily spend limit reached", {
				spentUsd: spentUsd.toFixed(4),
				limitUsd,
			});
		}

		return { allowed: !blocked, spentUsd, limitUsd };
	} catch (err) {
		// Fail-open — don't block generation if Redis is down
		logger.warn("[aiCostTracker] spend limit check failed, allowing", {
			error: String(err),
		});
		return { allowed: true, spentUsd: 0, limitUsd };
	}
}
