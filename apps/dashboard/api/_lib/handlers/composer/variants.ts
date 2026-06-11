import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database, Json } from "../../../../types/supabase.js";
import { getUserAIConfig } from "../../aiConfig.js";
import { apiError, apiSuccess, badRequest, methodNotAllowed } from "../../apiResponse.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";
import type { DbContext } from "../../dbContext.js";
import { withAuthDb } from "../../middleware.js";
import { checkAIRateLimit } from "../../aiRateLimit.js";
import { requireMinTier } from "../../tierGate.js";

type UserDb = DbContext["userDb"];
type PostVariantInsert = Database["public"]["Tables"]["post_variants"]["Insert"];

const LABELS = ["A", "B", "C"] as const;
const TYPES = ["hook", "pov", "listicle", "question", "story"] as const;

export default withAuthDb(async (req: VercelRequest, res: VercelResponse, context) => {
	const { user, userDb } = context;
	if (req.method === "GET") {
		const mode = String(req.query.mode ?? "list");
		if (mode === "live-results") return liveResults(req, res, userDb, user.id);
		const draftId = String(req.query.draft_id ?? "");
		if (!draftId) return badRequest(res, "draft_id is required");
		const { data, error } = await userDb.from("post_variants").select("*").eq("user_id", user.id).eq("draft_id", draftId).order("variant_label");
		if (error) return apiError(res, 500, "Failed to list variants", { details: error.message });
		return apiSuccess(res, { variants: data ?? [] });
	}

	if (req.method !== "POST") return methodNotAllowed(res);
	const { mode = "generate" } = req.body || {};
	if (mode === "promote") {
		const { id } = req.body || {};
		if (!id || typeof id !== "string") return badRequest(res, "id is required");
		const { data, error } = await userDb.from("post_variants").update({ promoted_at: new Date().toISOString() }).eq("id", id).eq("user_id", user.id).select("*").maybeSingle();
		if (error) return apiError(res, 500, "Failed to promote variant", { details: error.message });
		return apiSuccess(res, { variant: data });
	}

	const { caption, account_id, persona, draft_id } = req.body || {};
	if (!caption || typeof caption !== "string") return badRequest(res, "caption is required");
	if (!(await requireMinTier(user.id, "pro", res))) return;
	const rl = await checkAIRateLimit(user.id, "composer-variants");
	res.setHeader("X-RateLimit-Limit", String(rl.limit));
	res.setHeader("X-RateLimit-Remaining", String(rl.remaining));
	if (!rl.allowed) return apiError(res, 429, "AI rate limit exceeded. Try again shortly.");
	const aiConfig = await getUserAIConfig(user.id);
	if (!aiConfig) return apiError(res, 503, "AI is not configured", { code: "NO_API_KEY" });
	const prompt = [
		"VARIANTS_GENERATOR",
		"Create exactly 3 social post variants as JSON array.",
		"Each item: {content, variant_type, predicted_score, predicted_confidence, reasoning_json}.",
		"Labels are assigned A/B/C by the caller. Return only JSON.",
		`Persona: ${persona ?? "default"}`,
		`Account: ${account_id ?? "generic"}`,
		"Caption:",
		caption,
	].join("\n");
	const raw = await generateWithProvider(prompt, {
		provider: aiConfig.provider,
		model: aiConfig.model,
		apiKey: aiConfig.apiKey,
		baseUrl: aiConfig.baseUrl,
		ideaCount: 3,
		actionLog: {
			userId: user.id,
			accountId: typeof account_id === "string" ? account_id : null,
			surface: "composer",
			actionType: "variants_generate",
			inputText: caption,
			metadata: { persona: persona ?? "default", draftId: draft_id ?? null },
		},
	});
	const parsed = parseVariants(raw ?? "", caption);
	const rows = parsed.slice(0, 3).map((item, index) => {
		const variantType = TYPES.includes(item.variant_type as never)
			? (item.variant_type as (typeof TYPES)[number])
			: "hook";
		return {
			user_id: user.id,
			draft_id: draft_id ?? `draft-${Date.now()}`,
			variant_label: LABELS[index] ?? "A",
			content: item.content,
			variant_type: variantType,
			predicted_score: clampInt(item.predicted_score, 55, 95),
			predicted_confidence: Math.max(0.1, Math.min(0.99, Number(item.predicted_confidence ?? 0.72))),
			reasoning_json: (item.reasoning_json ?? {}) as Json,
		};
	}) satisfies PostVariantInsert[];
	const { data, error } = await userDb.from("post_variants").insert(rows).select("*");
	if (error) return apiError(res, 500, "Failed to save variants", { details: error.message });
	return apiSuccess(res, { variants: data ?? [] }, 201);
});

async function liveResults(req: VercelRequest, res: VercelResponse, userDb: UserDb, userId: string) {
	const postId = String(req.query.post_id ?? "");
	if (!postId) return badRequest(res, "post_id is required");
	const { data } = await userDb.from("post_metric_history").select("views_count, likes_count, replies_count").eq("post_id", postId).order("snapshot_at", { ascending: false }).limit(1).maybeSingle();
	const views = Number(data?.views_count ?? 0);
	const engagement = views > 0 ? (Number(data?.likes_count ?? 0) + Number(data?.replies_count ?? 0)) / views : 0;
	await userDb.from("post_variants").update({ live_views_count: views, live_engagement_rate: engagement }).eq("post_id", postId).eq("user_id", userId);
	return apiSuccess(res, { post_id: postId, live_views_count: views, live_engagement_rate: engagement });
}

function parseVariants(raw: string, caption: string): Array<Record<string, unknown> & { content: string }> {
	try {
		const cleaned = raw.replace(/^```json\s*/i, "").replace(/```$/i, "").trim();
		const parsed = JSON.parse(cleaned);
		if (Array.isArray(parsed)) return parsed.filter((item) => typeof item?.content === "string");
		if (Array.isArray(parsed?.variants)) return parsed.variants.filter((item: { content?: unknown | undefined }) => typeof item?.content === "string");
	} catch {}
	return [
		{ content: caption, variant_type: "hook", predicted_score: 70, predicted_confidence: 0.6, reasoning_json: { fallback: true } },
		{ content: `${caption}\n\nWhat would you add?`, variant_type: "question", predicted_score: 68, predicted_confidence: 0.55, reasoning_json: { fallback: true } },
		{ content: caption.split("\n").reverse().join("\n"), variant_type: "pov", predicted_score: 62, predicted_confidence: 0.5, reasoning_json: { fallback: true } },
	];
}

function clampInt(value: unknown, min: number, max: number) {
	const n = Number(value);
	if (!Number.isFinite(n)) return min;
	return Math.max(min, Math.min(max, Math.round(n)));
}
