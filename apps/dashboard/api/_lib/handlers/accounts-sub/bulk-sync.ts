import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, methodNotAllowed } from "../../apiResponse.js";
import { getSupabaseAny } from "../../supabase.js";

export default async function bulkSyncAccounts(
	req: VercelRequest,
	res: VercelResponse,
	user: { id: string },
) {
	if (req.method !== "POST") return methodNotAllowed(res);
	const body =
		typeof req.body === "object" && req.body !== null
			? (req.body as { accountIds?: unknown | undefined })
			: {};
	const accountIds = Array.isArray(body.accountIds)
		? body.accountIds.filter((id): id is string => typeof id === "string")
		: [];
	if (accountIds.length === 0) return apiError(res, 400, "accountIds is required");

	const db = getSupabaseAny();
	const now = new Date().toISOString();
	const [threadsRes, instagramRes] = await Promise.all([
		db
			.from("accounts")
			.update({ last_synced_at: now, updated_at: now })
			.eq("user_id", user.id)
			.in("id", accountIds),
		db
			.from("instagram_accounts")
			.update({ last_synced_at: now, updated_at: now })
			.eq("user_id", user.id)
			.in("id", accountIds),
	]);

	if (threadsRes.error) throw threadsRes.error;
	if (instagramRes.error) throw instagramRes.error;

	return apiSuccess(res, { updatedAt: now, accountIds });
}
