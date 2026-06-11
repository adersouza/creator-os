import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getUserAIConfig } from "../../aiConfig.js";
import { checkAIRateLimit } from "../../aiRateLimit.js";
import { apiError, apiSuccess, badRequest, methodNotAllowed } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { requireMinTier } from "../../tierGate.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";

export default withAuth(async (req: VercelRequest, res: VercelResponse, user) => {
	if (req.method !== "POST") return methodNotAllowed(res);
	const { caption, account_id } = req.body || {};
	if (!caption || typeof caption !== "string") return badRequest(res, "caption is required");
	if (!(await requireMinTier(user.id, "pro", res))) return;
	const rl = await checkAIRateLimit(user.id, "composer-critique");
	res.setHeader("X-RateLimit-Limit", String(rl.limit));
	res.setHeader("X-RateLimit-Remaining", String(rl.remaining));
	if (!rl.allowed) return apiError(res, 429, "AI rate limit exceeded. Try again shortly.");
	const aiConfig = await getUserAIConfig(user.id);
	if (!aiConfig) return apiError(res, 503, "AI is not configured", { code: "NO_API_KEY" });
	const prompt = [
		"COMPOSER_CRITIQUE_JUDGE",
		"Score this social post for likely engagement. Return JSON only:",
		"{score:number,predicted_likes:number,predicted_replies:number,reasoning:[{type:'positive'|'warning'|'tip',text:string}]}",
		`Account: ${account_id ?? "generic"}`,
		"Caption:",
		caption,
	].join("\n");
	try {
		const raw = await generateWithProvider(prompt, {
			provider: aiConfig.provider,
			model: aiConfig.model,
			apiKey: aiConfig.apiKey,
			baseUrl: aiConfig.baseUrl,
			ideaCount: 1,
			actionLog: {
				userId: user.id,
				accountId: typeof account_id === "string" ? account_id : null,
				surface: "composer",
				actionType: "critique",
				inputText: caption,
			},
		});
		return apiSuccess(res, parseCritique(raw ?? "", caption));
	} catch (error) {
		return apiError(res, 500, "Failed to critique caption", { details: error instanceof Error ? error.message : String(error) });
	}
});

function parseCritique(raw: string, caption: string) {
	try {
		const cleaned = raw.replace(/^```json\s*/i, "").replace(/```$/i, "").trim();
		const parsed = JSON.parse(cleaned);
		return {
			score: clamp(parsed.score, 0, 100),
			predicted_likes: clamp(parsed.predicted_likes, 0, 1_000_000),
			predicted_replies: clamp(parsed.predicted_replies, 0, 1_000_000),
			reasoning: Array.isArray(parsed.reasoning) ? parsed.reasoning.slice(0, 5) : [],
		};
	} catch {
		const score = Math.max(35, Math.min(82, 45 + Math.round(caption.length / 12)));
		return {
			score,
			predicted_likes: Math.round(score * 2.4),
			predicted_replies: Math.round(score * 0.18),
			reasoning: [
				{ type: "tip", text: "Add a sharper first line if this is meant to stop the scroll." },
			],
		};
	}
}

function clamp(value: unknown, min: number, max: number) {
	const n = Number(value);
	if (!Number.isFinite(n)) return min;
	return Math.max(min, Math.min(max, Math.round(n)));
}
