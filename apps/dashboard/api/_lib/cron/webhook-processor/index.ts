/**
 * Webhook processor sub-module barrel export.
 * Re-exports all public API so consumers can import from a single path.
 */

// Batch processing loops
export {
	processIgWebhookEvents,
	processThreadsWebhookEvents,
} from "./event-loop.js";
export { handleIgWebhookEvent } from "./ig-processors.js";
// Retry / replay
export { markWebhookEventForRetry, scheduleWebhookReplay } from "./retry.js";
// Shared types
export type {
	AccountRow,
	IgAccountRow,
	IgAttachment,
	IgCommentPayload,
	IgMentionPayload,
	IgMessageReactionPayload,
	IgMessagingPayload,
	IgMessagingSeenPayload,
	IgWebhookEvent,
	PostOwnerRow,
	PostRow,
	ThreadsMentionPayload,
	ThreadsPublishPayload,
	ThreadsReplyPayload,
	ThreadsWebhookEvent,
	WebhookEventUpdate,
} from "./shared.js";
// Platform-specific event handlers
export { handleThreadsWebhookEvent } from "./threads-processors.js";
