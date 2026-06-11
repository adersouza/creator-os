/**
 * Media operations
 */

import { safeJsonParse, supabase } from "./shared.js";

interface MediaRefreshResponse {
	mediaUrls?: string[] | undefined;
	refreshed?: boolean | undefined;
	error?: string | undefined;
}

export async function refreshPostMedia(
	postId: string,
): Promise<{ mediaUrls: string[]; refreshed: boolean }> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	if (!session?.access_token) {
		throw new Error("Not authenticated");
	}

	const response = await fetch("/api/media-refresh", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session.access_token}`,
		},
		body: JSON.stringify({ postId }),
	});

	const data = await safeJsonParse<MediaRefreshResponse>(
		response,
		"Media refresh",
	);

	if (!response.ok) {
		throw new Error(data.error || "Failed to refresh media");
	}

	return {
		mediaUrls: data.mediaUrls || [],
		refreshed: data.refreshed || false,
	};
}
