import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../../apiResponse.js";
import { requireMinTier } from "../../../tierGate.js";
import {
	drainAutoposterQueue,
	getAutoposterControlStatus,
	pauseAutoposter,
	resumeAutoposterWarmup,
} from "../controlPlane.js";
import {
	resolveWorkspaceId,
	verifyWorkspaceAccess,
	verifyWorkspaceWriteAccess,
} from "./routeHelpers.js";

export async function handleAutoposterControlStatus(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;
	const workspaceId = await resolveWorkspaceId(
		req.body?.workspaceId,
		userId,
		res,
	);
	if (!workspaceId) return;
	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;

	const status = await getAutoposterControlStatus(workspaceId);
	return apiSuccess(res, { status });
}

export async function handleAutoposterControlPause(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;
	const workspaceId = await resolveWorkspaceId(
		req.body?.workspaceId,
		userId,
		res,
	);
	if (!workspaceId) return;
	if (!(await verifyWorkspaceWriteAccess(userId, workspaceId, res))) return;
	const reason = String(req.body?.reason ?? "").trim();
	if (!reason) return apiError(res, 400, "reason required");

	const result = await pauseAutoposter(workspaceId, {
		reason,
		apply: req.body?.apply === true,
		actor: userId,
	});
	return apiSuccess(res, { result });
}

export async function handleAutoposterControlResumeWarmup(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;
	const workspaceId = await resolveWorkspaceId(
		req.body?.workspaceId,
		userId,
		res,
	);
	if (!workspaceId) return;
	if (!(await verifyWorkspaceWriteAccess(userId, workspaceId, res))) return;
	const reason = String(req.body?.reason ?? "").trim();
	if (!reason) return apiError(res, 400, "reason required");

	const result = await resumeAutoposterWarmup(workspaceId, {
		reason,
		apply: req.body?.apply === true,
		actor: userId,
	});
	return apiSuccess(res, { result });
}

export async function handleAutoposterControlDrain(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (!(await requireMinTier(userId, "empire", res))) return;
	const workspaceId = await resolveWorkspaceId(
		req.body?.workspaceId,
		userId,
		res,
	);
	if (!workspaceId) return;
	if (!(await verifyWorkspaceWriteAccess(userId, workspaceId, res))) return;
	const reason = String(req.body?.reason ?? "").trim();
	if (!reason) return apiError(res, 400, "reason required");
	if (req.body?.mode !== "cancel-ready") {
		return apiError(res, 400, "mode must be cancel-ready");
	}

	const result = await drainAutoposterQueue(workspaceId, {
		reason,
		mode: "cancel-ready",
		apply: req.body?.apply === true,
		includeManual: req.body?.includeManual === true,
		actor: userId,
	});
	return apiSuccess(res, { result });
}
