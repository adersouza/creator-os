/**
 * Reply Chain Pulse — sync reply-chain depth for published Threads posts.
 *
 * Calls GET /v1.0/{media-id}/conversation?fields=id,replied_to,timestamp,text,username
 * and reconstructs the reply tree from replied_to.id edges when the edge is
 * available. Some production accounts/posts currently receive Meta code 100
 * "Tried accessing nonexisting field (conversation)" behind HTTP 500. That is
 * a permanent unsupported-edge response, not a transient outage or token issue,
 * so this sync records depth=1 for those posts and moves on.
 *
 * Depth:
 *   1 = root post only (empty conversation)
 *   2 = ≥1 direct reply to root
 *   3 = ≥1 reply to a reply
 *   N = longest descendant chain from root
 *
 * Rate-limit awareness: each call = 1 against Threads API's 250/24h per
 * account. Caller (cron wrapper) is responsible for batching + budget.
 * This helper just does one post at a time.
 */

import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabase } from "../../supabase.js";
import type { Database } from "../../../../types/supabase.js";

type PostUpdate = Database["public"]["Tables"]["posts"]["Update"];

// ---------------------------------------------------------------------------
// Types (exported for unit tests)
// ---------------------------------------------------------------------------

export interface ConversationItem {
	id: string;
	replied_to?: { id: string } | null | undefined;
	timestamp?: string | undefined;
	text?: string | undefined;
	username?: string | undefined;
}

interface ThreadsApiError {
	code?: number | undefined;
	message?: string | undefined;
	type?: string | undefined;
	error_subcode?: number | undefined;
	fbtrace_id?: string | undefined;
}

interface ThreadsConversationResponse {
	data?: ConversationItem[] | undefined;
	error?: ThreadsApiError | undefined;
}

// ---------------------------------------------------------------------------
// Pure depth calculation (tested in isolation)
// ---------------------------------------------------------------------------

/**
 * Compute reply-chain depth from a flat conversation list.
 *
 * Contract:
 *   - `rootId` is the threads_post_id of the original post.
 *   - `items` is the flat array returned by /conversation (any order).
 *   - Items whose replied_to.id doesn't resolve to the root or any other
 *     item in the list are treated as orphan children of root (defensive
 *     against Threads returning partial trees).
 *
 * Returns at least 1 (root-only). Never throws.
 */
export function computeReplyDepth(
	rootId: string,
	items: ConversationItem[],
): number {
	if (!items.length) return 1;

	// Build adjacency: parentId → childIds
	const children = new Map<string, string[]>();
	const knownIds = new Set<string>([rootId, ...items.map((i) => i.id)]);

	for (const item of items) {
		const parent = item.replied_to?.id;
		// If parent isn't in the conversation set at all, treat as child of root.
		// Prevents orphans from being dropped when Threads returns partial data.
		const resolvedParent =
			parent && knownIds.has(parent) ? parent : rootId;
		const list = children.get(resolvedParent);
		if (list) list.push(item.id);
		else children.set(resolvedParent, [item.id]);
	}

	// Second pass: re-parent cycle-disconnected items onto root. If any item
	// can't reach root by walking up replied_to edges (e.g. A→B, B→A with
	// neither pointing at root), it'd be unreachable from our BFS and silently
	// dropped. Promote it to root's direct child so the conversation counts.
	const reachableFromRoot = new Set<string>([rootId]);
	const bfsReach: string[] = [rootId];
	while (bfsReach.length) {
		// biome-ignore lint/style/noNonNullAssertion: while(length) guard guarantees shift() is non-null
		const id = bfsReach.shift()!;
		const kids = children.get(id);
		if (!kids) continue;
		for (const kid of kids) {
			if (!reachableFromRoot.has(kid)) {
				reachableFromRoot.add(kid);
				bfsReach.push(kid);
			}
		}
	}
	for (const item of items) {
		if (!reachableFromRoot.has(item.id)) {
			const list = children.get(rootId);
			if (list) list.push(item.id);
			else children.set(rootId, [item.id]);
		}
	}

	// Final BFS: track the deepest level reached.
	let maxDepth = 1;
	const queue: Array<{ id: string; depth: number }> = [
		{ id: rootId, depth: 1 },
	];
	const visited = new Set<string>();

	while (queue.length) {
		// biome-ignore lint/style/noNonNullAssertion: while(length) guard guarantees shift() is non-null
		const node = queue.shift()!;
		if (visited.has(node.id)) continue; // guard against API cycles
		visited.add(node.id);
		if (node.depth > maxDepth) maxDepth = node.depth;
		const kids = children.get(node.id);
		if (kids) {
			for (const kid of kids) {
				queue.push({ id: kid, depth: node.depth + 1 });
			}
		}
	}

	return maxDepth;
}

// ---------------------------------------------------------------------------
// Single-post sync (I/O)
// ---------------------------------------------------------------------------

export interface ReplyChainSyncResult {
	postId: string;
	threadsPostId: string;
	depth: number;
	itemCount: number;
}

export class ReplyChainRateLimitError extends Error {
	constructor() {
		super("Threads API rate limit hit during reply-chain sync");
		this.name = "ReplyChainRateLimitError";
	}
}

class ReplyChainUnsupportedEdgeError extends Error {
	readonly apiError: ThreadsApiError;

	constructor(apiError: ThreadsApiError) {
		super(apiError.message ?? "Threads conversation edge is unavailable");
		this.name = "ReplyChainUnsupportedEdgeError";
		this.apiError = apiError;
	}
}

class ReplyChainHttpError extends Error {
	readonly status: number;

	constructor(status: number, body: string) {
		super(`Threads /conversation returned ${status}: ${body.slice(0, 200)}`);
		this.name = "ReplyChainHttpError";
		this.status = status;
	}
}

function safeParseThreadsResponse(body: string): ThreadsConversationResponse {
	if (!body) return {};
	try {
		const parsed = JSON.parse(body) as ThreadsConversationResponse;
		return parsed && typeof parsed === "object" ? parsed : {};
	} catch {
		return {};
	}
}

function isUnsupportedConversationEdge(
	error: ThreadsApiError | undefined,
): error is ThreadsApiError {
	const message = error?.message?.toLowerCase() ?? "";
	return (
		error?.code === 100 &&
		message.includes("nonexisting field") &&
		message.includes("conversation")
	);
}

function shouldRetryReplyChainError(error: unknown): boolean {
	if (
		error instanceof ReplyChainRateLimitError ||
		error instanceof ReplyChainUnsupportedEdgeError
	) {
		return false;
	}
	const status = (error as { status?: unknown; code?: unknown })?.status ??
		(error as { status?: unknown; code?: unknown })?.code;
	return (
		!status ||
		status === 429 ||
		(typeof status === "number" && status >= 500)
	);
}

async function fetchConversation(
	url: string,
	token: string,
	threadsPostId: string,
): Promise<ThreadsConversationResponse> {
	return withRetry(
		async () => {
			const response = await fetch(url, {
				headers: { Authorization: `Bearer ${token}` },
				signal: AbortSignal.timeout(6000),
			});
			const body = await response.text().catch(() => "");
			const data = safeParseThreadsResponse(body);

			if (response.status === 429) {
				throw new ReplyChainRateLimitError();
			}

			if (isUnsupportedConversationEdge(data.error)) {
				throw new ReplyChainUnsupportedEdgeError(data.error);
			}

			if (!response.ok) {
				throw new ReplyChainHttpError(response.status, body);
			}

			return data;
		},
		{
			label: `replyChain:${threadsPostId}`,
			shouldRetry: shouldRetryReplyChainError,
		},
	);
}

/**
 * Sync one post's reply chain. Returns the computed depth on success,
 * throws typed errors on failure so the cron wrapper can budget
 * rate-limit recovery.
 */
export async function syncReplyChainForPost(args: {
	postId: string;
	threadsPostId: string;
	accountId: string;
	accessTokenEncrypted: string;
}): Promise<ReplyChainSyncResult> {
	const { postId, threadsPostId, accessTokenEncrypted } = args;
	const token = decrypt(accessTokenEncrypted);

	const url = `https://graph.threads.net/v1.0/${threadsPostId}/conversation?fields=id,replied_to,timestamp,text,username`;
	let data: ThreadsConversationResponse;
	try {
		data = await fetchConversation(url, token, threadsPostId);
	} catch (error) {
		if (error instanceof ReplyChainUnsupportedEdgeError) {
			logger.info(
				"[replyChainSync] Threads conversation edge unavailable; recording depth=1",
				{
					postId,
					threadsPostId,
					code: error.apiError.code,
					type: error.apiError.type,
					message: error.apiError.message,
					fbtraceId: error.apiError.fbtrace_id,
				},
			);
			await persistReplyChain(postId, []);
			await persistDepth(postId, 1);
			return { postId, threadsPostId, depth: 1, itemCount: 0 };
		}
		throw error;
	}

	if (data.error) {
		// Treat user-not-allowed / post-deleted as "empty chain" rather than throwing
		// — lets the cron make progress through a batch without stalling on one bad row.
		logger.info("[replyChainSync] Threads returned error; recording depth=1", {
			postId,
			threadsPostId,
			error: data.error.message,
		});
		await persistDepth(postId, 1);
		return { postId, threadsPostId, depth: 1, itemCount: 0 };
	}

	const items = data.data ?? [];
	const depth = computeReplyDepth(threadsPostId, items);

	// Best-effort reply-chain write. Powers the velocity-histogram
	// tile + text-bearing reply tree (nice-to-have). If this fails,
	// the depth write below still runs — depth is the production-
	// critical signal and must not be blocked by an issue with the
	// reply-chain persistence path.
	try {
		await persistReplyChain(postId, items);
	} catch (err) {
		logger.warn(
			"[replyChainSync] Failed to persist reply chain; continuing with depth write",
			{
				postId,
				error: err instanceof Error ? err.message : String(err),
			},
		);
	}

	await persistDepth(postId, depth);

	return { postId, threadsPostId, depth, itemCount: items.length };
}

async function persistReplyChain(
	postId: string,
	items: ConversationItem[],
): Promise<void> {
	// Sort ascending (oldest first). Drop items missing timestamp —
	// the field is optional and we'd rather skip than write malformed
	// entries. Strip undefined fields for tighter JSONB storage.
	const chain = items
		.map((i) => ({
			id: i.id,
			replied_to: i.replied_to?.id ?? null,
			timestamp: i.timestamp ? Math.floor(Date.parse(i.timestamp) / 1000) : null,
			username: i.username ?? null,
			text: i.text ?? null,
		}))
		.filter((c) => c.timestamp != null)
		.sort((a, b) => (a.timestamp ?? 0) - (b.timestamp ?? 0));

	const patch: PostUpdate = { reply_chain: chain };
	const { error } = await getSupabase()
		.from("posts")
		.update(patch)
		.eq("id", postId);
	if (error) {
		throw new Error(`Failed to persist reply_chain: ${error.message}`);
	}
}

async function persistDepth(postId: string, depth: number): Promise<void> {
	const patch: PostUpdate = {
		reply_depth: depth,
		reply_chain_synced_at: new Date().toISOString(),
	};
	const { error } = await getSupabase()
		.from("posts")
		.update(patch)
		.eq("id", postId);
	if (error) {
		logger.warn("[replyChainSync] Failed to persist depth", {
			postId,
			depth,
			error: error.message,
		});
		throw new Error(`Failed to persist reply_depth: ${error.message}`);
	}
}
