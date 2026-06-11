// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Auto-share a published IG post to Stories.
 * Called after successful IG image post publish.
 * Uses the same image URL to create a Story post.
 *
 * Fire-and-forget: failures are logged but never block the main publish.
 */

import { logger } from "./logger.js";

/** Short Story captions — rotate randomly. Keep it 1-3 words max. */
const STORY_CAPTIONS = [
	"recent ;)",
	"lmr",
	"new 💋",
	"🤍",
	"hi",
	"just posted",
	"👀",
	"go like",
	"😏",
	"yours",
	"💕",
	"posted",
	"recent",
	"tap in",
	"🌙",
];

export async function autoShareToStory(
	encryptedToken: string,
	igUserId: string,
	imageUrl: string,
	loginType?: string,
	facebookPageToken?: string,
): Promise<{ success: boolean; storyId?: string | undefined; error?: string | undefined }> {
	try {
		// Lazy imports for Vercel cold-start performance
		const { decrypt } = await import("./encryption.js");
		const { withRetry } = await import("./retryUtils.js");
		const { fetchContainerWithRetry } = await import("./instagram/shared.js");

		const graphBase =
			loginType === "facebook"
				? "https://graph.facebook.com"
				: "https://graph.instagram.com";

		// Stories with facebook_login use the FB Page token
		const tokenSource =
			loginType === "facebook" && facebookPageToken
				? facebookPageToken
				: encryptedToken;
		if (!tokenSource) {
			return { success: false, error: "No token available for story share" };
		}
		const token = decrypt(tokenSource);

		// Step 1: Create Story container with short caption
		const caption =
			STORY_CAPTIONS[Math.floor(Math.random() * STORY_CAPTIONS.length)];
		const containerParams: Record<string, string> = {
			media_type: "STORIES",
			image_url: imageUrl,
			caption: caption!,
		};

		const result = await fetchContainerWithRetry(
			`${graphBase}/v25.0/${igUserId}/media`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(containerParams),
			},
			"storyAutoShare:createContainer",
			token,
		);

		if (!result.ok) {
			const errMsg =
				((result.data?.error as Record<string, unknown>)?.message as string) ||
				"Failed to create story container";
			logger.warn("[storyAutoShare] Container creation failed", {
				igUserId,
				error: errMsg,
				errorCategory: result.classified?.category,
			});
			return { success: false, error: errMsg };
		}

		const containerId = result.data.id;
		if (!containerId) {
			return { success: false, error: "No container ID returned for story" };
		}

		logger.info("[storyAutoShare] Story container created", { containerId });

		// Step 2: Poll container status (images are fast — 10 attempts, 3s interval)
		const statusUrl = `${graphBase}/v25.0/${containerId}?fields=status_code,status`;
		let containerReady = false;

		for (let attempt = 0; attempt < 10; attempt++) {
			await new Promise((resolve) => setTimeout(resolve, 3000));

			let statusCode: string | undefined;
			let statusData: Record<string, unknown> = {};
			try {
				const statusRes = await withRetry(
					() =>
						fetch(statusUrl, {
							headers: { Authorization: `Bearer ${token}` },
							signal: AbortSignal.timeout(15_000),
						}),
					{ label: "storyAutoShare:pollContainer" },
				);
				statusData = await statusRes.json();
				statusCode = statusData.status_code as string | undefined;
			} catch (pollErr) {
				// Timeout or network blip — log and retry
				logger.warn("[storyAutoShare] Poll attempt timed out, retrying", {
					containerId,
					attempt,
					error: pollErr instanceof Error ? pollErr.message : String(pollErr),
				});
				continue;
			}

			if (statusCode === "FINISHED") {
				containerReady = true;
				break;
			}
			if (statusCode === "ERROR" || statusCode === "EXPIRED") {
				logger.warn("[storyAutoShare] Container failed", {
					containerId,
					status: statusCode,
					error: statusData.status,
				});
				return {
					success: false,
					error: `Story container ${statusCode}: ${statusData.status || "unknown"}`,
				};
			}
			// IN_PROGRESS or unknown — keep polling
		}

		if (!containerReady) {
			logger.warn("[storyAutoShare] Container poll timed out", { containerId });
			return { success: false, error: "Story container processing timed out" };
		}

		// Step 3: Publish the Story
		const publishResponse = await withRetry(
			async () => {
				const res = await fetch(
					`${graphBase}/v25.0/${igUserId}/media_publish?creation_id=${containerId}`,
					{
						method: "POST",
						headers: { Authorization: `Bearer ${token}` },
						signal: AbortSignal.timeout(30_000),
					},
				);
				return res;
			},
			{ label: "storyAutoShare:publish" },
		);

		const publishData = await publishResponse.json();

		if (!publishResponse.ok || publishData.error) {
			const errMsg = publishData.error?.message || "Failed to publish story";
			logger.warn("[storyAutoShare] Publish failed", {
				containerId,
				error: errMsg,
			});
			return { success: false, error: errMsg };
		}

		logger.info("[storyAutoShare] Story published", {
			storyId: publishData.id,
			igUserId,
		});

		return { success: true, storyId: publishData.id };
	} catch (error: unknown) {
		const errMsg = error instanceof Error ? error.message : String(error);
		logger.error("[storyAutoShare] Unexpected error", { error: errMsg });
		return { success: false, error: errMsg };
	}
}
