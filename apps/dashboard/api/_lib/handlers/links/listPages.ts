import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getSupabase } from "../../supabase.js";
import { getUserTier, LINK_LIMITS } from "./shared.js";

export async function handleListPages(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const supabase = getSupabase();
	const { data, error } = await supabase
		.from("link_pages")
		.select("*, link_items(count)")
		.eq("user_id", userId)
		.order("created_at", { ascending: false });

	if (error) return apiError(res, 500, "Failed to list pages");

	const tier = await getUserTier(userId);
	const limits = LINK_LIMITS[tier];

	return apiSuccess(res, {
		pages: data || [],
		plan: { tier, ...limits },
	});
}
