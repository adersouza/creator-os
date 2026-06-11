/**
 * GDPR Export Status / Download — GET /api/user/export-status?jobId=X
 * Returns job status, or redirects to signed download URL when complete.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuthDb } from "../../middleware.js";

export default withAuthDb(async (req, res, context) => {
	const { user, userDb, adminDb } = context;
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const jobId = req.query.jobId as string;
	if (!jobId) return apiError(res, 400, "Missing jobId parameter");

	// biome-ignore lint/suspicious/noExplicitAny: Supabase type instantiation depth
	const { data: job, error } = await (userDb as any)
		.from("data_export_jobs")
		.select(
			"id, status, file_path, error_message, created_at, completed_at, expires_at",
		)
		.eq("id", jobId)
		.eq("user_id", user.id)
		.maybeSingle();

	if (error || !job) return apiError(res, 404, "Export job not found");

	if (job.status === "complete" && job.file_path) {
		// Check expiry
		if (job.expires_at && new Date(job.expires_at) < new Date()) {
			return apiError(
				res,
				410,
				"Export has expired. Please request a new one.",
			);
		}

		// Generate signed download URL (1 hour)
		const { data: signedUrl, error: signErr } = await adminDb.storage
			.from("exports")
			.createSignedUrl(job.file_path, 3600);

		if (signErr || !signedUrl) {
			return apiError(res, 500, "Failed to generate download link");
		}

		const download = req.query.download === "true";
		if (download) {
			return res.redirect(302, signedUrl.signedUrl);
		}

		return apiSuccess(res, {
			jobId: job.id,
			status: job.status,
			downloadUrl: signedUrl.signedUrl,
			expiresAt: job.expires_at,
		});
	}

	return apiSuccess(res, {
		jobId: job.id,
		status: job.status,
		errorMessage: job.error_message,
		createdAt: job.created_at,
	});
});
