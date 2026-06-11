import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getSupabase } from "../../supabase.js";
import { DeleteLinkSchema, syncWithRetry } from "./shared.js";

export async function handleDeleteLink(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const supabase = getSupabase();
	const parsed = DeleteLinkSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { linkId } = parsed.data;

	const { data: link } = await supabase
		.from("link_items")
		.select("page_id")
		.eq("id", linkId)
		.maybeSingle();

	if (!link) return apiError(res, 404, "Link not found");
	if (!link.page_id) return apiError(res, 500, "Link missing page reference");

	const { data: page } = await supabase
		.from("link_pages")
		.select("id")
		.eq("id", link.page_id)
		.eq("user_id", userId)
		.maybeSingle();

	if (!page) return apiError(res, 403, "Not authorized");

	const { error: deleteError } = await supabase
		.from("link_items")
		.delete()
		.eq("id", linkId);
	if (deleteError) return apiError(res, 500, "Failed to delete link");

	// Sync page to Cloudflare KV after deleting link (with retry)
	await syncWithRetry(supabase, link.page_id);
	return apiSuccess(res, {});
}
