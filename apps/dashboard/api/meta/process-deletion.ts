/**
 * Meta Data Deletion Processor
 * POST /api/meta/process-deletion
 *
 * QStash-triggered endpoint that runs the actual cascade deletion
 * after Meta's data-deletion callback stores the request.
 *
 * Skips Stripe cancellation and Meta token revocation (tokens already
 * cleared by the callback, and Meta already knows about the deletion).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { logger } from "../_lib/logger.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { verifyQStashSignature } from "../_lib/qstash.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	if (!(await verifyQStashSignature(req, res))) return;

	const { confirmationCode, userId: hintedUserId, metaUserId: hintedMetaUserId } =
		req.body || {};
	if (!confirmationCode) {
		return apiError(res, 400, "Missing confirmationCode");
	}

	const supabase = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.metaDeletionProcessor,
	);
	const { data: deletionRequest, error: requestError } = await supabase
		.from("data_deletion_requests")
		.select("confirmation_code, user_id, meta_user_id, status")
		.eq("confirmation_code", confirmationCode)
		.maybeSingle();
	if (requestError || !deletionRequest) {
		logger.warn("[process-deletion] Deletion request not found", {
			confirmationCode,
			error: requestError ? String(requestError.message || requestError) : null,
		});
		return apiError(res, 404, "Deletion request not found");
	}
	const userId = deletionRequest.user_id as string | null;
	const metaUserId = deletionRequest.meta_user_id as string | null;
	if (!userId || !metaUserId) {
		return apiError(res, 400, "Deletion request is missing required identity");
	}
	if (
		(hintedUserId && hintedUserId !== userId) ||
		(hintedMetaUserId && hintedMetaUserId !== metaUserId)
	) {
		logger.warn("[process-deletion] Body identity mismatch", {
			confirmationCode,
			bodyUserId: hintedUserId ?? null,
			rowUserId: userId,
			bodyMetaUserId: hintedMetaUserId ?? null,
			rowMetaUserId: metaUserId,
		});
		return apiError(res, 403, "Deletion request identity mismatch");
	}

	// Update status to processing
	await supabase
		.from("data_deletion_requests")
		.update({ status: "processing" })
		.eq("confirmation_code", confirmationCode);

	try {
		logger.info("[process-deletion] Starting cascade", {
			userId,
			metaUserId,
			confirmationCode,
		});

		// Import and run the shared cascade
		const { cascadeDeleteUserData, deleteAuthUser } = await import(
			"../_lib/handlers/user/deletionCascade.js"
		);

		await cascadeDeleteUserData(userId);
		await deleteAuthUser(userId);

		// Mark as completed
		await supabase
			.from("data_deletion_requests")
			.update({
				status: "completed",
				completed_at: new Date().toISOString(),
			})
			.eq("confirmation_code", confirmationCode);

		logger.info("[process-deletion] Cascade complete", {
			userId,
			confirmationCode,
		});
		return apiSuccess(res, { deleted: true });
	} catch (err) {
		const errorMsg = err instanceof Error ? err.message : String(err);
		logger.error("[process-deletion] Cascade failed", {
			userId,
			confirmationCode,
			error: errorMsg,
		});

		// Mark as failed
		await supabase
			.from("data_deletion_requests")
			.update({
				status: "failed",
				error_message: errorMsg.slice(0, 500),
			})
			.eq("confirmation_code", confirmationCode);

		// Return 500 so QStash retries
		return apiError(res, 500, "Deletion failed");
	}
}
