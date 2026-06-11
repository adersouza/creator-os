/**
 * Shared types, interfaces, and utility functions for webhook processing.
 * Used by all webhook-processor sub-modules.
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import type { Platform } from "../../platform.js";

// ============================================================================
// Row / API Types
// ============================================================================

/** Minimal account row returned from `accounts` table selects. */
export interface AccountRow {
	id: string;
	user_id: string;
}

/** Minimal post row returned from `posts` table selects. */
export interface PostRow {
	id: string;
	account_id?: string | undefined;
}

/** Minimal post-owner row returned from `posts` user_id select. */
export interface PostOwnerRow {
	user_id: string;
}

/** Minimal instagram_accounts row (narrow select). */
export interface IgAccountRow {
	id: string;
	user_id: string;
	instagram_user_id: string;
	instagram_access_token_encrypted?: string | undefined;
	login_type?: string | undefined;
}

/** Threads webhook event row as stored in `threads_webhook_events`. */
export interface ThreadsWebhookEvent {
	id: string;
	event_type: string;
	threads_user_id: string;
	payload: Record<string, unknown>;
	retry_count?: number | undefined;
	received_at?: string | undefined;
}

/** Instagram webhook event row as stored in `ig_webhook_events`. */
export interface IgWebhookEvent {
	id: string;
	event_type: string;
	ig_user_id: string;
	payload: Record<string, unknown>;
	retry_count?: number | undefined;
	received_at?: string | undefined;
}

/** Attachment entry inside an IG messaging payload. */
export interface IgAttachment {
	type: string;
	payload?: { url?: string | undefined } | undefined;
}

/** Typed payload for Threads reply webhook events. */
export interface ThreadsReplyPayload {
	id?: string | undefined;
	text?: string | undefined;
	timestamp?: string | number | undefined;
	username?: string | undefined;
	profile_picture_url?: string | undefined;
	from?: { id?: string | undefined; username?: string | undefined; profile_picture_url?: string | undefined } | undefined;
	replied_to?: { id?: string | undefined } | undefined;
	root_post?: { id?: string | undefined; owner_id?: string | undefined; username?: string | undefined } | undefined;
}

/** Typed payload for Threads mention webhook events. */
export interface ThreadsMentionPayload {
	id?: string | undefined;
	text?: string | undefined;
	timestamp?: string | number | undefined;
	username?: string | undefined;
	profile_picture_url?: string | undefined;
	permalink?: string | undefined;
	from?: { id?: string | undefined; username?: string | undefined; profile_picture_url?: string | undefined } | undefined;
}

/** Typed payload for Threads publish webhook events. */
export interface ThreadsPublishPayload {
	id?: string | undefined;
	text?: string | undefined;
	timestamp?: string | number | undefined;
	media_type?: string | undefined;
	media_url?: string | undefined;
	permalink?: string | undefined;
}

/** Typed payload for IG comment webhook events. */
export interface IgCommentPayload {
	id?: string | undefined;
	comment_id?: string | undefined;
	media_id?: string | undefined;
	text?: string | undefined;
	created_time?: string | undefined;
	username?: string | undefined;
	from?: { username?: string | undefined } | undefined;
	media?: { id?: string | undefined } | undefined;
}

/** Typed payload for IG mention webhook events. */
export interface IgMentionPayload {
	id?: string | undefined;
	media_id?: string | undefined;
	caption?: string | undefined;
	text?: string | undefined;
	timestamp?: string | number | undefined;
	permalink?: string | undefined;
	media_type?: string | undefined;
	username?: string | undefined;
	from?: { id?: string | undefined; username?: string | undefined } | undefined;
	media?: { id?: string | undefined } | undefined;
}

/** Typed payload for IG messaging (DM) webhook events. */
export interface IgMessagingPayload {
	sender?: { id?: string | undefined } | undefined;
	from?: { id?: string | undefined } | undefined;
	thread_id?: string | undefined;
	conversation_id?: string | undefined;
	text?: string | undefined;
	message?: {
        		mid?: string | undefined;
        		text?: string | undefined;
        		attachments?: IgAttachment[] | undefined;
        		is_echo?: boolean | undefined;
        	} | undefined;
}

/** Typed payload for IG messaging_seen webhook events. */
export interface IgMessagingSeenPayload {
	sender?: { id?: string | undefined } | undefined;
	read?: { mid?: string | undefined } | undefined;
}

/** Typed payload for IG message_reactions webhook events. */
export interface IgMessageReactionPayload {
	sender?: { id?: string | undefined } | undefined;
	reaction?: {
        		action?: string | undefined;
        		emoji?: string | undefined;
        		reaction?: string | undefined;
        		mid?: string | undefined;
        	} | undefined;
}

/** Update payload for dead-letter / retry columns (partial, not all cols in DB type). */
export interface WebhookEventUpdate {
	processed?: boolean | undefined;
	processed_at?: string | undefined;
	error?: string | undefined;
	last_error?: string | undefined;
	dead_letter?: boolean | undefined;
	dead_letter_at?: string | undefined;
	dead_letter_reason?: string | undefined;
	retry_count?: number | undefined;
	next_retry_at?: string | undefined;
	lifetime_retry_count?: number | undefined;
}

// ============================================================================
// Constants
// ============================================================================

export const WEBHOOK_TABLES: Record<Platform, string> = {
	threads: "threads_webhook_events",
	instagram: "ig_webhook_events",
};

// Leave 10s buffer before Vercel's 60s hard kill
export const MAX_EXECUTION_TIME = 50_000;

// ============================================================================
// Utility Functions
// ============================================================================

/** Parse webhook timestamp -- handles both ISO 8601 strings and Unix seconds */
export function parseWebhookTimestamp(ts: string | number): string {
	if (typeof ts === "string") {
		const d = new Date(ts);
		if (!Number.isNaN(d.getTime())) return d.toISOString();
	}
	if (typeof ts === "number") {
		// Unix seconds (10 digits) vs milliseconds (13 digits)
		const ms = ts > 1e12 ? ts : ts * 1000;
		const d = new Date(ms);
		if (!Number.isNaN(d.getTime())) return d.toISOString();
	}
	return new Date().toISOString();
}

export async function getAccountToken(
	supabase: SupabaseClient,
	accountId: string,
): Promise<string> {
	const { data } = await supabase
		.from("accounts")
		.select("threads_access_token_encrypted")
		.eq("id", accountId)
		.maybeSingle();
	return data?.threads_access_token_encrypted || "";
}
