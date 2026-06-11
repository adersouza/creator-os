// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Shared types, constants, and helpers for daily maintenance phases.
 */

import type { TypedSupabaseClient } from "../../supabase.js";

// ============================================================================
// Types
// ============================================================================

export type Logger = {
	debug: (msg: string, ctx?: Record<string, unknown>) => void;
	info: (msg: string, ctx?: Record<string, unknown>) => void;
	warn: (msg: string, ctx?: Record<string, unknown>) => void;
	error: (msg: string, ctx?: Record<string, unknown>) => void;
};

export interface Account {
	id: string;
	user_id: string;
	username: string | null;
	threads_user_id: string | null;
	threads_access_token_encrypted: string | null;
	token_expires_at: string | null;
	updated_at: string | null;
}

export interface InstagramAccount {
	id: string;
	user_id: string;
	username: string | null;
	instagram_user_id: string | null;
	instagram_access_token_encrypted: string | null;
	token_expires_at: string | null;
	login_type: string | null;
	updated_at: string | null;
}

export interface ThreadsTokenResponse {
	access_token: string;
	expires_in?: number | undefined;
	error?:
		| {
				message: string;
				type: string;
				code: number;
				error_subcode?: number | undefined;
		  }
		| undefined;
}

export interface RefreshResult {
	accountId: string;
	username: string | null;
	success: boolean;
	error?: string | undefined;
	/**
	 * Structured Meta error envelope, when the failure was a Meta API response.
	 * Used by `trackRefreshFailure` to classify transient (don't bump counter)
	 * vs auth (flag for reauth) via the canonical metaErrors classifier.
	 */
	metaError?:
		| {
				code?: number | undefined;
				error_subcode?: number | undefined;
				type?: string | undefined;
				message?: string | undefined;
		  }
		| undefined;
	newExpiresAt?: string | undefined;
}

export interface PurgeResult {
	table: string;
	deleted: number;
}

export interface PhaseMetadata {
	expireTrials: { count: number; error?: string | undefined };
	refreshTokens: { refreshed: number; failed: number; error?: string | undefined };
	dataRetention: { deleted: number; error?: string | undefined };
	cleanupAudit: { ok: boolean; deleted?: number | undefined; error?: string | undefined };
	mediaMigration: { migrated: number; failed: number; error?: string | undefined };
	enforceAccounts: { enforced: number; error?: string | undefined };
	vacuumAnalyze: { ok: boolean; error?: string | undefined };
	storageCleanup: {
		deleted: number;
		scanned?: number | undefined;
		referenced?: number | undefined;
		orphaned?: number | undefined;
		error?: string | undefined;
	};
	stripeSubscriptionPoll: {
		checked: number;
		corrected: number;
		error?: string | undefined;
	};
	dlqSweep: {
		threadsRevived: number;
		igRevived: number;
		error?: string | undefined;
	};
}

// Re-export for convenience
export type { TypedSupabaseClient };

// ============================================================================
// Configuration
// ============================================================================

export const MAX_EXECUTION_TIME = 290_000; // 290s — leave 10s headroom for response
// 5 days (120h) — widened from 72h to catch tokens earlier.
// token-refresh.ts handles the 10-day safety net; this is the primary window.
export const HOURS_BEFORE_EXPIRY = 120;
export const TOKEN_CONCURRENCY_LIMIT = 5;
export const MEDIA_BATCH_SIZE = 10;
export const BUCKET_NAME = "post-media";

// ============================================================================
// Helpers
// ============================================================================

export function hasTimeBudget(startTime: number): boolean {
	return Date.now() - startTime < MAX_EXECUTION_TIME;
}

export function createConcurrencyLimiter(maxConcurrent: number) {
	let running = 0;
	const queue: (() => void)[] = [];

	return async <T>(fn: () => Promise<T>): Promise<T> => {
		return new Promise((resolve, reject) => {
			const run = async () => {
				running++;
				try {
					resolve(await fn());
				} catch (error) {
					reject(error);
				} finally {
					running--;
					if (queue.length > 0) {
						const next = queue.shift();
						next?.();
					}
				}
			};

			if (running < maxConcurrent) {
				run();
			} else {
				queue.push(run);
			}
		});
	};
}

export function getExtensionFromContentType(contentType: string): string {
	const map: Record<string, string> = {
		"image/jpeg": "jpg",
		"image/jpg": "jpg",
		"image/png": "png",
		"image/gif": "gif",
		"image/webp": "webp",
		"video/mp4": "mp4",
		"video/quicktime": "mov",
		"video/webm": "webm",
	};
	return map[contentType.split(";")[0]!] || "jpg";
}
