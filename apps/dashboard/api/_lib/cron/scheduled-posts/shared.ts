/**
 * Shared types, interfaces, and constants used across scheduled-posts sub-modules.
 */

import type { Json } from "../../../../types/supabase.js";
import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";

// ============================================================================
// Database accessor
// ============================================================================

export const db = () => getSupabase();

type NotificationInsert = {
	user_id: string;
	type: string;
	title: string;
	message: string;
	read: boolean;
	data?: Json;
};

export async function safeInsertNotification(
	notification: NotificationInsert,
	context: Record<string, unknown>,
): Promise<void> {
	try {
		const notificationRow = {
			user_id: notification.user_id,
			type: notification.type,
			title: notification.title,
			message: notification.message,
			read: notification.read,
			...(notification.data !== undefined ? { data: notification.data } : {}),
		};
		await db().from("notifications").insert(notificationRow);
	} catch (error) {
		logger.warn("[scheduled-posts] Notification insert failed after publish", {
			...context,
			error: error instanceof Error ? error.message : String(error),
		});
	}
}

// ============================================================================
// Configuration
// ============================================================================

export const config = {
	maxDuration: 60, // 1 minute max
};

// Rate limits per Threads API documentation (250/day official)
export const RATE_LIMITS = {
	POSTS_PER_HOUR: 25,
	POSTS_PER_DAY: 250,
};

// ============================================================================
// Types
// ============================================================================

export interface RateLimitResult {
	allowed: boolean;
	reason: string | null;
	posts_this_hour: number;
	posts_today: number;
}

export interface CrossPostRecord {
	id: string;
	user_id: string;
	content?: string | null | undefined;
	media_urls?: string[] | null | undefined;
	media_type?: string | null | undefined;
	metadata?: Json | Record<string, unknown> | null | undefined;
	account_id?: string | null | undefined;
}

export interface ProcessingStats {
	found: number;
	published: number;
	failed: number;
	retried: number;
	rateLimited: number;
	errors: string[];
}

// ============================================================================
// Transient error detection
// ============================================================================

export type { ClassifiedError, MetaErrorCategory } from "../../metaErrors.js";
// Re-export structured error classifier for callers that have parsed error objects
export {
	classifyMetaError,
	isAuthError,
	isTransientMetaError,
} from "../../metaErrors.js";

/** Transient error patterns — legacy string-matching fallback.
 *  Prefer classifyMetaError() with structured { code, subcode, type } when available.
 *  Meta returns code=1 / code=2 with various canonical messages — both are
 *  transient (Meta infra) but past payloads have stripped the code, leaving
 *  only the message. Match on those messages so string-only callers don't
 *  incorrectly mark posts as permanent failures. */
const TRANSIENT_ERROR_PATTERNS = [
	"timeout",
	"ETIMEDOUT",
	"ECONNRESET",
	"ECONNREFUSED",
	"rate limit",
	"too many requests",
	"429",
	"internal server error",
	"500",
	"502",
	"503",
	"504",
	"temporarily unavailable",
	"temporary meta server error",
	"an unknown error occurred",
	"unknown error",
	"unexpected error",
	"service temporarily unavailable",
	"please retry your request",
];

/** @deprecated Use classifyMetaError() or isTransientMetaError() for structured errors */
export function isTransientError(errorMsg: string): boolean {
	const lower = errorMsg.toLowerCase();
	return TRANSIENT_ERROR_PATTERNS.some((pattern) =>
		lower.includes(pattern.toLowerCase()),
	);
}
