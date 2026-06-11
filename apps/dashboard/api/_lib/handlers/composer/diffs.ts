import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, badRequest, methodNotAllowed } from "../../apiResponse.js";
import { withAuthDb } from "../../middleware.js";

export default withAuthDb(async (req: VercelRequest, res: VercelResponse, context) => {
	const { user, userDb } = context;
	if (req.method === "GET") {
		const draftId = String(req.query.draft_id ?? "");
		if (!draftId) return badRequest(res, "draft_id is required");
		const { data, error } = await userDb.from("post_channel_diffs").select("*").eq("user_id", user.id).eq("draft_id", draftId).order("created_at", { ascending: false });
		if (error) return apiError(res, 500, "Failed to fetch diffs", { details: error.message });
		return apiSuccess(res, { diffs: data ?? [] });
	}
	if (req.method !== "POST") return methodNotAllowed(res);
	const { id, draft_id, platform, master_caption, variant_caption, status } = req.body || {};
	if (status && id) {
		const { data, error } = await userDb.from("post_channel_diffs").update({ status, resolved_at: new Date().toISOString() }).eq("id", id).eq("user_id", user.id).select("*").maybeSingle();
		if (error) return apiError(res, 500, "Failed to update diff", { details: error.message });
		return apiSuccess(res, { diff: data });
	}
	if (!draft_id || !platform || !master_caption || !variant_caption) return badRequest(res, "draft_id, platform, master_caption, variant_caption are required");
	const { data, error } = await userDb.from("post_channel_diffs").insert({
		user_id: user.id,
		draft_id,
		platform,
		divergence_type: "custom",
		master_caption,
		variant_caption,
		status: "unresolved",
	}).select("*").maybeSingle();
	if (error) return apiError(res, 500, "Failed to create diff", { details: error.message });
	return apiSuccess(res, { diff: data }, 201);
});
