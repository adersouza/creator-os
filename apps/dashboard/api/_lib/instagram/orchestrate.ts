/**
 * Instagram Publish Orchestrator
 *
 * Shared layer between callers and postToInstagram() that handles:
 * 1. Media accessibility check — pre-publish URL validation
 * 2. Core publish via postToInstagram()
 * 3. Post-publish: engagement sync and story auto-share
 *
 * Callers still handle their own: DB status updates, notifications,
 * cross-posting, retry logic (these vary per publish path).
 */

import { logger } from "../logger.js";
import type { IGPostData, IGPostingResult } from "./shared.js";

// ============================================================================
// Types
// ============================================================================

export interface IGPublishOptions {
	encryptedToken: string;
	igUserId: string;
	postData: IGPostData;
	encryptedFbPageToken?: string | undefined;
	loginType?: string | undefined;

	/** Check media URL accessibility before publishing */
	mediaCheck?: boolean | undefined;

	/** Post-publish actions (all fire-and-forget) */
	postPublish?: {
        		engagementSync?: {
                    			postId: string;
                    			accountId: string;
                    			userId?: string | undefined;
                    			source?: string | undefined;
                    		} | undefined;
        		storyAutoShare?: {
                    			enabled: boolean;
                    			mediaUrl: string;
                    		} | undefined;
        	} | undefined;
}

// ============================================================================
// Orchestrator
// ============================================================================

export async function orchestrateIGPublish(
	options: IGPublishOptions,
): Promise<IGPostingResult> {
	const {
		encryptedToken,
		igUserId,
		encryptedFbPageToken,
		loginType,
		mediaCheck,
		postPublish,
	} = options;

	// Shallow copy postData so we don't mutate the caller's object
	const postData: IGPostData = {
		...options.postData,
		children: options.postData.children?.map((c) => ({ ...c })),
	};

	const activeMediaUrls =
		postData.children?.map((child) => child.url) ??
		(postData.imageUrl
			? [postData.imageUrl]
			: postData.videoUrl
				? [postData.videoUrl]
				: []);

	// ── 1. Media Accessibility Check ─────────────────────────────────────
	if (mediaCheck && activeMediaUrls.length > 0) {
		try {
			const { checkMediaUrlAccessible } = await import("../mediaValidation.js");
			const mediaError = await checkMediaUrlAccessible(activeMediaUrls);
			if (mediaError) {
				return {
					success: false,
					error: mediaError,
					timestamp: new Date(),
				};
			}
		} catch (err) {
			// Fail-open: check failure → proceed with publish
			logger.warn("[orchestrateIG] Media check failed, proceeding", {
				error: err instanceof Error ? err.message : String(err),
			});
		}
	}

	// ── 2. Core Publish ──────────────────────────────────────────────────
	const { postToInstagram } = await import("./publishing.js");

	const result = await postToInstagram(
		encryptedToken,
		igUserId,
		postData,
		encryptedFbPageToken,
		loginType,
	);

	// ── 3. Post-Publish (fire-and-forget, only on success) ───────────────
	if (result.success && result.mediaId && postPublish) {
		// Engagement sync at 1h, 6h, 24h
		if (postPublish.engagementSync) {
			const { postId, accountId, userId, source } = postPublish.engagementSync;
			import("../qstashSchedule.js")
				.then(({ schedulePostPublishSyncs }) =>
					schedulePostPublishSyncs(
						postId,
						accountId,
						userId || "",
						"instagram",
						source || "orchestrator",
					),
				)
				.catch((err) =>
					logger.warn("[orchestrateIG] Engagement sync schedule failed", {
						error: String(err),
					}),
				);
		}

		// Auto-share IMAGE posts to Stories
		const storyAutoShare = postPublish.storyAutoShare;
		if (storyAutoShare?.enabled && storyAutoShare.mediaUrl) {
			import("../storyAutoShare.js")
				.then(({ autoShareToStory }) =>
					autoShareToStory(
						encryptedToken,
						igUserId,
						storyAutoShare.mediaUrl,
						loginType,
						encryptedFbPageToken,
					),
				)
				.catch((err) =>
					logger.warn("[orchestrateIG] Story auto-share failed", {
						error: String(err),
					}),
				);
		}
	}

	return result;
}
