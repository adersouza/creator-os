/**
 * Shared constants for the Juno33 API layer.
 *
 * Centralises magic strings so they are defined once and imported everywhere.
 */

// ============================================================================
// Post Statuses
// ============================================================================

export const POST_STATUS = {
	SCHEDULED: "scheduled",
	PUBLISHING: "publishing",
	PUBLISHED: "published",
	FAILED: "failed",
	DEAD_LETTER: "dead_letter",
	DRAFT: "draft",
	PENDING_APPROVAL: "pending_approval",
} as const;

export type PostStatus = (typeof POST_STATUS)[keyof typeof POST_STATUS];

// ============================================================================
// Notification Types
// ============================================================================

export const NOTIFICATION_TYPE = {
	POST_PUBLISHED: "post_published",
	POST_FAILED: "post_failed",
	COMMENT_RECEIVED: "comment_received",
	COMMENT_REPLIED: "comment_replied",
	DM_RECEIVED: "dm_received",
	DM_SENT: "dm_sent",
	REPLY_RECEIVED: "reply_received",
	REPLY_SENT: "reply_sent",
	MENTION_RECEIVED: "mention_received",
	TOKEN_REAUTH_NEEDED: "token_reauth_needed",
} as const;

export type NotificationType =
	(typeof NOTIFICATION_TYPE)[keyof typeof NOTIFICATION_TYPE];

// ============================================================================
// Platforms
// ============================================================================

export const PLATFORM = {
	THREADS: "threads",
	INSTAGRAM: "instagram",
} as const;

export type Platform = (typeof PLATFORM)[keyof typeof PLATFORM];

// ============================================================================
// Account Statuses
// ============================================================================

export const ACCOUNT_STATUS = {
	ACTIVE: "active",
	SUSPENDED: "suspended",
} as const;

// ============================================================================
// Approval Statuses
// ============================================================================

export const APPROVAL_STATUS = {
	APPROVED: "approved",
	REJECTED: "rejected",
} as const;

// ============================================================================
// DLQ / Queue Statuses
// ============================================================================

export const QUEUE_STATUS = {
	QUEUED: "queued",
	PENDING: "pending",
	PROCESSING: "processing",
	COMPLETED: "completed",
	FAILED: "failed",
	DEAD_LETTER: "dead_letter",
} as const;

// ============================================================================
// IG Container Statuses
// ============================================================================

export const IG_CONTAINER_STATUS = {
	IN_PROGRESS: "IN_PROGRESS",
	FINISHED: "FINISHED",
	EXPIRED: "EXPIRED",
	ERROR: "ERROR",
	PUBLISHED: "PUBLISHED",
} as const;
