/**
 * Smart-link AI Enhance.
 *
 * Phase 1 backend contract. Uses the configured AI provider when available
 * and falls back to deterministic variants so the editor remains usable.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getUserAIConfig } from "../../aiConfig.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { z, zRecord, zUnknown } from "../../zodCompat.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";

const ItemSchema = z.object({
	id: z.string(),
	title: z.string().default(""),
	url: z.string().default(""),
	clicks: z.number().default(0),
	blockType: z.string().optional(),
	subtitle: z.string().optional(),
	metadata: zRecord(z.string(), zUnknown()).optional(),
});

const EnhanceSchema = z.object({
	link_id: z.string().uuid().optional(),
	items: z.array(ItemSchema).max(100).optional(),
	blocks: z.array(ItemSchema).max(100).optional(),
});

type SmartLinkItem = typeof ItemSchema["_output"];

const MAX_AI_ITEMS = 40;
const MAX_AI_TEXT = 180;
const MAX_AI_URL = 240;

export async function handleEnhance(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = EnhanceSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const inputItems = parsed.data.blocks ?? parsed.data.items ?? [];
	const suggestedItems = inputItems.map((item) => ({
		...item,
		title: smartLabel(item),
	}));
	const reorderedItems = [...inputItems].sort((a, b) => b.clicks - a.clicks);
	const revenueFirst = [...suggestedItems].sort((a, b) => {
		const score = (item: SmartLinkItem) =>
			item.blockType === "tip_jar" ||
			item.blockType === "digital_product" ||
			item.blockType === "affiliate_catalog"
				? 1
				: 0;
		return score(b) - score(a) || b.clicks - a.clicks;
	});
	const fallbackVariants = [
		{
			blocks: suggestedItems,
			reasoning: "Sharper labels with the existing order preserved.",
		},
		{
			blocks: reorderedItems,
			reasoning: "Performance order based on observed click counts.",
		},
		{
			blocks: revenueFirst,
			reasoning: "Revenue-oriented order prioritizing monetization blocks.",
		},
	];
	const rl = await checkRateLimit({
		key: `ai:smart-links-enhance:${userId}:hour`,
		limit: 60,
		windowSeconds: 3600,
		failMode: "closed",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "AI rate limit exceeded. Try again shortly.");
	}
	const aiVariants = await generateVariantsWithAI(userId, inputItems);

	return apiSuccess(res, {
		suggestedItems,
		reorderedItems,
		variants: aiVariants ?? fallbackVariants,
		reasoning: [
			{
				type: "tip",
				text: "Labels were rewritten to state the action and context instead of generic click copy.",
			},
			{
				type: "positive",
				text: "Reorder is based on observed click counts so proven blocks move closer to the top.",
			},
		],
	});
}

async function generateVariantsWithAI(
	userId: string,
	items: SmartLinkItem[],
): Promise<Array<{ blocks: SmartLinkItem[]; reasoning: string }> | null> {
	if (!items.length) return null;
	const aiConfig = await getUserAIConfig(userId);
	if (!aiConfig) return null;
	const promptItems = items.slice(0, MAX_AI_ITEMS).map(toPromptItem);
	const prompt = [
		"You are improving a creator bio-link page.",
		'Return strict JSON only with shape {"variants":[{"blocks":[],"reasoning":""}]}',
		"Create exactly 3 variants. Return block ids in the suggested order plus edited title/subtitle only.",
		"Do not return metadata, URLs, scripts, markdown, or unsupported block types. The server preserves immutable fields.",
		"Optimize for clarity, conversion intent, and mobile scan speed.",
		`Blocks: ${JSON.stringify(promptItems)}`,
	].join("\n");
	try {
		const raw = await generateWithProvider(prompt, {
			provider: aiConfig.provider,
			apiKey: aiConfig.apiKey,
			baseUrl: aiConfig.baseUrl,
			model: aiConfig.model,
			ideaCount: 20,
			useStructuredOutput: true,
			structuredOutputSchema: {
				type: "OBJECT",
				properties: {
					variants: {
						type: "ARRAY",
						items: {
							type: "OBJECT",
							properties: {
								blocks: { type: "ARRAY", items: { type: "OBJECT" } },
								reasoning: { type: "STRING" },
							},
							required: ["blocks", "reasoning"],
						},
					},
				},
				required: ["variants"],
			},
		});
		if (!raw) return null;
		const parsed = JSON.parse(raw) as {
			variants?:
				| Array<{
						blocks?: SmartLinkItem[] | undefined;
						reasoning?: string | undefined;
				  }>
				| undefined;
		};
		const originalById = new Map(items.map((item) => [item.id, item]));
		const variants = (parsed.variants ?? [])
			.slice(0, 3)
			.map((variant) => ({
				blocks: reconcileAiBlocks(
					Array.isArray(variant.blocks) ? variant.blocks : [],
					originalById,
				),
				reasoning: String(variant.reasoning ?? "AI suggested arrangement."),
			}))
			.filter((variant) => variant.blocks.length > 0);
		return variants.length ? variants : null;
	} catch (error) {
		logger.warn("[links] AI enhance failed; using deterministic fallback", {
			error: String(error),
		});
		return null;
	}
}

function truncateForPrompt(
	value: string | undefined,
	max: number,
): string | undefined {
	if (!value) return undefined;
	const trimmed = value.replace(/\s+/g, " ").trim();
	if (trimmed.length <= max) return trimmed;
	return `${trimmed.slice(0, max - 1)}...`;
}

function toPromptItem(item: SmartLinkItem): Record<string, unknown> {
	return {
		id: item.id,
		title: truncateForPrompt(item.title, MAX_AI_TEXT) ?? "",
		subtitle: truncateForPrompt(item.subtitle, MAX_AI_TEXT),
		urlHost: safeHost(item.url),
		clicks: item.clicks,
		blockType: truncateForPrompt(item.blockType, 40),
		metadataKeys: item.metadata
			? Object.keys(item.metadata).slice(0, 12)
			: undefined,
	};
}

function safeHost(url: string): string | undefined {
	try {
		return truncateForPrompt(new URL(url).hostname, MAX_AI_URL);
	} catch {
		return undefined;
	}
}

function reconcileAiBlocks(
	blocks: SmartLinkItem[],
	originalById: Map<string, SmartLinkItem>,
): SmartLinkItem[] {
	const seen = new Set<string>();
	const reconciled: SmartLinkItem[] = [];
	for (const block of blocks) {
		const original = originalById.get(String(block.id));
		if (!original || seen.has(original.id)) continue;
		seen.add(original.id);
		reconciled.push({
			...original,
			title:
				truncateForPrompt(String(block.title ?? original.title), MAX_AI_TEXT) ??
				original.title,
			subtitle:
				truncateForPrompt(
					String(block.subtitle ?? original.subtitle ?? ""),
					MAX_AI_TEXT,
				) ?? original.subtitle,
		});
	}
	return reconciled;
}

function smartLabel(item: SmartLinkItem): string {
	const base = item.title.trim() || "Untitled block";
	if (/limited|drop|sale|launch/i.test(base)) return `Limited drop · ${base}`;
	if (/newsletter|email|subscribe/i.test(base)) return "Get the newsletter";
	if (/tip|coffee|support/i.test(base)) return "Tip jar · support the work";
	if (/book|call|session|calendar/i.test(base)) return "Book a session";
	if (/essay|post|article|read/i.test(base)) return `New essay · ${base}`;
	return base.length > 32 ? base : `${base} · open now`;
}
