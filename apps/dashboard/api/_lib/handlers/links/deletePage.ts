import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getSupabase } from "../../supabase.js";
import { DeletePageSchema, deleteFromCloudflareWithRetry } from "./shared.js";

export async function handleDeletePage(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const supabase = getSupabase();
	const parsed = DeletePageSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { pageId } = parsed.data;

	// Fetch slug before deleting (needed for Cloudflare KV cleanup)
	const { data: pageToDelete } = await supabase
		.from("link_pages")
		.select("slug")
		.eq("id", pageId)
		.eq("user_id", userId)
		.maybeSingle();
	if (!pageToDelete) return apiError(res, 404, "Page not found");

	const { error: deleteError } = await supabase
		.from("link_pages")
		.delete()
		.eq("id", pageId)
		.eq("user_id", userId);
	if (deleteError) return apiError(res, 500, "Failed to delete page");

	// Delete from Cloudflare KV (with retry)
	if (pageToDelete.slug) {
		await deleteFromCloudflareWithRetry(pageToDelete.slug);
	}

	return apiSuccess(res, {});
}
