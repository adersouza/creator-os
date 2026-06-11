/**
 * Instagram Batch Requests — Meta Graph API batch endpoint.
 */

import {
	type BatchRequest,
	type BatchResponse,
	decrypt,
	igFetch,
	logger,
} from "./shared.js";

// ============================================================================
// Batch Requests
// ============================================================================

export async function batchRequest(
	encryptedToken: string,
	requests: BatchRequest[],
	loginType?: string,
): Promise<{ success: boolean; responses?: BatchResponse[] | undefined; error?: string | undefined }> {
	try {
		// Batch API only works on graph.facebook.com — see metaApiConfig.ts
		const { isBatchSupported } = await import("../metaApiConfig.js");
		if (!isBatchSupported(loginType)) {
			return {
				success: false,
				error: "Batch API not supported for Instagram Business Login",
			};
		}
		const token = decrypt(encryptedToken);

		// Meta Batch API expects form-encoded body with batch as a JSON string.
		// access_token MUST be in the form body — the batch endpoint does not
		// honour the Authorization: Bearer header, producing an empty 200 response.
		const params = new URLSearchParams();
		params.set("access_token", token);
		params.set("batch", JSON.stringify(requests));
		const response = await igFetch(
			"https://graph.facebook.com/v25.0/",
			{
				method: "POST",
				headers: { "Content-Type": "application/x-www-form-urlencoded" },
				body: params.toString(),
			},
			"igApi:batch",
			// token NOT passed here — already in body, avoids double-auth confusion
		);

		const text = await response.text();
		let data: unknown;
		try {
			data = JSON.parse(text);
		} catch {
			return {
				success: false,
				error: `Invalid JSON response (${text.length} chars)`,
			};
		}

		if (!response.ok || (data as { error?: { message?: string | undefined } | undefined }).error) {
			return {
				success: false,
				error:
					(data as { error?: { message?: string | undefined } | undefined }).error?.message ||
					"Batch request failed",
			};
		}

		return { success: true, responses: data as BatchResponse[] };
	} catch (error: unknown) {
		logger.error("IG batch request error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}
