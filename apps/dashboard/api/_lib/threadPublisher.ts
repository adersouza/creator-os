// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Self-Reply Thread Chain Publisher
 *
 * Publishes a multi-post self-reply thread chain on Threads.
 * Reusable function not tied to Express req/res — suitable for
 * autoposter, MCP tools, and any programmatic publish path.
 *
 * Self-reply threads average 4,416 views/post vs ~83 for single posts.
 */

import { decrypt } from "./encryption.js";
import { logger } from "./logger.js";
import { withRetry } from "./retryUtils.js";
import { sanitizeHtml } from "./sanitize.js";

const THREADS_API_BASE = "https://graph.threads.net/v1.0";
const CONTAINER_TIMEOUT = 10_000;
const PUBLISH_TIMEOUT = 10_000;
const INTER_PUBLISH_DELAY_MS = 500;

interface ThreadChainResult {
	success: boolean;
	rootThreadId?: string | undefined;
	allPostIds?: string[] | undefined;
	error?: string | undefined;
}

/**
 * Publish a self-reply thread chain on Threads.
 * Takes an array of text parts and chains them as replies.
 * Returns the root post ID and all child IDs.
 *
 * Partial success is OK — if part 3 of 4 fails, we return
 * the IDs of the 2 successfully published posts.
 */
export async function publishThreadChain(
	encryptedAccessToken: string,
	threadsUserId: string,
	parts: string[],
	topicTag?: string | null,
): Promise<ThreadChainResult> {
	if (!parts || parts.length === 0) {
		return { success: false, error: "No parts provided" };
	}

	let token: string;
	try {
		token = decrypt(encryptedAccessToken);
	} catch (err) {
		return {
			success: false,
			error: `Token decrypt failed: ${err instanceof Error ? err.message : String(err)}`,
		};
	}

	const postIds: string[] = [];
	let previousId: string | null = null;

	for (let i = 0; i < parts.length; i++) {
		const content = sanitizeHtml(parts[i]!);
		if (!content) continue;

		try {
			// Step 1: Create container
			const createParams: Record<string, string> = {
				media_type: "TEXT",
				text: content,
			};

			// Topic tag only on the root post
			if (i === 0 && topicTag) {
				createParams.topic_tag = topicTag;
			}

			// Self-reply: chain to previous post
			if (previousId) {
				createParams.reply_to_id = previousId;
			}

			const createUrl = `${THREADS_API_BASE}/${threadsUserId}/threads`;
			const createResponse = await withRetry(() =>
				fetch(createUrl, {
					method: "POST",
					headers: {
						"Content-Type": "application/x-www-form-urlencoded",
						Authorization: `Bearer ${token}`,
					},
					body: new URLSearchParams(createParams),
					signal: AbortSignal.timeout(CONTAINER_TIMEOUT),
				}),
			);

			const createData = await createResponse.json();
			if (!createResponse.ok || !createData.id) {
				const errMsg = createData.error?.message || "Unknown container error";
				logger.warn("[threadChain] Container creation failed", {
					part: i + 1,
					total: parts.length,
					error: errMsg,
				});
				// Return partial success if we already published the root
				if (postIds.length > 0) {
					return {
						success: true,
						rootThreadId: postIds[0],
						allPostIds: postIds,
						error: `Partial: failed at part ${i + 1}: ${errMsg}`,
					};
				}
				return {
					success: false,
					error: `Container ${i + 1} failed: ${errMsg}`,
				};
			}

			const containerId = createData.id as string;

			// Step 2: Publish
			const publishUrl = `${THREADS_API_BASE}/${threadsUserId}/threads_publish`;
			const publishResponse = await withRetry(() =>
				fetch(publishUrl, {
					method: "POST",
					headers: {
						"Content-Type": "application/x-www-form-urlencoded",
						Authorization: `Bearer ${token}`,
					},
					body: new URLSearchParams({ creation_id: containerId }),
					signal: AbortSignal.timeout(PUBLISH_TIMEOUT),
				}),
			);

			const publishData = await publishResponse.json();
			if (!publishResponse.ok || !publishData.id) {
				const errMsg = publishData.error?.message || "Unknown publish error";
				logger.warn("[threadChain] Publish failed", {
					part: i + 1,
					total: parts.length,
					error: errMsg,
				});
				if (postIds.length > 0) {
					return {
						success: true,
						rootThreadId: postIds[0],
						allPostIds: postIds,
						error: `Partial: failed at part ${i + 1}: ${errMsg}`,
					};
				}
				return { success: false, error: `Publish ${i + 1} failed: ${errMsg}` };
			}

			postIds.push(publishData.id as string);
			previousId = publishData.id as string;

			// Rate limiting between publishes
			if (i < parts.length - 1) {
				await new Promise((resolve) =>
					setTimeout(resolve, INTER_PUBLISH_DELAY_MS),
				);
			}
		} catch (err) {
			const errMsg = err instanceof Error ? err.message : String(err);
			logger.warn("[threadChain] Exception at part", {
				part: i + 1,
				total: parts.length,
				error: errMsg,
			});
			if (postIds.length > 0) {
				return {
					success: true,
					rootThreadId: postIds[0],
					allPostIds: postIds,
					error: `Partial: exception at part ${i + 1}: ${errMsg}`,
				};
			}
			return { success: false, error: `Exception at part ${i + 1}: ${errMsg}` };
		}
	}

	if (postIds.length === 0) {
		return { success: false, error: "No parts were published" };
	}

	return {
		success: true,
		rootThreadId: postIds[0],
		allPostIds: postIds,
	};
}
