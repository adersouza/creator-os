/**
 * User-Friendly Error Messages
 *
 * Provides actionable error messages instead of generic failures.
 */

export const INSTAGRAM_ERROR_MESSAGES = {
  // Collaboration
  COLLABORATION_ACCEPT_FAILED: "Unable to accept collaboration invite. Please check your connection and try again.",
  COLLABORATION_DECLINE_FAILED: "Unable to decline collaboration invite. Please try again later.",
  COLLABORATION_FETCH_FAILED: "Unable to load collaboration invites. Your session may have expired. Try reconnecting your Instagram account.",

  // Comments
  COMMENTS_LOAD_FAILED: "Unable to load comments. The post may have been deleted or your session expired. Try reconnecting your Instagram account.",
  COMMENT_REPLY_FAILED: "Failed to post reply. Please check your message and try again.",
  COMMENT_HIDE_FAILED: "Unable to hide comment. Please try again.",
  COMMENT_DELETE_FAILED: "Unable to delete comment. You can only delete comments on your own posts.",

  // Messages
  MESSAGE_SEND_FAILED: "Message failed to send. Please check your connection and try again.",
  CONVERSATIONS_LOAD_FAILED: "Unable to load conversations. Please try reconnecting your Instagram account.",
  MESSAGES_LOAD_FAILED: "Unable to load messages. This conversation may no longer be available.",

  // Stories
  STORIES_LOAD_FAILED: "Unable to load stories. Stories are only available for 24 hours after posting.",
  STORY_INSIGHTS_FAILED: "Unable to load story insights. Insights may not be available yet (can take up to 24 hours).",

  // Hashtags
  HASHTAG_SEARCH_FAILED: "Hashtag search failed. This feature requires a Facebook-linked Instagram Business account.",
  HASHTAG_LIMIT_REACHED: "Hashtag search limit reached: 30 unique hashtags per 7 days. Try again later or search a previously used hashtag.",

  // General
  SESSION_EXPIRED: "Your Instagram session has expired. Please reconnect your account.",
  RATE_LIMIT: "Too many requests. Please wait a moment and try again.",
  NETWORK_ERROR: "Network error. Please check your internet connection and try again.",
  GENERIC_ERROR: "An unexpected error occurred. Please try again. If the problem persists, contact support.",
} as const;

export type InstagramErrorType = keyof typeof INSTAGRAM_ERROR_MESSAGES;

/**
 * Get user-friendly error message
 */
export function getErrorMessage(
  errorType: InstagramErrorType,
  fallback?: string
): string {
  return INSTAGRAM_ERROR_MESSAGES[errorType] || fallback || INSTAGRAM_ERROR_MESSAGES.GENERIC_ERROR;
}

/**
 * Parse API error and return user-friendly message
 */
export function parseApiError(error: any): string {
  const message = error?.message || error?.error || String(error);

  // Check for specific error patterns
  if (message.includes("session") || message.includes("token") || message.includes("expired")) {
    return INSTAGRAM_ERROR_MESSAGES.SESSION_EXPIRED;
  }

  if (message.includes("rate limit") || message.includes("429")) {
    return INSTAGRAM_ERROR_MESSAGES.RATE_LIMIT;
  }

  if (message.includes("network") || message.includes("fetch")) {
    return INSTAGRAM_ERROR_MESSAGES.NETWORK_ERROR;
  }

  // Return message with helpful context
  return message || INSTAGRAM_ERROR_MESSAGES.GENERIC_ERROR;
}
