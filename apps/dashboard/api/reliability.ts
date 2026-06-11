import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import { withAuth } from "./_lib/middleware.js";
import { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } from "./_lib/privilegedDb.js";
import { loadReliabilitySections, persistReliabilitySloSnapshot } from "./_lib/reliability.js";

export default withAuth(async (req: VercelRequest, res: VercelResponse, user) => {
	const action = String(req.query.action || "slo-summary");
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");
	if (action !== "slo-summary") return apiError(res, 404, "Unknown reliability action");

	const windowHours = Math.min(Math.max(Number(req.query.windowHours || 24), 1), 24 * 30);
	const db = getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.reliabilityTelemetry);
	const sections = await loadReliabilitySections(db, user.id, { windowHours });
	await persistReliabilitySloSnapshot(db, user.id, sections.reliabilitySlo);

	return apiSuccess(res, {
		generatedAt: new Date().toISOString(),
		windowHours,
		...sections,
	});
});
