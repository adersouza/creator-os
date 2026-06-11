import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { requireMinTier } from "../../../tierGate.js";
import { z } from "../../../zodCompat.js";
import { backfillAccountDnaForWorkspace } from "../accountDna.js";
import { resolveWorkspaceId, verifyWorkspaceAccess } from "./routeHelpers.js";

const BackfillAccountDnaSchema = z.object({
	workspaceId: z.string().min(1).optional().nullable(),
	force: z.boolean().optional(),
	dryRun: z.boolean().optional(),
	limit: z.number().int().min(1).max(1000).optional(),
});

export async function handleBackfillAccountDna(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;

	const parsed = BackfillAccountDnaSchema.safeParse(req.body || {});
	if (!parsed.success)
		return apiError(res, 400, "Invalid account DNA backfill payload");

	const workspaceId = await resolveWorkspaceId(
		parsed.data.workspaceId,
		userId,
		res,
	);
	if (!workspaceId) return;
	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	try {
		const result = await backfillAccountDnaForWorkspace({
			workspaceId,
			force: parsed.data.force,
			dryRun: parsed.data.dryRun,
			limit: parsed.data.limit,
		});
		return apiSuccess(res, {
			workspaceId,
			...result,
		});
	} catch (error) {
		const message = String(error);
		logger.error("Account DNA backfill failed", {
			workspaceId,
			userId,
			error: message,
		});
		if (
			message.includes("account_dna") ||
			message.includes("relation") ||
			message.includes("column")
		) {
			return apiError(res, 424, "Account DNA migration has not been applied");
		}
		return apiError(res, 500, "Failed to backfill account DNA");
	}
}
