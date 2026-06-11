/**
 * Reply Response Time Tracker
 *
 * Tracks how quickly a user replies to comments on their posts.
 * Updates a running average on the post record.
 */

import { logger } from "./logger.js";
import { getSupabase } from "./supabase.js";

/**
 * Track a reply response time and update the post's running average.
 *
 * @param postId - Internal post UUID
 * @param commentTimestamp - When the inbound comment was received (ISO string or Date)
 * @param replyTimestamp - When the outbound reply was sent (ISO string or Date)
 */
export async function trackReplyResponse(
	postId: string,
	commentTimestamp: string | Date,
	replyTimestamp: string | Date,
): Promise<void> {
	try {
		const commentTime = new Date(commentTimestamp).getTime();
		const replyTime = new Date(replyTimestamp).getTime();

		// #609: Guard against NaN timestamps corrupting running average
		if (Number.isNaN(commentTime) || Number.isNaN(replyTime)) {
			logger.warn("Invalid timestamp in reply tracking, skipping", {
				postId,
				commentTimestamp: String(commentTimestamp),
				replyTimestamp: String(replyTimestamp),
			});
			return;
		}

		if (replyTime <= commentTime) {
			logger.warn("Reply timestamp is before comment timestamp, skipping", {
				postId,
			});
			return;
		}

		const responseMinutes = (replyTime - commentTime) / (1000 * 60);

		// Cap at 7 days to avoid skewing from ancient replies
		if (responseMinutes > 7 * 24 * 60) {
			logger.info("Reply response time >7d, skipping", {
				postId,
				responseMinutes,
			});
			return;
		}

		const db = getSupabase();

		// Fetch current running average
		const { data: post, error: fetchError } = await db
			.from("posts")
			.select("avg_reply_response_mins, reply_response_count")
			.eq("id", postId)
			.maybeSingle();

		if (fetchError || !post) {
			logger.warn("Could not fetch post for reply tracking", {
				postId,
				error: fetchError?.message,
			});
			return;
		}

		const postData = post as {
			avg_reply_response_mins?: number | null | undefined;
			reply_response_count?: number | null | undefined;
		};
		const currentAvg = postData.avg_reply_response_mins ?? 0;
		const currentCount = postData.reply_response_count ?? 0;

		// Compute new running average
		const newCount = currentCount + 1;
		const newAvg = (currentAvg * currentCount + responseMinutes) / newCount;

		const { error: updateError } = await db
			.from("posts")
			.update({
				avg_reply_response_mins: Math.round(newAvg * 100) / 100,
				reply_response_count: newCount,
			})
			.eq("id", postId);

		if (updateError) {
			logger.error("Failed to update reply response time", {
				postId,
				error: updateError.message,
			});
			return;
		}

		logger.info("Tracked reply response time", {
			postId,
			responseMinutes: Math.round(responseMinutes),
			newAvg: Math.round(newAvg),
		});
	} catch (err: unknown) {
		logger.error("Reply response tracker error", {
			postId,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}
