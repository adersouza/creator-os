import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, badRequest, methodNotAllowed } from "../../apiResponse.js";
import { redactAIActionText } from "../auto-post/aiProviders.js";
import { withAuth } from "../../middleware.js";
import { getSupabaseAny } from "../../supabase.js";

export default withAuth(async (req: VercelRequest, res: VercelResponse, user) => {
	if (req.method !== "POST") return methodNotAllowed(res);
	const { account_id, action_type, input_text, output_text, model_used, provider, latency_ms, metadata } = req.body || {};
	if (!action_type || typeof action_type !== "string") return badRequest(res, "action_type is required");
	const { error } = await getSupabaseAny().from("ai_action_log").insert({
		user_id: user.id,
		account_id: account_id ?? null,
		surface: "composer",
		action_type,
		input_text: redactAIActionText(typeof input_text === "string" ? input_text : null),
		output_text: redactAIActionText(typeof output_text === "string" ? output_text : null),
		model_used: model_used ?? null,
		provider: provider ?? null,
		latency_ms: typeof latency_ms === "number" ? latency_ms : null,
		metadata: metadata ?? {},
	});
	if (error) return apiError(res, 500, "Failed to write AI action log", { details: error.message });
	return apiSuccess(res, { logged: true });
});
