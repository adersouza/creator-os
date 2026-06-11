/**
 * Unified Webhook Event Abstraction
 *
 * Provides a single interface for both Threads (`threads_webhook_events`)
 * and Instagram (`ig_webhook_events`) webhook event tables.
 *
 * Both tables share a similar schema with boolean `processed` / `dead_letter`
 * fields rather than a string status column. This abstraction normalizes them
 * into a unified status enum for easier consumption.
 */

import type { Platform } from "./platform.js";

import { getSupabase } from "./supabase.js";

// ============================================================================
// Types
// ============================================================================

export type WebhookEventStatus =
	| "pending"
	| "processing"
	| "completed"
	| "failed"
	| "dead_letter";

export interface UnifiedWebhookEvent {
	id: string;
	platform: Platform;
	platformUserId: string;
	eventType: string;
	eventData: Record<string, unknown>;
	status: WebhookEventStatus;
	retryCount: number;
	maxRetries: number;
	nextRetryAt: string | null;
	createdAt: string;
	processedAt: string | null;
	error: string | null;
}

export interface WebhookEventStats {
	threads: { pending: number; failed: number; deadLetter: number };
	instagram: { pending: number; failed: number; deadLetter: number };
}

// ============================================================================
// Constants
// ============================================================================

const DEFAULT_MAX_RETRIES = 5;

// ============================================================================
// Mappers
// ============================================================================

/**
 * Derive a unified status from the boolean flags in the DB rows.
 * - dead_letter = true → "dead_letter"
 * - processed = true → "completed"
 * - retry_count > 0 && !processed → "failed" (has been attempted, awaiting retry)
 * - otherwise → "pending"
 */
function deriveStatus(row: {
	processed: boolean;
	dead_letter: boolean | null;
	retry_count: number;
}): WebhookEventStatus {
	if (row.dead_letter) return "dead_letter";
	if (row.processed) return "completed";
	if (row.retry_count > 0) return "failed";
	return "pending";
}

function safePayload(payload: unknown): Record<string, unknown> {
	if (payload === null || payload === undefined) return {};
	if (typeof payload !== "object" || Array.isArray(payload)) return {};
	return payload as Record<string, unknown>;
}

interface WebhookEventRow {
	id: string;
	event_type: string;
	payload: unknown;
	received_at?: string | undefined;
	created_at?: string | undefined;
	processed: boolean;
	processed_at?: string | null | undefined;
	dead_letter: boolean | null;
	retry_count: number;
	next_retry_at?: string | null | undefined;
	last_error?: string | null | undefined;
	error?: string | null | undefined;
	threads_user_id?: string | undefined;
	ig_user_id?: string | undefined;
	user_id?: string | undefined;
}

function mapThreadsEvent(row: WebhookEventRow): UnifiedWebhookEvent | null {
	if (!row.id || !row.event_type) return null;
	return {
		id: row.id,
		platform: "threads",
		platformUserId: row.threads_user_id ?? "",
		eventType: row.event_type,
		eventData: safePayload(row.payload),
		status: deriveStatus(row),
		retryCount: row.retry_count ?? 0,
		maxRetries: DEFAULT_MAX_RETRIES,
		nextRetryAt: row.next_retry_at ?? null,
		createdAt: row.received_at ?? row.created_at ?? "",
		processedAt: row.processed_at ?? null,
		error: row.last_error ?? row.error ?? null,
	};
}

function mapInstagramEvent(row: WebhookEventRow): UnifiedWebhookEvent | null {
	if (!row.id || !row.event_type) return null;
	return {
		id: row.id,
		platform: "instagram",
		platformUserId: row.ig_user_id ?? "",
		eventType: row.event_type,
		eventData: safePayload(row.payload),
		status: deriveStatus(row),
		retryCount: row.retry_count ?? 0,
		maxRetries: DEFAULT_MAX_RETRIES,
		nextRetryAt: row.next_retry_at ?? null,
		createdAt: row.received_at ?? "",
		processedAt: row.processed_at ?? null,
		error: row.last_error ?? row.error ?? null,
	};
}

// ============================================================================
// Query Functions
// ============================================================================

/**
 * Fetch pending (unprocessed, non-dead-letter) webhook events across both platforms.
 * Ordered by received_at ascending (oldest first).
 */
export async function getPendingWebhookEvents(
	limit = 50,
): Promise<UnifiedWebhookEvent[]> {
	const supabase = getSupabase();
	const halfLimit = Math.ceil(limit / 2);

	const cols =
		"id, event_type, payload, received_at, created_at, processed, processed_at, dead_letter, retry_count, user_id";

	type FlexibleQuery = {
		eq: (col: string, val: unknown) => FlexibleQuery;
		or: (filter: string) => FlexibleQuery;
		order: (col: string, opts: { ascending: boolean }) => FlexibleQuery;
		limit: (
			n: number,
		) => Promise<{ data: WebhookEventRow[] | null; error: unknown }>;
		gt: (col: string, val: unknown) => FlexibleQuery;
	};

	const [threadsResult, igResult] = await Promise.all([
		(
			supabase
				.from("threads_webhook_events")
				.select(cols) as unknown as FlexibleQuery
		)
			.eq("processed", false)
			.or("dead_letter.is.null,dead_letter.eq.false")
			.order("received_at", { ascending: true })
			.limit(halfLimit),
		(
			supabase
				.from("ig_webhook_events")
				.select(cols) as unknown as FlexibleQuery
		)
			.eq("processed", false)
			.or("dead_letter.is.null,dead_letter.eq.false")
			.order("received_at", { ascending: true })
			.limit(halfLimit),
	]);

	const threadsEvents = (threadsResult.data || [])
		.map(mapThreadsEvent)
		.filter(Boolean) as UnifiedWebhookEvent[];
	const igEvents = (igResult.data || [])
		.map(mapInstagramEvent)
		.filter(Boolean) as UnifiedWebhookEvent[];

	// Merge and sort by createdAt ascending, then trim to requested limit
	return [...threadsEvents, ...igEvents]
		.sort(
			(a, b) =>
				new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime(),
		)
		.slice(0, limit);
}

/**
 * Get webhook event statistics for health monitoring.
 * Counts pending, failed (retrying), and dead-letter events per platform.
 */
export async function getWebhookEventStats(): Promise<WebhookEventStats> {
	const supabase = getSupabase();

	type CountQuery = {
		eq: (
			col: string,
			val: unknown,
		) => CountQuery & Promise<{ count: number | null; error: unknown }>;
		or: (
			filter: string,
		) => CountQuery & Promise<{ count: number | null; error: unknown }>;
		gt: (
			col: string,
			val: unknown,
		) => CountQuery & Promise<{ count: number | null; error: unknown }>;
		then: Promise<{ count: number | null; error: unknown }>["then"];
	};

	// Run all 6 count queries in parallel
	const [
		threadsPendingResult,
		threadsFailedResult,
		threadsDeadLetterResult,
		igPendingResult,
		igFailedResult,
		igDeadLetterResult,
	] = await Promise.all([
		// Threads — pending: not processed, not dead_letter, retry_count = 0
		(
			supabase
				.from("threads_webhook_events")
				.select("id", { count: "exact", head: true }) as unknown as CountQuery
		)
			.eq("processed", false)
			.or("dead_letter.is.null,dead_letter.eq.false")
			.eq("retry_count", 0),

		// Threads — failed (retrying): not processed, not dead_letter, retry_count > 0
		(
			supabase
				.from("threads_webhook_events")
				.select("id", { count: "exact", head: true }) as unknown as CountQuery
		)
			.eq("processed", false)
			.or("dead_letter.is.null,dead_letter.eq.false")
			.gt("retry_count", 0),

		// Threads — dead letter
		(
			supabase
				.from("threads_webhook_events")
				.select("id", { count: "exact", head: true }) as unknown as CountQuery
		).eq("dead_letter", true),

		// Instagram — pending
		(
			supabase
				.from("ig_webhook_events")
				.select("id", { count: "exact", head: true }) as unknown as CountQuery
		)
			.eq("processed", false)
			.or("dead_letter.is.null,dead_letter.eq.false")
			.eq("retry_count", 0),

		// Instagram — failed (retrying)
		(
			supabase
				.from("ig_webhook_events")
				.select("id", { count: "exact", head: true }) as unknown as CountQuery
		)
			.eq("processed", false)
			.or("dead_letter.is.null,dead_letter.eq.false")
			.gt("retry_count", 0),

		// Instagram — dead letter
		(
			supabase
				.from("ig_webhook_events")
				.select("id", { count: "exact", head: true }) as unknown as CountQuery
		).eq("dead_letter", true),
	]);

	return {
		threads: {
			pending: threadsPendingResult.count ?? 0,
			failed: threadsFailedResult.count ?? 0,
			deadLetter: threadsDeadLetterResult.count ?? 0,
		},
		instagram: {
			pending: igPendingResult.count ?? 0,
			failed: igFailedResult.count ?? 0,
			deadLetter: igDeadLetterResult.count ?? 0,
		},
	};
}
