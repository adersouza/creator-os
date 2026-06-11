import { apiError, apiSuccess } from "../../apiResponse.js";
import { logAudit } from "../../auditLog.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { getRequiredAppBaseUrl } from "../../qstashDefaults.js";
import { checkRateLimit } from "../../rateLimiter.js";

export default withAuthDb(async (req, res, context) => {
	const { user, userDb } = context;
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const rl = await checkRateLimit({
		key: `user-export:${user.id}`,
		limit: 5,
		windowSeconds: 3600,
		failMode: "closed",
	});
	if (!rl.allowed) {
		return apiError(
			res,
			429,
			"Too many export requests. Please wait before retrying.",
		);
	}

	const userId = user.id;

	try {
		// Create export job
		// biome-ignore lint/suspicious/noExplicitAny: Supabase type instantiation depth
		const { data: job, error: insertErr } = await (userDb as any)
			.from("data_export_jobs")
			.insert({ user_id: userId, status: "pending" })
			.select("id")
			.single();

		if (insertErr || !job) {
			logger.error("[user/export] Failed to create export job", {
				error: String(insertErr),
			});
			return apiError(res, 500, "Failed to initiate export");
		}

		// Dispatch to background worker via QStash
		try {
			const { getQStashClient } = await import("../../qstash.js");
			const qstash = getQStashClient();
			await qstash.publishJSON({
				url: `${getRequiredAppBaseUrl()}/api/jobs/export-worker`,
				body: { jobId: job.id, userId },
				retries: 2,
			});
		} catch (qErr) {
			// If QStash dispatch fails, mark job as failed
			// biome-ignore lint/suspicious/noExplicitAny: Supabase type instantiation depth
			await (userDb as any)
				.from("data_export_jobs")
				.update({
					status: "failed",
					error_message: "Failed to dispatch worker",
				})
				.eq("id", job.id)
				.eq("user_id", userId);
			logger.error("[user/export] QStash dispatch failed", {
				error: String(qErr),
			});
			return apiError(res, 500, "Failed to initiate export");
		}

		await logAudit(userId, "user.data_export_requested", { req });

		return apiSuccess(
			res,
			{
				jobId: job.id,
				status: "pending",
				message: "Export started. You will be notified when ready.",
			},
			202,
		);
	} catch (error) {
		logger.error("[user/export] Failed", { userId, error: String(error) });
		return apiError(res, 500, "Failed to initiate export");
	}
});
