/**
 * Instagram Comment Management — get comments, reply, hide, delete,
 * and private reply to comments via DM.
 */

import {
	decrypt,
	getGraphBaseUrl,
	type IGComment,
	type IGPaging,
	igFetch,
	logger,
} from "./shared.js";

// ============================================================================
// Comment Management
// ============================================================================

export async function getMediaComments(
	encryptedToken: string,
	mediaId: string,
	after?: string,
	loginType?: string,
): Promise<{
	success: boolean;
	comments?: IGComment[] | undefined;
	paging?: IGPaging | undefined;
	error?: string | undefined;
}> {
	try {
		if (typeof encryptedToken !== "string" || encryptedToken.length === 0) {
			throw new Error("Instagram access token not available");
		}
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		let url = `${graphBase}/v25.0/${mediaId}/comments?fields=id,text,username,timestamp,like_count,parent_id,from{id,username},replies{id,text,username,timestamp,like_count,parent_id,from{id,username}},hidden`;
		if (after) url += `&after=${after}`;

		const response = await igFetch(url, undefined, "igApi:getComments", token);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to fetch comments",
			};
		}

		return { success: true, comments: data.data || [], paging: data.paging };
	} catch (error: unknown) {
		logger.error("IG getMediaComments error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

export async function replyToComment(
	encryptedToken: string,
	commentId: string,
	message: string,
	loginType?: string,
): Promise<{ success: boolean; commentId?: string | undefined; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${commentId}/replies`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ message }),
			},
			"igApi:replyComment",
			token,
		);

		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to reply",
			};
		}

		return { success: true, commentId: data.id };
	} catch (error: unknown) {
		logger.error("IG replyToComment error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

export async function hideComment(
	encryptedToken: string,
	commentId: string,
	hide: boolean,
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${commentId}`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ hide }),
			},
			"igApi:hideComment",
			token,
		);

		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to update comment visibility",
			};
		}

		return { success: true };
	} catch (error: unknown) {
		logger.error("IG hideComment error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

export async function deleteComment(
	encryptedToken: string,
	commentId: string,
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${commentId}`,
			{ method: "DELETE" },
			"igApi:deleteComment",
			token,
		);

		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to delete comment",
			};
		}

		return { success: true };
	} catch (error: unknown) {
		logger.error("IG deleteComment error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Private Reply to Comment
// ============================================================================

/**
 * Send a private reply to a commenter via DM.
 * Uses POST /{ig-user-id}/messages with recipient.comment_id per Meta docs.
 * Must be sent within 7 days of comment (Live: during broadcast only).
 * Only one private reply allowed per comment.
 */
export async function sendPrivateReply(
	encryptedToken: string,
	igUserId: string,
	commentId: string,
	message: string,
	loginType?: string,
): Promise<{ success: boolean; messageId?: string | undefined; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/messages`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					recipient: { comment_id: commentId },
					message: { text: message },
				}),
			},
			"igApi:privateReply",
			token,
		);

		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to send private reply",
			};
		}

		return { success: true, messageId: data.message_id };
	} catch (error: unknown) {
		logger.error("IG sendPrivateReply error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}
