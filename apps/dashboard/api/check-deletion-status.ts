/**
 * Data Deletion Status Check
 * POST /api/check-deletion-status
 *
 * Public endpoint (no auth required) called by DeletionStatus.tsx
 * to check the status of a Meta-initiated data deletion request.
 * Returns { found, status, requestedAt, completedAt, message }.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import { logger } from "./_lib/logger.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./_lib/privilegedDb.js";
import { checkRateLimit } from "./_lib/rateLimiter.js";

const CONFIRMATION_CODE_PATTERN = /^[A-Za-z0-9_-]{16,128}$/;

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const ip =
		(req.headers["x-forwarded-for"] as string)?.split(",")[0]?.trim() ||
		"unknown";
	const rl = await checkRateLimit({
		key: `check-deletion:${ip}`,
		limit: 10,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Too many requests");
	}

	const { confirmationCode } = req.body || {};
	if (!confirmationCode || typeof confirmationCode !== "string") {
		return apiError(res, 400, "Missing confirmationCode");
	}
	if (!CONFIRMATION_CODE_PATTERN.test(confirmationCode)) {
		return apiError(res, 400, "Invalid confirmationCode");
	}

	try {
		const supabase = getPrivilegedSupabaseAny(
			PRIVILEGED_DB_REASONS.metaDeletionStatus,
		);
		// biome-ignore lint/suspicious/noExplicitAny: table not in generated types
		const { data: row, error } = await (supabase as any)
			.from("data_deletion_requests")
			.select("status, requested_at, completed_at, error_message")
			.eq("confirmation_code", confirmationCode)
			.maybeSingle();

		if (error) {
			logger.error("[check-deletion-status] DB error", {
				error: String(error),
			});
			return apiError(res, 500, "Internal error");
		}

		if (!row) {
			return apiSuccess(res, {
				found: false,
				message: "No deletion request found for this confirmation code.",
			});
		}

		const statusMessages: Record<string, string> = {
			pending:
				"Your data deletion request has been received and is queued for processing.",
			processing:
				"Your data is currently being deleted. This may take a few minutes.",
			completed: "Your data has been permanently deleted from our systems.",
			failed:
				"There was an issue processing your deletion. Please contact support.",
			no_data_found:
				"No data was found associated with your account. No deletion was needed.",
		};

		return apiSuccess(res, {
			found: true,
			status: row.status,
			requestedAt: row.requested_at,
			completedAt: row.completed_at,
			message: statusMessages[row.status] || "Unknown status.",
		});
	} catch (err) {
		logger.error("[check-deletion-status] Error", { error: String(err) });
		return apiError(res, 500, "Internal error");
	}
}
