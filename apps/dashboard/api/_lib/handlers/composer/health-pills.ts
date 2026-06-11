import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, badRequest, methodNotAllowed } from "../../apiResponse.js";
import { withAuthDb } from "../../middleware.js";

export default withAuthDb(async (req: VercelRequest, res: VercelResponse, { user, userDb }) => {
	if (req.method !== "GET") return methodNotAllowed(res);
	const ids = String(req.query.account_ids ?? "")
		.split(",")
		.map((id) => id.trim())
		.filter(Boolean);
	if (ids.length === 0) return apiSuccess(res, { accounts: [] });
	if (ids.length > 50) return badRequest(res, "account_ids max 50");

	const owned = await userDb.from("accounts").select("id").eq("user_id", user.id).in("id", ids);
	if (owned.error) return apiError(res, 500, "Failed to verify accounts", { details: owned.error.message });
	const ownedIds = (owned.data ?? []).map((row: { id: string }) => row.id);
	if (ownedIds.length === 0) return apiSuccess(res, { accounts: [] });

	const { data, error } = await userDb
		.from("account_health_signals")
		.select("account_id, signal_type, severity, detected_at")
		.in("account_id", ownedIds)
		.is("resolved_at", null)
		.order("detected_at", { ascending: false });
	if (error) return apiError(res, 500, "Failed to fetch health signals", { details: error.message });

	const grouped = new Map<string, Array<{ signal_type: string; severity: string }>>();
	for (const row of data ?? []) {
		const accountId = String(row.account_id);
		const group = grouped.get(accountId) ?? [];
		group.push({ signal_type: String(row.signal_type), severity: String(row.severity) });
		grouped.set(accountId, group);
	}

	return apiSuccess(res, {
		accounts: ownedIds.map((accountId) => ({
			account_id: accountId,
			signals: grouped.get(accountId) ?? [],
		})),
	});
});
