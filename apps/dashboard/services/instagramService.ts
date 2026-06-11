// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { randomUUID } from "@/src/lib/uuid.js";
import logger from "@/utils/logger.js";
import { supabase } from "./supabase.js";

async function getAuthHeaders(): Promise<HeadersInit> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) {
		throw new Error("No active session — please log in again");
	}
	return {
		"Content-Type": "application/json",
		Authorization: `Bearer ${session.access_token}`,
	};
}

const API_BASE = "/api";

async function postRequest<T = unknown>(
	url: string,
	body: Record<string, unknown>,
): Promise<T | null> {
	// Global guard: reject invalid accountIds before hitting the network.
	// Instagram/Meta API calls always require a specific account ID — "ALL" is a
	// UI-level concept and must never reach the API. Return null so callers can
	// skip rendering rather than trigger an error.
	const accountId = body.accountId as string | undefined;
	if (accountId !== undefined && (!accountId || accountId === "ALL")) {
		return null;
	}

	const requestId = randomUUID().slice(0, 8); // Short ID for logs
	const tag = `[IG:${url.split("?")[0]!.replace("/instagram/", "")}][${requestId}]`;
	const startTime = performance.now();

	const headers = await getAuthHeaders();
	let response: Response;
	try {
		response = await fetch(`${API_BASE}${url}`, {
			method: "POST",
			headers,
			body: JSON.stringify(body),
		});
	} catch (networkErr) {
		const elapsed = Math.round(performance.now() - startTime);
		logger.error(`${tag} Network error after ${elapsed}ms:`, networkErr);
		throw new Error(
			`Network error: ${networkErr instanceof Error ? networkErr.message : "fetch failed"}`,
		);
	}

	const elapsed = Math.round(performance.now() - startTime);
	const data = await response.json();

	if (!response.ok) {
		logger.error(
			`${tag} FAILED (${response.status}) in ${elapsed}ms:`,
			data.error || data.message || data,
		);
		throw new Error(
			data.error || data.message || `Request failed (${response.status})`,
		);
	}

	if (import.meta.env.DEV) {
	}
	return data as T;
}

async function getRequest<T = unknown>(
	url: string,
	params: Record<string, string>,
): Promise<T | null> {
	// Guard: reject invalid accountIds (same rationale as postRequest above).
	const accountId = params.accountId;
	if (accountId !== undefined && (!accountId || accountId === "ALL")) {
		return null;
	}

	const tag = `[IG:${url.split("?")[0]!.replace("/instagram/", "")}]`;
	if (import.meta.env.DEV) {
	}
	const startTime = performance.now();

	const headers = await getAuthHeaders();
	const qs = new URLSearchParams(params);

	let response: Response;
	try {
		response = await fetch(`${API_BASE}${url}?${qs}`, {
			method: "GET",
			headers,
		});
	} catch (networkErr) {
		const elapsed = Math.round(performance.now() - startTime);
		logger.error(`${tag} Network error after ${elapsed}ms:`, networkErr);
		throw new Error(
			`Network error: ${networkErr instanceof Error ? networkErr.message : "fetch failed"}`,
		);
	}

	const elapsed = Math.round(performance.now() - startTime);
	const data = await response.json();

	if (!response.ok) {
		logger.error(
			`${tag} FAILED (${response.status}) in ${elapsed}ms:`,
			data.error || data.message || data,
		);
		throw new Error(
			data.error || data.message || `Request failed (${response.status})`,
		);
	}

	if (import.meta.env.DEV) {
	}
	return data as T;
}

export const instagramService = {
	// ── Insights ──────────────────────────────────────────────────────────

	getAccountInsights(accountId: string, period?: string) {
		return postRequest("/instagram/insights?action=account-insights", {
			accountId,
			...(period && { period }),
		});
	},

	getPostInsights(accountId: string, mediaId: string) {
		return postRequest("/instagram/insights?action=post-insights", {
			accountId,
			mediaId,
		});
	},

	getPublishingLimit(accountId: string) {
		return postRequest("/instagram/insights?action=publishing-limit", {
			accountId,
		});
	},

	// ── Collaboration ─────────────────────────────────────────────────────

	getCollaborationInvites(accountId: string) {
		return postRequest("/instagram/collaboration?action=list", {
			accountId,
		});
	},

	acceptCollaboration(accountId: string, mediaId: string) {
		return postRequest("/instagram/collaboration?action=accept", {
			accountId,
			mediaId,
		});
	},

	declineCollaboration(accountId: string, mediaId: string) {
		return postRequest("/instagram/collaboration?action=decline", {
			accountId,
			mediaId,
		});
	},

	// ── Media Management ─────────────────────────────────────────────────

	deleteMedia(accountId: string, mediaId: string, postId?: string) {
		return postRequest("/instagram/media?action=delete", {
			accountId,
			mediaId,
			...(postId && { postId }),
		});
	},

	getCollaborativeMedia(accountId: string, limit?: number) {
		return postRequest("/instagram/media?action=collaborative-list", {
			accountId,
			...(limit && { limit }),
		});
	},

	searchCollaborativeMedia(accountId: string, mediaId: string) {
		return postRequest("/instagram/media?action=collaborative-search", {
			accountId,
			mediaId,
		});
	},

	likeMedia(accountId: string, mediaId: string) {
		return postRequest("/instagram/media?action=like", {
			accountId,
			mediaId,
		});
	},

	unlikeMedia(accountId: string, mediaId: string) {
		return postRequest("/instagram/media?action=unlike", {
			accountId,
			mediaId,
		});
	},

	likeComment(accountId: string, commentId: string) {
		return postRequest("/instagram/media?action=like", {
			accountId,
			commentId,
		});
	},

	unlikeComment(accountId: string, commentId: string) {
		return postRequest("/instagram/media?action=unlike", {
			accountId,
			commentId,
		});
	},

	// ── Comments ──────────────────────────────────────────────────────────

	getComments(accountId: string, mediaId: string, after?: string) {
		return postRequest("/instagram/comments?action=list", {
			accountId,
			mediaId,
			...(after && { after }),
		});
	},

	replyToComment(accountId: string, commentId: string, message: string) {
		return postRequest("/instagram/comments?action=reply", {
			accountId,
			commentId,
			message,
		});
	},

	hideComment(accountId: string, commentId: string, hide: boolean) {
		return postRequest("/instagram/comments?action=hide", {
			accountId,
			commentId,
			hide,
		});
	},

	deleteComment(accountId: string, commentId: string) {
		return postRequest("/instagram/comments?action=delete", {
			accountId,
			commentId,
		});
	},

	toggleCommentEnabled(accountId: string, mediaId: string, enabled: boolean) {
		return postRequest("/instagram/comments?action=toggle-comments", {
			accountId,
			mediaId,
			enabled,
		});
	},

	privateReplyToComment(accountId: string, commentId: string, message: string) {
		return postRequest("/instagram/comments?action=private-reply", {
			accountId,
			commentId,
			message,
		});
	},

	// ── Mentions ──────────────────────────────────────────────────────────

	getTaggedMedia(accountId: string) {
		return postRequest("/instagram/mentions?action=tagged", {
			accountId,
		});
	},

	getMentionedMedia(accountId: string) {
		return postRequest("/instagram/mentions?action=mentioned", {
			accountId,
		});
	},

	// ── Business Discovery ────────────────────────────────────────────────

	getBusinessDiscovery(accountId: string, targetUsername: string) {
		return postRequest("/competitors?action=ig-business-discovery", {
			accountId,
			targetUsername,
		});
	},

	// ── Saved Media ─────────────────────────────────────────────────────

	getSavedMedia(accountId: string, limit?: number) {
		return postRequest("/instagram/saved", {
			accountId,
			...(limit && { limit }),
		});
	},

	// ── Stories ───────────────────────────────────────────────────────────

	getStories(accountId: string) {
		return getRequest("/instagram/stories", { accountId });
	},

	getStoryInsights(accountId: string, mediaId: string) {
		return getRequest("/instagram/stories", {
			accountId,
			action: "insights",
			mediaId,
		});
	},

	// ── Webhook Subscription ───────────────────────────────────────────

	subscribeToWebhooks(accountId: string) {
		return postRequest("/instagram/webhook-subscribe", { accountId });
	},

	// ── Messaging ─────────────────────────────────────────────────────────

	getConversations(accountId: string, after?: string) {
		return postRequest("/instagram/messages?action=conversations", {
			accountId,
			...(after && { after }),
		});
	},

	getConversationMessages(
		accountId: string,
		conversationId: string,
		after?: string,
	) {
		return postRequest("/instagram/messages?action=messages", {
			accountId,
			conversationId,
			...(after && { after }),
		});
	},

	sendMessage(
		accountId: string,
		recipientId: string,
		message: string,
		tag?: string,
	) {
		return postRequest("/instagram/messages?action=send", {
			accountId,
			recipientId,
			message,
			...(tag && { tag }),
		});
	},

	sendMediaMessage(
		accountId: string,
		recipientId: string,
		mediaUrl: string,
		mediaType: "image" | "video" | "audio" | "file",
	) {
		return postRequest("/instagram/messages?action=send-media", {
			accountId,
			recipientId,
			mediaUrl,
			mediaType,
		});
	},

	sendSenderAction(
		accountId: string,
		recipientId: string,
		action: "typing_on" | "typing_off" | "mark_seen",
	) {
		return postRequest("/instagram/messages?action=sender-action", {
			accountId,
			recipientId,
			action,
		});
	},

	sendMultiImageMessage(
		accountId: string,
		recipientId: string,
		imageUrls: string[],
	) {
		return postRequest("/instagram/messages?action=send-images", {
			accountId,
			recipientId,
			imageUrls,
		});
	},

	// ── DM Templates ──────────────────────────────────────────────────────

	getDMTemplates(category?: string) {
		return postRequest("/instagram/dm-templates?action=list", {
			...(category && { category }),
		});
	},

	createDMTemplate(
		name: string,
		content: string,
		category?: string,
		shortcut?: string,
	) {
		return postRequest("/instagram/dm-templates?action=create", {
			name,
			content,
			category,
			shortcut,
		});
	},

	updateDMTemplate(
		templateId: string,
		updates: {
			name?: string | undefined;
			content?: string | undefined;
			category?: string | undefined;
			shortcut?: string | undefined;
		},
	) {
		return postRequest("/instagram/dm-templates?action=update", {
			templateId,
			...updates,
		});
	},

	deleteDMTemplate(templateId: string) {
		return postRequest("/instagram/dm-templates?action=delete", { templateId });
	},

	incrementTemplateUse(templateId: string) {
		return postRequest("/instagram/dm-templates?action=increment-use", {
			templateId,
		});
	},

	// ── Auto-Responders ───────────────────────────────────────────────────

	getAutoResponders(accountId?: string) {
		return postRequest("/instagram/auto-responders?action=list", {
			...(accountId && { accountId }),
		});
	},

	createAutoResponder(data: {
		accountId: string;
		name: string;
		triggerType: "keyword" | "first_message" | "mention" | "story_reply";
		triggerKeywords?: string[] | undefined;
		templateId?: string | undefined;
		customResponse?: string | undefined;
		delaySeconds?: number | undefined;
		onlyNewConversations?: boolean | undefined;
		maxResponsesPerUser?: number | undefined;
		useAiResponse?: boolean | undefined;
		aiResponseIntent?: string | undefined;
		aiConversationDepth?: number | undefined;
		aiSystemPrompt?: string | null | undefined;
	}) {
		return postRequest("/instagram/auto-responders?action=create", data);
	},

	updateAutoResponder(
		responderId: string,
		updates: {
			name?: string | undefined;
			triggerType?: "keyword" | "first_message" | "mention" | "story_reply" | undefined;
			triggerKeywords?: string[] | undefined;
			templateId?: string | null | undefined;
			customResponse?: string | null | undefined;
			delaySeconds?: number | undefined;
			onlyNewConversations?: boolean | undefined;
			maxResponsesPerUser?: number | undefined;
			useAiResponse?: boolean | undefined;
			aiResponseIntent?: string | undefined;
			aiConversationDepth?: number | undefined;
			aiSystemPrompt?: string | null | undefined;
		},
	) {
		return postRequest("/instagram/auto-responders?action=update", {
			responderId,
			...updates,
		});
	},

	deleteAutoResponder(responderId: string) {
		return postRequest("/instagram/auto-responders?action=delete", {
			responderId,
		});
	},

	toggleAutoResponder(responderId: string, isEnabled: boolean) {
		return postRequest("/instagram/auto-responders?action=toggle", {
			responderId,
			isEnabled,
		});
	},
};
