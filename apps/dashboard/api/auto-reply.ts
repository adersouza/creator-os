/**
 * Auto-Reply endpoint — handles QStash-dispatched self-comments.
 *
 * Called by auto-post-publish.ts with a 15s delay to avoid Threads API
 * propagation race condition ("resource does not exist").
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "./_lib/zodCompat.js";

export const config = { maxDuration: 30 };

// QStash signature is the primary guard — it covers the body bytes, so a
// payload can't be tampered with mid-flight. This Zod schema is defense in
// depth: clamps shapes (no oversized comments, no unexpected fields driving
// downstream Meta API calls) and produces a uniform 400 on contract drift.
const SelfCommentPayloadSchema = z.object({
	action: z.literal("self-comment"),
	accountId: z.string().min(1).max(128),
	threadId: z.string().min(1).max(128),
	// Threads cap on post body is 500 chars; cap input slightly higher to
	// account for trim/normalize but reject anything pathological.
	comment: z.string().min(1).max(1000),
	queueItemId: z.string().min(1).max(128).optional(),
});

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyQStashSignature } = await import("./_lib/qstash.js");
	if (!(await verifyQStashSignature(req, res))) return;

	const { logger } = await import("./_lib/logger.js");
	const { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } = await import(
		"./_lib/privilegedDb.js"
	);
	const db = getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.autoReplyWorker);

	const parsed = SelfCommentPayloadSchema.safeParse(req.body);
	if (!parsed.success) {
		logger.warn("[auto-reply] Payload schema rejected", {
			issues: parsed.error.issues.map((i) => i.message),
		});
		return res.status(400).json({ error: "Invalid payload" });
	}
	const { accountId, threadId, comment, queueItemId } = parsed.data;

	try {
		const { data: account } = await db
			.from("accounts")
			.select("threads_access_token_encrypted, threads_user_id")
			.eq("id", accountId)
			.maybeSingle();

		if (!account?.threads_access_token_encrypted) {
			logger.warn("[auto-reply] Account not found or no token", { accountId });
			return res.status(200).json({ ok: true, skipped: "no_token" });
		}

		const { sendThreadsReply } = await import("./_lib/autoReplyEngine.js");
		const sent = await sendThreadsReply(
			account.threads_access_token_encrypted,
			account.threads_user_id,
			threadId,
			comment,
		);

		if (!sent) {
			logger.warn(
				"[auto-reply] Self-comment failed (sendThreadsReply returned false)",
				{ queueItemId, accountId, threadId },
			);
			return res.status(200).json({ ok: true, skipped: "send_failed" });
		}

		logger.info("[auto-reply] Self-comment posted", {
			queueItemId,
			accountId,
			comment,
		});
		return res.status(200).json({ ok: true });
	} catch (err) {
		logger.warn("[auto-reply] Self-comment failed", {
			error: err instanceof Error ? err.message : String(err),
			accountId,
			threadId,
		});
		// Return 200 so QStash doesn't retry — self-comments are best-effort
		return res.status(200).json({ ok: true, error: String(err) });
	}
}
