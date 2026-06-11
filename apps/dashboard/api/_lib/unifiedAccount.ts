/**
 * Unified Account Abstraction
 *
 * Provides a single interface for both Threads (`accounts` table, TEXT ID)
 * and Instagram (`instagram_accounts` table, UUID ID) account types.
 *
 * The underlying DB schema is NOT changed — this is a read-side abstraction
 * that normalizes divergent column names into a common shape.
 */

import { logger, serializeError } from "./logger.js";
import type { Platform } from "./platform.js";
import { getSupabase } from "./supabase.js";

// ============================================================================
// Types
// ============================================================================

export interface UnifiedAccount {
	id: string;
	platform: Platform;
	userId: string;
	platformUserId: string;
	username: string;
	displayName: string | null;
	profilePicUrl: string | null;
	followerCount: number;
	followingCount: number;
	baselineFollowerCount: number;
	accessTokenEncrypted: string | null;
	tokenExpiresAt: string | null;
	isActive: boolean;
	lastSyncedAt: string | null;
	createdAt: string | null;
	updatedAt: string | null;
}

// ============================================================================
// Raw DB Row Interfaces (internal)
// ============================================================================

interface ThreadsAccountRow {
	id: string;
	user_id: string;
	threads_user_id: string;
	username: string | null;
	display_name: string | null;
	avatar_url: string | null;
	followers_count: number | null;
	following_count: number | null;
	baseline_followers_count: number | null;
	threads_access_token_encrypted: string | null;
	token_expires_at: string | null;
	is_active: boolean | null;
	last_synced_at: string | null;
	created_at: string | null;
	updated_at: string | null;
}

interface InstagramAccountRow {
	id: string;
	user_id: string;
	instagram_user_id: string;
	username: string | null;
	display_name: string | null;
	avatar_url: string | null;
	follower_count: number | null;
	following_count: number | null;
	baseline_follower_count: number | null;
	instagram_access_token_encrypted: string | null;
	token_expires_at: string | null;
	is_active: boolean | null;
	last_synced_at: string | null;
	created_at: string | null;
	updated_at: string | null;
}

// ============================================================================
// Mappers
// ============================================================================

/**
 * Map a raw `accounts` (Threads) row to UnifiedAccount.
 */
function mapThreadsAccount(row: ThreadsAccountRow): UnifiedAccount {
	return {
		id: row.id,
		platform: "threads",
		userId: row.user_id,
		platformUserId: row.threads_user_id,
		username: row.username ?? "",
		displayName: row.display_name ?? null,
		profilePicUrl: row.avatar_url ?? null,
		followerCount: row.followers_count ?? 0,
		followingCount: row.following_count ?? 0,
		baselineFollowerCount: row.baseline_followers_count ?? 0,
		accessTokenEncrypted: row.threads_access_token_encrypted ?? null,
		tokenExpiresAt: row.token_expires_at ?? null,
		isActive: row.is_active ?? true,
		lastSyncedAt: row.last_synced_at ?? null,
		createdAt: row.created_at ?? null,
		updatedAt: row.updated_at ?? null,
	};
}

/**
 * Map a raw `instagram_accounts` row to UnifiedAccount.
 */
function mapInstagramAccount(row: InstagramAccountRow): UnifiedAccount {
	return {
		id: row.id,
		platform: "instagram",
		userId: row.user_id,
		platformUserId: row.instagram_user_id,
		username: row.username ?? "",
		displayName: row.display_name ?? null,
		profilePicUrl: row.avatar_url ?? null,
		followerCount: row.follower_count ?? 0,
		followingCount: row.following_count ?? 0,
		baselineFollowerCount: row.baseline_follower_count ?? 0,
		accessTokenEncrypted: row.instagram_access_token_encrypted ?? null,
		tokenExpiresAt: row.token_expires_at ?? null,
		isActive: row.is_active ?? true,
		lastSyncedAt: row.last_synced_at ?? null,
		createdAt: row.created_at ?? null,
		updatedAt: row.updated_at ?? null,
	};
}

// ============================================================================
// Query Functions
// ============================================================================

/**
 * Fetch a unified account by ID and platform.
 * Returns null if not found.
 */
export async function getUnifiedAccount(
	id: string,
	platform: Platform,
): Promise<UnifiedAccount | null> {
	const supabase = getSupabase();

	if (platform === "threads") {
		// #708: Use maybeSingle() instead of single() to avoid PGRST116 error on missing rows
		const { data, error } = await supabase
			.from("accounts")
			.select(
				"id, user_id, threads_user_id, username, display_name, avatar_url, followers_count, following_count, baseline_followers_count, threads_access_token_encrypted, token_expires_at, is_active, last_synced_at, created_at, updated_at",
			)
			.eq("id", id)
			.maybeSingle();

		if (error) {
			// Distinguish "no row" from "Supabase failed". Returning null on a
			// real DB error masks the outage — exact shape of the April incident
			// where phantom column errors looked identical to missing rows.
			logger.warn("[unifiedAccount] threads fetch failed", {
				accountId: id,
				error: serializeError(error),
			});
			return null;
		}
		if (!data) return null;
		return mapThreadsAccount(data as unknown as ThreadsAccountRow);
	}

	const { data, error } = await supabase
		.from("instagram_accounts")
		.select(
			"id, user_id, instagram_user_id, username, display_name, avatar_url, follower_count, following_count, baseline_follower_count, instagram_access_token_encrypted, token_expires_at, is_active, last_synced_at, created_at, updated_at",
		)
		.eq("id", id)
		.maybeSingle();

	if (error) {
		logger.warn("[unifiedAccount] instagram fetch failed", {
			accountId: id,
			error: serializeError(error),
		});
		return null;
	}
	if (!data) return null;
	return mapInstagramAccount(data as unknown as InstagramAccountRow);
}

/**
 * Fetch all accounts for a user across both platforms.
 * Queries both tables in parallel and merges results.
 */
export async function getUserAccounts(
	userId: string,
): Promise<UnifiedAccount[]> {
	const supabase = getSupabase();

	const [threadsResult, igResult] = await Promise.all([
		supabase
			.from("accounts")
			.select(
				"id, user_id, threads_user_id, username, display_name, avatar_url, followers_count, following_count, baseline_followers_count, threads_access_token_encrypted, token_expires_at, is_active, last_synced_at, created_at, updated_at",
			)
			.eq("user_id", userId),
		supabase
			.from("instagram_accounts")
			.select(
				"id, user_id, instagram_user_id, username, display_name, avatar_url, follower_count, following_count, baseline_follower_count, instagram_access_token_encrypted, token_expires_at, is_active, last_synced_at, created_at, updated_at",
			)
			.eq("user_id", userId),
	]);

	const threadsAccounts = (
		(threadsResult.data || []) as unknown as ThreadsAccountRow[]
	).map(mapThreadsAccount);
	const igAccounts = (
		(igResult.data || []) as unknown as InstagramAccountRow[]
	).map(mapInstagramAccount);

	return [...threadsAccounts, ...igAccounts];
}

/**
 * Fetch all active accounts across ALL users (both platforms).
 * Useful for cron jobs that iterate over every account.
 * Optionally filter to only accounts with valid tokens.
 */
export async function getAllActiveAccounts(options?: {
	requireToken?: boolean | undefined;
}): Promise<UnifiedAccount[]> {
	const supabase = getSupabase();
	const requireToken = options?.requireToken ?? false;

	let threadsQuery = supabase
		.from("accounts")
		.select(
			"id, user_id, threads_user_id, username, display_name, avatar_url, followers_count, following_count, baseline_followers_count, threads_access_token_encrypted, token_expires_at, is_active, last_synced_at, created_at, updated_at",
		)
		.limit(10000);
	let igQuery = supabase
		.from("instagram_accounts")
		.select(
			"id, user_id, instagram_user_id, username, display_name, avatar_url, follower_count, following_count, baseline_follower_count, instagram_access_token_encrypted, token_expires_at, is_active, last_synced_at, created_at, updated_at",
		)
		.limit(10000);

	if (requireToken) {
		// Supabase query-builder generics can blow TS's instantiation depth
		// (TS2589); cast through a narrow structural type for this filter.
		threadsQuery = (threadsQuery as unknown as { not: typeof threadsQuery.not }).not(
			"threads_access_token_encrypted",
			"is",
			null,
		) as unknown as typeof threadsQuery;
		igQuery = (igQuery as unknown as { not: typeof igQuery.not }).not(
			"instagram_access_token_encrypted",
			"is",
			null,
		) as unknown as typeof igQuery;
	}

	const [threadsResult, igResult] = await Promise.all([threadsQuery, igQuery]);

	const threadsAccounts = (
		(threadsResult.data || []) as unknown as ThreadsAccountRow[]
	).map(mapThreadsAccount);
	const igAccounts = (
		(igResult.data || []) as unknown as InstagramAccountRow[]
	).map(mapInstagramAccount);

	return [...threadsAccounts, ...igAccounts];
}
