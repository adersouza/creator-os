/**
 * QStash Delayed Cross-Reply Endpoint
 *
 * Called by QStash 30-60s after a successful autoposter publish.
 * A different account in the same group replies to the post,
 * simulating organic engagement.
 *
 * POST /api/cross-reply-publish
 * Auth: QStash signature verification
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { logger } from "./_lib/logger.js";
import { verifyQStashSignature } from "./_lib/qstash.js";
import { z } from "./_lib/zodCompat.js";

const CrossReplyBodySchema = z.object({
	queueItemId: z.string().min(1),
	workspaceId: z.string().min(1),
	groupId: z.string().min(1),
	ownerId: z.string().min(1),
	targetAccountId: z.string().min(1),
	targetThreadsPostId: z.string().min(1),
	postContent: z.string().default(""),
});

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") {
		const { apiError } = await import("./_lib/apiResponse.js");
		return apiError(res, 405, "Method not allowed");
	}

	if (!(await verifyQStashSignature(req, res))) return;

	const parsed = CrossReplyBodySchema.safeParse(req.body);
	if (!parsed.success) {
		return res
			.status(400)
			.json({ ok: false, skipped: true, reason: "invalid_body" });
	}

	try {
		const { executeCrossReply } = await import("./_lib/crossReplyPublisher.js");
		const result = await executeCrossReply(parsed.data);

		logger.info("[cross-reply-publish] Done", {
			queueItemId: parsed.data.queueItemId,
			success: result.success,
			replier: result.replierAccountId,
			error: result.error,
		});

		return res.status(200).json({ ok: true, ...result });
	} catch (err) {
		const errMsg = err instanceof Error ? err.message : String(err);
		logger.warn("[cross-reply-publish] Unhandled error", { error: errMsg });
		// Report to Sentry so failures are visible in monitoring
		import("./_lib/sentryServer.js")
			.then(({ captureServerException }) =>
				captureServerException(err, { handler: "cross-reply-publish" }),
			)
			.catch(() => {});
		return res.status(200).json({ ok: true, error: errMsg });
	}
}
