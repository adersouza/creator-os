/**
 * Instagram Messaging — conversations, DMs, media messages, sender actions,
 * quick replies, generic templates, button templates, message reactions,
 * post sharing, heart stickers, and user profile retrieval.
 */

import {
	type ButtonTemplateButton,
	decrypt,
	getGraphBaseUrl,
	type IGConversation,
	type IGMessage,
	type IGPaging,
	type IGUserProfile,
	igFetch,
	logger,
	type QuickReply,
	type TemplateElement,
} from "./shared.js";

// ============================================================================
// Conversations
// ============================================================================

export async function getConversations(
	encryptedToken: string,
	igUserId: string,
	after?: string,
	loginType?: string,
): Promise<{
	success: boolean;
	conversations?: IGConversation[] | undefined;
	paging?: IGPaging | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		let url = `${graphBase}/v25.0/${igUserId}/conversations?fields=id,participants{id,username},messages.limit(1){id,message,created_time,from},updated_time&platform=instagram`;
		if (after) url += `&after=${after}`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:getConversations",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to fetch conversations",
			};
		}

		return {
			success: true,
			conversations: data.data || [],
			paging: data.paging,
		};
	} catch (error: unknown) {
		logger.error("IG getConversations error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

export async function getConversationMessages(
	encryptedToken: string,
	conversationId: string,
	after?: string,
	loginType?: string,
): Promise<{
	success: boolean;
	messages?: IGMessage[] | undefined;
	paging?: IGPaging | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		let url = `${graphBase}/v25.0/${conversationId}?fields=messages{id,message,from,to,created_time,is_unsupported}`;
		if (after) url += `&after=${after}`;

		const response = await igFetch(url, undefined, "igApi:getMessages", token);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to fetch messages",
			};
		}

		return {
			success: true,
			messages: data.messages?.data || [],
			paging: data.messages?.paging,
		};
	} catch (error: unknown) {
		logger.error("IG getConversationMessages error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

export async function sendMessage(
	encryptedToken: string,
	igUserId: string,
	recipientId: string,
	message: string,
	loginType?: string,
	tag?: string,
): Promise<{ success: boolean; messageId?: string | undefined; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const payload: Record<string, unknown> = {
			recipient: { id: recipientId },
			message: { text: message },
		};
		// HUMAN_AGENT tag required for messages sent outside the 24-hour messaging window
		if (tag) {
			payload.tag = tag;
		}

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/messages`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload),
			},
			"igApi:sendMessage",
			token,
		);

		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to send message",
			};
		}

		return { success: true, messageId: data.message_id };
	} catch (error: unknown) {
		logger.error("IG sendMessage error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Media Message (PDF, images, video, audio attachments)
// ============================================================================

export async function sendMediaMessage(
	encryptedToken: string,
	igUserId: string,
	recipientId: string,
	mediaUrl: string,
	mediaType: "image" | "video" | "audio" | "file",
	loginType?: string,
): Promise<{ success: boolean; messageId?: string | undefined; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const payload: Record<string, unknown> = {
			recipient: { id: recipientId },
			message: {
				attachment: {
					type: mediaType,
					payload: { url: mediaUrl },
				},
			},
		};

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/messages`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload),
			},
			"igApi:sendMediaMessage",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to send media message",
			};
		}
		return { success: true, messageId: data.message_id };
	} catch (error: unknown) {
		logger.error("IG sendMediaMessage error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Sender Actions (typing indicators, mark seen)
// ============================================================================

export async function sendSenderAction(
	encryptedToken: string,
	igUserId: string,
	recipientId: string,
	action: "typing_on" | "typing_off" | "mark_seen",
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/messages`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					recipient: { id: recipientId },
					sender_action: action,
				}),
			},
			"igApi:senderAction",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to send action",
			};
		}
		return { success: true };
	} catch (error: unknown) {
		logger.error("IG sendSenderAction error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Multi-Image DMs
// ============================================================================

export async function sendMultiImageMessage(
	encryptedToken: string,
	igUserId: string,
	recipientId: string,
	imageUrls: string[],
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
					recipient: { id: recipientId },
					message: {
						attachments: imageUrls.slice(0, 10).map((url) => ({
							type: "image",
							payload: { url },
						})),
					},
				}),
			},
			"igApi:sendMultiImageMessage",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to send images",
			};
		}
		return { success: true, messageId: data.message_id };
	} catch (error: unknown) {
		logger.error("IG sendMultiImageMessage error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Quick Replies
// ============================================================================

/**
 * Send a message with quick reply buttons (max 13, 20 chars each).
 * Not available on desktop. Buttons dismiss after tap.
 * Permissions: instagram_business_basic, instagram_business_manage_messages
 */
export async function sendQuickReplies(
	encryptedToken: string,
	igUserId: string,
	recipientId: string,
	text: string,
	quickReplies: QuickReply[],
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
					recipient: { id: recipientId },
					messaging_type: "RESPONSE",
					message: {
						text,
						quick_replies: quickReplies.slice(0, 13),
					},
				}),
			},
			"igApi:sendQuickReplies",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to send quick replies",
			};
		}
		return { success: true, messageId: data.message_id };
	} catch (error: unknown) {
		logger.error("IG sendQuickReplies error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Generic Template (carousel messages)
// ============================================================================

/**
 * Send a generic template message (carousel of cards with images, text, buttons).
 * Max 10 elements, 3 buttons per element, 80 char title/subtitle.
 * Not available on desktop.
 * Permissions: instagram_business_basic, instagram_business_manage_messages
 */
export async function sendGenericTemplate(
	encryptedToken: string,
	igUserId: string,
	recipientId: string,
	elements: TemplateElement[],
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
					recipient: { id: recipientId },
					message: {
						attachment: {
							type: "template",
							payload: {
								template_type: "generic",
								elements: elements.slice(0, 10).map((el) => ({
									...el,
									buttons: el.buttons?.slice(0, 3),
								})),
							},
						},
					},
				}),
			},
			"igApi:sendGenericTemplate",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to send template",
			};
		}
		return { success: true, messageId: data.message_id };
	} catch (error: unknown) {
		logger.error("IG sendGenericTemplate error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Message Reactions
// ============================================================================

/**
 * React or unreact to a message.
 * Pass reaction emoji to react, or omit/null to unreact.
 * Permissions: instagram_business_basic, instagram_business_manage_messages
 */
export async function sendMessageReaction(
	encryptedToken: string,
	igUserId: string,
	recipientId: string,
	messageId: string,
	reaction?: string | null,
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const reactionPayload: { message_id: string; reaction?: string | undefined } = {
			message_id: messageId,
		};
		if (reaction) {
			reactionPayload.reaction = reaction;
		}
		const payload: Record<string, unknown> = {
			recipient: { id: recipientId },
			sender_action: reaction ? "react" : "unreact",
			payload: reactionPayload,
		};

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/messages`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload),
			},
			"igApi:messageReaction",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to send reaction",
			};
		}
		return { success: true };
	} catch (error: unknown) {
		logger.error("IG sendMessageReaction error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Share Published Post via DM
// ============================================================================

/**
 * Send an app user's own published Instagram post as a DM.
 * The app user must own the post.
 * Permissions: instagram_business_basic, instagram_business_manage_messages
 */
export async function sendPostShare(
	encryptedToken: string,
	igUserId: string,
	recipientId: string,
	postId: string,
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
					recipient: { id: recipientId },
					message: {
						attachment: {
							type: "MEDIA_SHARE",
							payload: { id: postId },
						},
					},
				}),
			},
			"igApi:sendPostShare",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to share post",
			};
		}
		return { success: true, messageId: data.message_id };
	} catch (error: unknown) {
		logger.error("IG sendPostShare error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Send Heart Sticker
// ============================================================================

/**
 * Send a heart sticker (like_heart) in a DM conversation.
 */
export async function sendHeartSticker(
	encryptedToken: string,
	igUserId: string,
	recipientId: string,
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
					recipient: { id: recipientId },
					message: {
						attachment: { type: "like_heart" },
					},
				}),
			},
			"igApi:sendHeartSticker",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to send sticker",
			};
		}
		return { success: true, messageId: data.message_id };
	} catch (error: unknown) {
		logger.error("IG sendHeartSticker error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Button Template
// ============================================================================

/**
 * Send a button template message (text + up to 3 buttons).
 * Buttons can open URLs or trigger postback webhooks.
 */
export async function sendButtonTemplate(
	encryptedToken: string,
	igUserId: string,
	recipientId: string,
	text: string,
	buttons: ButtonTemplateButton[],
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
					recipient: { id: recipientId },
					message: {
						attachment: {
							type: "template",
							payload: {
								template_type: "button",
								text,
								buttons: buttons.slice(0, 3),
							},
						},
					},
				}),
			},
			"igApi:sendButtonTemplate",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to send button template",
			};
		}
		return { success: true, messageId: data.message_id };
	} catch (error: unknown) {
		logger.error("IG sendButtonTemplate error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// User Profile (messaging context — requires user consent via DM)
// ============================================================================

/**
 * Get an Instagram user's profile info using their Instagram-scoped ID (IGSID).
 * Only works if the user has sent a message to the business account (user consent required).
 * Permissions: instagram_business_basic, instagram_business_manage_messages
 */
export async function getUserProfile(
	encryptedToken: string,
	igsid: string,
	loginType?: string,
): Promise<{ success: boolean; profile?: IGUserProfile | undefined; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const fields =
			"name,username,profile_pic,follower_count,is_user_follow_business,is_business_follow_user,is_verified_user";
		const url = `${graphBase}/v25.0/${igsid}?fields=${fields}`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:getUserProfile",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to fetch user profile",
			};
		}

		return { success: true, profile: data as IGUserProfile };
	} catch (error: unknown) {
		logger.error("IG getUserProfile error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}
