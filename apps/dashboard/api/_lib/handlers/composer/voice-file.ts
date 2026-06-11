import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database, Json } from "../../../../types/supabase.js";
import { apiError, apiSuccess, badRequest, methodNotAllowed } from "../../apiResponse.js";
import { withAuthDb } from "../../middleware.js";

type VoiceContextFileInsert =
	Database["public"]["Tables"]["voice_context_files"]["Insert"];

export default withAuthDb(async (req: VercelRequest, res: VercelResponse, { user, userDb }) => {
	const groupId = String(req.query.account_group_id ?? req.body?.account_group_id ?? "");
	if (!groupId) return badRequest(res, "account_group_id is required");
	const group = await userDb.from("account_groups").select("id, user_id, voice_profile").eq("id", groupId).eq("user_id", user.id).maybeSingle();
	if (group.error) return apiError(res, 500, "Failed to fetch account group", { details: group.error.message });
	if (!group.data) return apiError(res, 404, "Account group not found");

	if (req.method === "GET") {
		const existing = await userDb.from("voice_context_files").select("*").eq("account_group_id", groupId).eq("user_id", user.id).maybeSingle();
		if (existing.error) return apiError(res, 500, "Failed to fetch voice file", { details: existing.error.message });
		if (existing.data) return apiSuccess(res, { voice_file: existing.data });
		const content = group.data?.voice_profile ? JSON.stringify(group.data.voice_profile, null, 2) : "";
		return apiSuccess(res, { voice_file: { account_group_id: groupId, user_id: user.id, content, version: 1, top_patterns: [] } });
	}

	if (req.method !== "PUT") return methodNotAllowed(res);
	const { content, banned_patterns, audience, top_patterns } = req.body || {};
	if (typeof content !== "string") return badRequest(res, "content is required");
	const payload: VoiceContextFileInsert = {
		account_group_id: groupId,
		user_id: user.id,
		content,
		banned_patterns: Array.isArray(banned_patterns) ? banned_patterns : null,
		audience: typeof audience === "string" ? audience : null,
		top_patterns: Array.isArray(top_patterns) ? (top_patterns as Json) : [],
		last_edited_at: new Date().toISOString(),
	};
	const { data, error } = await userDb.from("voice_context_files").upsert(payload, { onConflict: "account_group_id" }).select("*").maybeSingle();
	if (error) return apiError(res, 500, "Failed to save voice file", { details: error.message });
	return apiSuccess(res, { voice_file: data });
});
