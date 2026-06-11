/**
 * Instagram Collaboration Invites — get, accept, and decline collaboration invites.
 */

import {
	decrypt,
	getGraphBaseUrl,
	type IGCollaborationInvite,
	igFetch,
	logger,
} from "./shared.js";

// ============================================================================
// Collaboration Invites
// ============================================================================

export async function getCollaborationInvites(
	encryptedToken: string,
	igUserId: string,
	loginType?: string,
): Promise<{
	success: boolean;
	invites?: IGCollaborationInvite[] | undefined;
	error?: string | undefined;
}> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const url = `${graphBase}/v25.0/${igUserId}/collaboration_invites?fields=media_id,media_owner_username,caption,media_url`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:collabInvites",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to fetch collaboration invites",
			};
		}

		return { success: true, invites: data.data || [] };
	} catch (error: unknown) {
		logger.error("IG getCollaborationInvites error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

export async function acceptCollaboration(
	encryptedToken: string,
	igUserId: string,
	mediaId: string,
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		// Per docs: POST /{ig_user_id}/collaboration_invites with media_id and accept=true
		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/collaboration_invites`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					media_id: mediaId,
					accept: "true",
				}),
			},
			"igApi:acceptCollab",
			token,
		);

		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to accept collaboration",
			};
		}

		return { success: true };
	} catch (error: unknown) {
		logger.error("IG acceptCollaboration error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

export async function declineCollaboration(
	encryptedToken: string,
	igUserId: string,
	mediaId: string,
	loginType?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	try {
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);

		// Per docs: POST /{ig_user_id}/collaboration_invites with media_id and accept=false
		const response = await igFetch(
			`${graphBase}/v25.0/${igUserId}/collaboration_invites`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					media_id: mediaId,
					accept: "false",
				}),
			},
			"igApi:declineCollab",
			token,
		);

		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to decline collaboration",
			};
		}

		return { success: true };
	} catch (error: unknown) {
		logger.error("IG declineCollaboration error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}
