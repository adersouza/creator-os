/**
 * Unified Smart Inbox — GET /api/inbox/unified
 *
 * Merges IG comments, IG mentions, Threads replies, Threads mentions, and
 * cached IG DMs into a single prioritized inbox view. The high-volume post
 * sources are queried in chunks so 200-account workspaces do not build giant
 * PostgREST `.in(post_id, ...)` URLs.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

interface UnifiedMessage {
	id: string;
	source:
		| "ig_dm"
		| "ig_comment"
		| "ig_mention"
		| "threads_reply"
		| "threads_mention";
	accountId?: string | null | undefined;
	groupId?: string | null | undefined;
	conversationId?: string | undefined;
	replyToId?: string | undefined;
	replyKind?: "dm" | "comment" | "reply" | undefined;
	from: { id: string; username: string; avatar?: string | undefined };
	text: string;
	timestamp: string;
	postId?: string | undefined;
	postPreview?: string | undefined;
	sentiment?: "positive" | "neutral" | "negative" | "toxic" | undefined;
	isRead: boolean;
	isReplied: boolean;
	priority: number;
}

interface AccountRow {
	id: string;
	threads_user_id?: string | undefined;
	instagram_user_id?: string | undefined;
	username: string;
	group_id?: string | null | undefined;
}

interface PostRow {
	id: string;
	content: string;
	account_id?: string | null | undefined;
	instagram_account_id?: string | null | undefined;
}

const POST_ID_QUERY_CHUNK_SIZE = 200;

function computePriority(msg: Omit<UnifiedMessage, "priority">): number {
	const isRecent =
		Date.now() - new Date(msg.timestamp).getTime() < 60 * 60 * 1000;
	if (
		!msg.isReplied &&
		(msg.sentiment === "negative" || msg.sentiment === "toxic")
	)
		return 100;
	if (!msg.isReplied) return 80;
	if (msg.sentiment === "negative" || msg.sentiment === "toxic") return 70;
	if (isRecent) return 60;
	return 40;
}

function withPriority(base: Omit<UnifiedMessage, "priority">): UnifiedMessage {
	return { ...base, priority: computePriority(base) };
}

function chunkArray<T>(items: T[], size: number): T[][] {
	const chunks: T[][] = [];
	for (let i = 0; i < items.length; i += size) {
		chunks.push(items.slice(i, i + size));
	}
	return chunks;
}

function sortRowsByTimestamp(
	rows: Record<string, unknown>[],
	field: string,
): Record<string, unknown>[] {
	return [...rows].sort(
		(a, b) =>
			new Date((b[field] as string) || 0).getTime() -
			new Date((a[field] as string) || 0).getTime(),
	);
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const filter = (req.query.filter as string) || "all";
		const parsedPage = parseInt(req.query.page as string, 10);
		if (req.query.page && Number.isNaN(parsedPage))
			return apiError(res, 400, "Invalid page");
		const page = Math.max(1, parsedPage || 1);
		const parsedLimit = parseInt(req.query.limit as string, 10);
		if (req.query.limit && Number.isNaN(parsedLimit))
			return apiError(res, 400, "Invalid limit");
		const limit = Math.min(100, Math.max(1, parsedLimit || 50));
		const cursor = typeof req.query.cursor === "string" ? req.query.cursor : null;
		if (cursor && Number.isNaN(new Date(cursor).getTime()))
			return apiError(res, 400, "Invalid cursor");
		const offset = cursor ? 0 : (page - 1) * limit;

		const db = getSupabase();
		const messages: UnifiedMessage[] = [];
		const fetchLimit = limit * 2;

		try {
			const [{ data: accounts }, { data: instagramAccounts }, { data: userPosts }] = await Promise.all([
				db
					.from("accounts")
					.select("id, threads_user_id, username, group_id")
					.eq("user_id", user.id),
				db
					.from("instagram_accounts")
					.select("id, instagram_user_id, username, group_id")
					.eq("user_id", user.id),
				db
					.from("posts")
					.select("id, content, account_id, instagram_account_id")
					.eq("user_id", user.id)
					.eq("status", "published")
					.order("created_at", { ascending: false })
					.limit(5000),
			]);

			const accountRows = [
				...((accounts || []) as unknown as AccountRow[]),
				...((instagramAccounts || []) as unknown as AccountRow[]),
			];
			const accountIds = accountRows.map((a) => a.id);
			const accountGroupById = new Map(
				accountRows.map((a) => [a.id, a.group_id ?? null]),
			);
			const postRows = (userPosts || []) as unknown as PostRow[];
			const postIds = postRows.map((p) => p.id);
			const postsMap = new Map(postRows.map((p) => [p.id, p]));

			const countPromises: PromiseLike<number>[] = [];
			const dataPromises: PromiseLike<void>[] = [];

			if ((filter === "all" || filter === "replies") && postIds.length > 0) {
				const chunks = chunkArray(postIds, POST_ID_QUERY_CHUNK_SIZE);
				countPromises.push(
					Promise.all(
						chunks.map((ids) => {
							let query = db
								.from("post_replies")
								.select("id", { count: "exact", head: true })
								.in("post_id", ids);
							if (cursor) query = query.lt("created_at", cursor);
							return query.then((r: { count: number | null }) => r.count || 0);
						}),
					).then((counts) => counts.reduce((sum, count) => sum + count, 0)),
				);
				dataPromises.push(
					Promise.all(
						chunks.map((ids) => {
							let query = db
								.from("post_replies")
								.select(
									"id, post_id, content, username, avatar_url, created_at, is_read, likes_count, threads_reply_id",
								)
								.in("post_id", ids);
							if (cursor) query = query.lt("created_at", cursor);
							return query
								.order("created_at", { ascending: false })
								.limit(fetchLimit);
						}),
					).then((results: Array<{ data: Record<string, unknown>[] | null }>) => {
						const replies = sortRowsByTimestamp(
							results.flatMap((result) => result.data || []),
							"created_at",
						).slice(0, fetchLimit);
						for (const r of replies) {
							const post = postsMap.get(r.post_id as string);
							const accountId = post?.account_id ?? null;
							messages.push(
								withPriority({
									id: `threads_reply_${r.id}`,
									source: "threads_reply",
									accountId,
									groupId: accountId ? accountGroupById.get(accountId) ?? null : null,
									replyToId: (r.threads_reply_id as string) || String(r.id),
									replyKind: "reply",
									from: {
										id: (r.username as string) || "unknown",
										username: (r.username as string) || "unknown",
										avatar: (r.avatar_url as string) || undefined,
									},
									text: (r.content as string) || "",
									timestamp: (r.created_at as string) || new Date().toISOString(),
									postId: (r.post_id as string) || undefined,
									postPreview: post?.content?.substring(0, 100) || undefined,
									isRead: Boolean(r.is_read),
									isReplied: false,
								}),
							);
						}
					}),
				);
			}

			if (filter === "all" || filter === "mentions") {
				countPromises.push(
					(() => {
						let query = db
							.from("mentions")
							.select("id", { count: "exact", head: true })
							.eq("user_id", user.id);
						if (cursor) query = query.lt("mentioned_at", cursor);
						return query.then((r: { count: number | null }) => r.count || 0);
					})(),
				);
				dataPromises.push(
					(() => {
						let query = db
							.from("mentions")
							.select(
								"id, account_id, mentioned_by_username, mentioned_by_avatar, content, mentioned_at, created_at, permalink, is_read, threads_post_id",
							)
							.eq("user_id", user.id);
						if (cursor) query = query.lt("mentioned_at", cursor);
						return query
							.order("mentioned_at", { ascending: false })
							.limit(fetchLimit)
							.then((result: { data: Record<string, unknown>[] | null }) => {
								for (const m of result.data || []) {
									const accountId =
										typeof m.account_id === "string" ? m.account_id : null;
									messages.push(
										withPriority({
											id: `threads_mention_${m.id}`,
											source: "threads_mention",
											accountId,
											groupId: accountId
												? accountGroupById.get(accountId) ?? null
												: null,
											replyToId: (m.threads_post_id as string) || String(m.id),
											replyKind: "reply",
											from: {
												id: (m.mentioned_by_username as string) || "unknown",
												username:
													(m.mentioned_by_username as string) || "unknown",
												avatar:
													(m.mentioned_by_avatar as string) || undefined,
											},
											text: (m.content as string) || "Mentioned you",
											timestamp:
												(m.mentioned_at as string) ||
												(m.created_at as string) ||
												new Date().toISOString(),
											postPreview: (m.permalink as string) || undefined,
											isRead: Boolean(m.is_read),
											isReplied: false,
										}),
									);
								}
							});
					})(),
				);
			}

			if ((filter === "all" || filter === "comments") && postIds.length > 0) {
				const chunks = chunkArray(postIds, POST_ID_QUERY_CHUNK_SIZE);
				countPromises.push(
					Promise.all(
						chunks.map((ids) => {
							let query = db
								.from("ig_comments")
								.select("id", { count: "exact", head: true })
								.in("post_id", ids);
							if (cursor) query = query.lt("created_at", cursor);
							return query.then((r: { count: number | null }) => r.count || 0);
						}),
					).then((counts) => counts.reduce((sum, count) => sum + count, 0)),
				);
				dataPromises.push(
					Promise.all(
						chunks.map((ids) => {
							let query = db
								.from("ig_comments")
								.select("id, account_id, comment_id, post_id, text, username, created_at, media_id, like_count, is_read")
								.in("post_id", ids);
							if (cursor) query = query.lt("created_at", cursor);
							return query
								.order("created_at", { ascending: false })
								.limit(fetchLimit);
						}),
					).then((results: Array<{ data: Record<string, unknown>[] | null }>) => {
						const comments = sortRowsByTimestamp(
							results.flatMap((result) => result.data || []),
							"created_at",
						).slice(0, fetchLimit);
						for (const c of comments) {
							const post = postsMap.get(c.post_id as string);
							const accountId =
								(c.account_id as string | null) ??
								post?.instagram_account_id ??
								post?.account_id ??
								null;
							messages.push(
								withPriority({
									id: `ig_comment_${c.id}`,
									source: "ig_comment",
									accountId,
									groupId: accountId ? accountGroupById.get(accountId) ?? null : null,
									replyToId: (c.comment_id as string) || String(c.id),
									replyKind: "comment",
									from: {
										id: (c.username as string) || "unknown",
										username: (c.username as string) || "unknown",
									},
									text: (c.text as string) || "",
									timestamp: (c.created_at as string) || new Date().toISOString(),
									postId: (c.media_id as string) || (c.post_id as string) || undefined,
									postPreview: post?.content?.substring(0, 100) || undefined,
									isRead: c.is_read === true,
									isReplied: false,
								}),
							);
						}
					}),
				);
			}

			if (filter === "all" || filter === "mentions") {
				countPromises.push(
					(() => {
						let query = db
							.from("ig_mentions")
							.select("id", { count: "exact", head: true })
							.eq("user_id", user.id);
						if (cursor) query = query.lt("mentioned_at", cursor);
						return query.then((r: { count: number | null }) => r.count || 0);
					})(),
				);
				dataPromises.push(
					(() => {
						let query = db
							.from("ig_mentions")
							.select("id, ig_account_id, username, caption, mentioned_at, permalink, media_id, is_read")
							.eq("user_id", user.id);
						if (cursor) query = query.lt("mentioned_at", cursor);
						return query
							.order("mentioned_at", { ascending: false })
							.limit(fetchLimit)
							.then((result: { data: Record<string, unknown>[] | null }) => {
								for (const m of result.data || []) {
									const accountId =
										typeof m.ig_account_id === "string" ? m.ig_account_id : null;
									messages.push(
										withPriority({
											id: `ig_mention_${m.id}`,
											source: "ig_mention",
											accountId,
											groupId: accountId
												? accountGroupById.get(accountId) ?? null
												: null,
											replyToId: (m.media_id as string) || String(m.id),
											replyKind: "comment",
											from: {
												id: (m.username as string) || "unknown",
												username: (m.username as string) || "unknown",
											},
											text: (m.caption as string) || "Mentioned you",
											timestamp:
												(m.mentioned_at as string) || new Date().toISOString(),
											postPreview: (m.permalink as string) || undefined,
											isRead: m.is_read === true,
											isReplied: false,
										}),
									);
								}
							});
					})(),
				);
			}

			if (filter === "all" || filter === "comments") {
				countPromises.push(
					(() => {
						let query = db
							.from("inbox_dm_cache")
							.select("id", { count: "exact", head: true })
							.eq("user_id", user.id);
						if (cursor) query = query.lt("last_message_at", cursor);
						return query.then((r: { count: number | null }) => r.count || 0);
					})(),
				);
				dataPromises.push(
					(() => {
						let query = db
							.from("inbox_dm_cache")
							.select("id, account_id, participant_username, conversation_name, last_message_text, last_message_at, updated_at, is_read")
							.eq("user_id", user.id);
						if (cursor) query = query.lt("last_message_at", cursor);
						return query
							.order("last_message_at", { ascending: false })
							.limit(fetchLimit)
							.then((result: { data: Record<string, unknown>[] | null }) => {
								for (const dm of result.data || []) {
									const accountId =
										typeof dm.account_id === "string" ? dm.account_id : null;
									const username =
										(dm.participant_username as string) ||
										(dm.conversation_name as string) ||
										"unknown";
									messages.push(
										withPriority({
											id: `ig_dm_${dm.id}`,
											source: "ig_dm",
											accountId,
											groupId: accountId
												? accountGroupById.get(accountId) ?? null
												: null,
											conversationId: String(dm.id),
											replyToId: String(dm.id),
											replyKind: "dm",
											from: { id: username, username },
											text: (dm.last_message_text as string) || "",
											timestamp:
												(dm.last_message_at as string) ||
												(dm.updated_at as string) ||
												new Date().toISOString(),
											isRead: dm.is_read === true,
											isReplied: false,
										}),
									);
								}
							});
					})(),
				);
			}

			const [counts] = await Promise.all([
				Promise.all(countPromises),
				Promise.all(dataPromises),
			]);
			const totalCount = counts.reduce((a, b) => a + b, 0);

			if (accountIds.length > 0) {
				const { data: sentReplies } = await db
					.from("sent_replies")
					.select("parent_post_id")
					.in("account_id", accountIds);
				const repliedPostIds = new Set(
					((sentReplies || []) as unknown as { parent_post_id: string }[]).map(
						(r) => r.parent_post_id,
					),
				);
				for (const msg of messages) {
					if (msg.postId && repliedPostIds.has(msg.postId)) {
						msg.isReplied = true;
						msg.priority = computePriority(msg);
					}
				}
			}

			messages.sort((a, b) => {
				if (b.priority !== a.priority) return b.priority - a.priority;
				return (
					new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
				);
			});

			const paged = messages.slice(offset, offset + limit);

			return apiSuccess(res, {
				messages: paged,
				total: totalCount,
				page,
				limit,
				hasMore: cursor
					? messages.length > limit
					: offset + limit < totalCount,
				nextCursor:
					paged.length > 0
						? paged[paged.length - 1]?.timestamp ?? null
						: null,
			});
		} catch (err) {
			logger.error("[inbox/unified] Failed to fetch unified inbox messages", {
				error: String(err),
			});
			return apiError(res, 500, "Internal server error");
		}
	},
);
