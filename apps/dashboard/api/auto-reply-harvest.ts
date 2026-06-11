/**
 * QStash Targeted Reply Harvest Endpoint
 *
 * Called by QStash exactly 15 minutes after a post publishes to harvest
 * comments and generate replies for that specific post.
 * Research: 15-min reply speed = 391% higher conversion.
 *
 * Auth: QStash signature verification (not user auth).
 * Idempotent: if the cron already harvested this post, this is a no-op.
 *
 * POST /api/auto-reply-harvest
 * Body: { queueItemId, workspaceId, groupId, ownerId, accountId, postId, sourceTable? }
 * Ownership fields are legacy payload fields; the handler re-derives them from
 * the source queue/post row before harvesting.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { logger } from "./_lib/logger.js";
import { verifyQStashSignature } from "./_lib/qstash.js";
import { z, zEnum } from "./_lib/zodCompat.js";

export const config = { maxDuration: 30 };

const HarvestBodySchema = z.object({
	queueItemId: z.string().min(1),
	workspaceId: z.string().min(1),
	groupId: z.string().min(1),
	ownerId: z.string().min(1),
	accountId: z.string().min(1),
	postId: z.string().min(1),
	sourceTable: zEnum(["auto_post_queue", "posts"]).optional(),
});

interface HarvestTarget {
	queueItemId: string;
	postId: string;
	workspaceId: string;
	groupId: string;
	ownerId: string;
	accountId: string;
	alreadyHarvested: boolean;
}

interface DbResult<T> {
	data: T | null;
	error?: { message?: string } | null;
}

interface QueryBuilder<T = Record<string, unknown>> {
	select(columns: string): QueryBuilder<T>;
	eq(field: string, value: unknown): QueryBuilder<T>;
	contains(field: string, value: unknown[]): QueryBuilder<T>;
	maybeSingle(): Promise<DbResult<T>>;
}

interface SupabaseLike {
	from(table: string): QueryBuilder;
}

export default async function handler(
	req: VercelRequest,
	res: VercelResponse,
): Promise<void> {
	if (req.method !== "POST") {
		const { apiError } = await import("./_lib/apiResponse.js");
		apiError(res, 405, "Method not allowed");
		return;
	}

	if (!(await verifyQStashSignature(req, res))) return;

	const parsed = HarvestBodySchema.safeParse(req.body);
	if (!parsed.success) {
		res.status(400).json({ ok: false, skipped: true, reason: "invalid_body" });
		return;
	}

	const { queueItemId, postId, sourceTable = "auto_post_queue" } = parsed.data;

	try {
		// Re-derive ownership/scope from the source row. Do not trust the QStash
		// body for account/group/workspace ownership, because the body is an
		// external delivery envelope rather than the source of truth.
		const { getSupabaseAny } = await import("./_lib/supabase.js");
		const target = await resolveHarvestTarget(
			getSupabaseAny(),
			sourceTable,
			queueItemId,
			postId,
		);
		if (!target) {
			res.status(200).json({ ok: true, skipped: true, reason: "not_found" });
			return;
		}

		if (target.alreadyHarvested) {
			res
				.status(200)
				.json({ ok: true, skipped: true, reason: "already_harvested" });
			return;
		}

		const { harvestAndReplyForPost } = await import(
			"./_lib/handlers/auto-post/autoReply.js"
		);

		const result = await harvestAndReplyForPost(
			target.workspaceId,
			target.groupId,
			target.ownerId,
			target.accountId,
			target.postId,
			target.queueItemId,
			sourceTable,
		);

		res.status(200).json({
			ok: true,
			harvested: result.harvested,
			published: result.published,
		});
	} catch (err) {
		logger.error("[auto-reply-harvest] Handler error", {
			queueItemId,
			error: String(err),
		});
		// Report to Sentry so failures are visible in monitoring
		import("./_lib/sentryServer.js")
			.then(({ captureServerException }) =>
				captureServerException(err, {
					handler: "auto-reply-harvest",
					queueItemId,
				}),
			)
			.catch(() => {});
		// Return 200 to prevent QStash retries on unexpected errors
		// The cron fallback will catch any missed harvests
		res.status(200).json({ ok: true, skipped: true, reason: "error" });
	}
}

async function resolveHarvestTarget(
	db: unknown,
	sourceTable: "auto_post_queue" | "posts",
	queueItemId: string,
	postId: string,
): Promise<HarvestTarget | null> {
	const client = db as SupabaseLike;
	const asString = (value: unknown): string | null =>
		typeof value === "string" && value.length > 0 ? value : null;

	if (sourceTable === "auto_post_queue") {
		const { data: item } = await client
			.from("auto_post_queue")
			.select("id, workspace_id, group_id, account_id, reply_harvested_at")
			.eq("id", queueItemId)
			.eq("status", "published")
			.maybeSingle();
		const itemId = asString(item?.id);
		const accountId = asString(item?.account_id);
		const groupId = asString(item?.group_id);
		const workspaceId = asString(item?.workspace_id);
		if (!itemId || !accountId || !groupId || !workspaceId) {
			return null;
		}

		const { data: account } = await client
			.from("accounts")
			.select("user_id")
			.eq("id", accountId)
			.maybeSingle();
		const ownerId = asString(account?.user_id);
		if (!ownerId) return null;

		return {
			queueItemId: itemId,
			postId: itemId,
			workspaceId,
			groupId,
			ownerId,
			accountId,
			alreadyHarvested: Boolean(item?.reply_harvested_at),
		};
	}

	const { data: post } = await client
		.from("posts")
		.select("id, user_id, account_id, group_id, metadata")
		.eq("id", postId || queueItemId)
		.eq("status", "published")
		.maybeSingle();
	const resolvedPostId = asString(post?.id);
	const postAccountId = asString(post?.account_id);
	const postOwnerId = asString(post?.user_id);
	if (!resolvedPostId || !postAccountId || !postOwnerId) return null;

	let groupId = asString(post?.group_id);
	if (!groupId) {
		const { data: group } = await client
			.from("account_groups")
			.select("id")
			.eq("user_id", postOwnerId)
			.contains("account_ids", [postAccountId])
			.maybeSingle();
		groupId = asString(group?.id);
	}
	if (!groupId) return null;

	const { data: groupConfig } = await client
		.from("auto_post_group_config")
		.select("workspace_id")
		.eq("group_id", groupId)
		.maybeSingle();
	const workspaceId = asString(groupConfig?.workspace_id);
	if (!workspaceId) return null;

	return {
		queueItemId: resolvedPostId,
		postId: resolvedPostId,
		workspaceId,
		groupId,
		ownerId: postOwnerId,
		accountId: postAccountId,
		alreadyHarvested: Boolean(
			(post?.metadata as Record<string, unknown> | null)?.reply_harvested_at,
		),
	};
}
