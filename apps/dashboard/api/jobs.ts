/**
 * Jobs API Route — Thin Router
 * /api/jobs?action=<action>
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { authenticatedRouteError, getAuthUserOrError } from "./_lib/apiResponse.js";
import { getPublishJobStatus, processPublishJob } from "./_lib/publishJobs.js";
import { verifyQStashSignature } from "./_lib/qstash.js";
import { getOrCreateRequestId } from "./_lib/requestId.js";

export const config = { maxDuration: 300 };

export default async function handler(req: VercelRequest, res: VercelResponse) {
	getOrCreateRequestId(req, res);
	const action = (req.query.action as string) || "";
	switch (action) {
		case "export-worker":
			if (!(await verifyQStashSignature(req, res))) return;
			req.headers["upstash-signature-verified"] = "true";
			return (await import("./_lib/handlers/jobs/export-worker.js")).default(
				req,
				res,
			);
		case "publish-status": {
			if (req.method !== "GET") {
				return authenticatedRouteError(req, res, 405, "Method not allowed");
			}
			const user = await getAuthUserOrError(req, res);
			if (!user) return;
			return getPublishJobStatus(req, res, user.id);
		}
		case "publish-worker": {
			if (req.method !== "POST") {
				return res.status(405).json({ error: "Method not allowed" });
			}
			if (!(await verifyQStashSignature(req, res))) return;
			const jobId =
				typeof req.body?.jobId === "string" ? req.body.jobId : undefined;
			if (!jobId) return res.status(400).json({ error: "jobId is required" });
			const result = await processPublishJob(jobId);
			return res.status(200).json({ success: true, ...result });
		}
		default:
			return authenticatedRouteError(
				req,
				res,
				400,
				`Unknown action: ${action}`,
			);
	}
}
