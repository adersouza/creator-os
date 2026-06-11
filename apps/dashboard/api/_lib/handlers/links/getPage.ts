import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getSupabase } from "../../supabase.js";

export async function handleGetPage(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const supabase = getSupabase();
	const pageId = req.query.pageId as string;
	if (!pageId) return apiError(res, 400, "pageId required");

	const { data, error } = await supabase
		.from("link_pages")
		.select("*, link_items(*)")
		.eq("id", pageId)
		.eq("user_id", userId)
		.maybeSingle();

	if (error) return apiError(res, 404, "Page not found");
	if (!data) return apiError(res, 404, "Page not found");

	// Sort links by position
	if (data.link_items) {
		data.link_items.sort(
			(a: { position: number }, b: { position: number }) =>
				a.position - b.position,
		);
	}

	return apiSuccess(res, { page: data });
}
