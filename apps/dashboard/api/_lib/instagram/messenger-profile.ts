/**
 * Instagram Messenger Profile — persistent menus, ice breakers,
 * and welcome message flows (CRUD operations).
 */

import {
	decrypt,
	getGraphBaseUrl,
	type IceBreakerLocale,
	type IGWelcomeFlow,
	igFetch,
	logger,
	type PersistentMenuLocale,
	type WelcomeFlowQuickReply,
} from "./shared.js";

// ============================================================================
// Persistent Menu (CRUD via messenger_profile)
// ============================================================================

/**
 * Set the persistent menu for an IG professional account.
 * Menu items are always visible in the DM conversation.
 */
export async function setPersistentMenu(
	encryptedToken: string,
	igUserId: string,
	menuItems: PersistentMenuLocale[],
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/messenger_profile`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					platform: "instagram",
					persistent_menu: menuItems,
				}),
			},
			"igApi:setPersistentMenu",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to set persistent menu",
			};
		}
		return { success: true };
	} catch (error: unknown) {
		logger.error("IG setPersistentMenu error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * Get the persistent menu for an IG professional account.
 */
export async function getPersistentMenu(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<{ success: boolean; menu?: unknown | undefined; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const url = `${graphBase}/v25.0/${igUserId}/messenger_profile?fields=persistent_menu&platform=instagram`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:getPersistentMenu",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to get persistent menu",
			};
		}
		return { success: true, menu: data.data };
	} catch (error: unknown) {
		logger.error("IG getPersistentMenu error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * Delete the persistent menu for an IG professional account.
 */
export async function deletePersistentMenu(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/messenger_profile`,
			{
				method: "DELETE",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ fields: ["persistent_menu"] }),
			},
			"igApi:deletePersistentMenu",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to delete persistent menu",
			};
		}
		return { success: true };
	} catch (error: unknown) {
		logger.error("IG deletePersistentMenu error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Ice Breakers (CRUD via messenger_profile)
// ============================================================================

/**
 * Set ice breakers (max 4 FAQ-style questions) for an IG professional account.
 * Shown to users starting a new conversation.
 */
export async function setIceBreakers(
	encryptedToken: string,
	igUserId: string,
	iceBreakers: IceBreakerLocale[],
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/messenger_profile`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					platform: "instagram",
					ice_breakers: iceBreakers.slice(0, 4),
				}),
			},
			"igApi:setIceBreakers",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to set ice breakers",
			};
		}
		return { success: true };
	} catch (error: unknown) {
		logger.error("IG setIceBreakers error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * Get ice breakers for an IG professional account.
 */
export async function getIceBreakers(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<{ success: boolean; iceBreakers?: unknown | undefined; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const url = `${graphBase}/v25.0/${igUserId}/messenger_profile?fields=ice_breakers`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:getIceBreakers",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to get ice breakers",
			};
		}
		return { success: true, iceBreakers: data.data };
	} catch (error: unknown) {
		logger.error("IG getIceBreakers error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * Delete ice breakers for an IG professional account.
 */
export async function deleteIceBreakers(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/messenger_profile`,
			{
				method: "DELETE",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ fields: ["ice_breakers"] }),
			},
			"igApi:deleteIceBreakers",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to delete ice breakers",
			};
		}
		return { success: true };
	} catch (error: unknown) {
		logger.error("IG deleteIceBreakers error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Welcome Message Flows (CRUD for ads integration)
// ============================================================================

/**
 * Create a welcome message flow for Click-to-Instagram-Direct ads.
 */
export async function createWelcomeMessageFlow(
	encryptedToken: string,
	igUserId: string,
	name: string,
	welcomeText: string,
	quickReplies: WelcomeFlowQuickReply[],
	loginType?: string,
): Promise<{ success: boolean; flowId?: string | undefined; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/welcome_message_flows`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					eligible_platforms: ["instagram"],
					name,
					welcome_message_flow: [
						{
							message: {
								text: welcomeText,
								quick_replies: quickReplies,
							},
						},
					],
				}),
			},
			"igApi:createWelcomeFlow",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to create welcome flow",
			};
		}
		return { success: true, flowId: data.flow_id };
	} catch (error: unknown) {
		logger.error("IG createWelcomeMessageFlow error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * List welcome message flows for an IG professional account.
 */
export async function getWelcomeMessageFlows(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<{ success: boolean; flows?: IGWelcomeFlow[] | undefined; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const url = `${graphBase}/v25.0/${igUserId}/welcome_message_flows`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:getWelcomeFlows",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to get welcome flows",
			};
		}
		return {
			success: true,
			flows: Array.isArray(data) ? data : data.data || [],
		};
	} catch (error: unknown) {
		logger.error("IG getWelcomeMessageFlows error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * Delete a welcome message flow.
 */
export async function deleteWelcomeMessageFlow(
	encryptedToken: string,
	igUserId: string,
	flowId: string,
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/welcome_message_flows?flow_id=${flowId}`,
			{ method: "DELETE" },
			"igApi:deleteWelcomeFlow",
			token,
		);

		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to delete welcome flow",
			};
		}
		return { success: true };
	} catch (error: unknown) {
		logger.error("IG deleteWelcomeMessageFlow error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}
