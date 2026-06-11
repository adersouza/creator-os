import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
import { ReorderSchema, syncWithRetry } from "./shared.js";

export async function handleReorderLinks(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const supabase = getSupabase();
	const parsed = ReorderSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { pageId, linkIds } = parsed.data;

	// Verify ownership
	const { data: page } = await supabase
		.from("link_pages")
		.select("id")
		.eq("id", pageId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!page) return apiError(res, 404, "Page not found");

	// Verify all linkIds belong to this page
	const { data: existingLinks } = await supabase
		.from("link_items")
		.select("id")
		.eq("page_id", pageId);

	const validIds = new Set(
		(existingLinks || []).map((l: { id: string }) => l.id),
	);
	const allValid = linkIds.every((id) => validIds.has(id));
	if (!allValid) {
		return apiError(
			res,
			400,
			"One or more link IDs do not belong to this page",
		);
	}

	// Batch upsert all position updates atomically
	const updates = linkIds.map((id, i) => ({
		id,
		page_id: pageId,
		position: i,
	}));
	const { error: upsertError } = await getSupabaseAny()
		.from("link_items")
		.upsert(updates, { onConflict: "id" });

	if (upsertError) {
		logger.error("[links] Reorder upsert failed", {
			error: String(upsertError),
		});
		return apiError(res, 500, "Failed to reorder links");
	}

	// Sync page to Cloudflare KV after reorder (with retry)
	await syncWithRetry(supabase, pageId);
	return apiSuccess(res, {});
}
