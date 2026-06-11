/**
 * Centralized Token Access — fetch + decrypt account tokens in one call.
 *
 * Replaces the scattered pattern of independently querying accounts table
 * + importing decrypt + calling decrypt in 37+ files. All token access
 * should go through these helpers.
 */

import { decrypt } from "./encryption.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./privilegedDb.js";

const db = () =>
	getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.tokenDecryption);

// ============================================================================
// Types
// ============================================================================

export interface ThreadsTokenResult {
	token: string;
	threadsUserId: string;
	accountId: string;
	username: string;
}

export interface IGTokenResult {
	token: string;
	igUserId: string;
	accountId: string;
	username: string;
	loginType: string;
	/** Facebook Page access token (for IG accounts connected via FB login) */
	fbPageToken?: string | undefined;
}

// ============================================================================
// Threads Token Access
// ============================================================================

/**
 * Fetch and decrypt a Threads account token by account ID.
 * Returns null if account not found, inactive, needs reauth, or has no token.
 */
export async function getDecryptedThreadsToken(
	accountId: string,
): Promise<ThreadsTokenResult | null> {
	const { data: account } = await db()
		.from("accounts")
		.select(
			"id, username, threads_user_id, threads_access_token_encrypted, needs_reauth, is_active",
		)
		.eq("id", accountId)
		.maybeSingle();

	if (!account) return null;
	if (account.needs_reauth || !account.is_active) return null;
	if (!account.threads_access_token_encrypted) return null;

	const token = decrypt(account.threads_access_token_encrypted);
	if (!token) return null;

	return {
		token,
		threadsUserId: account.threads_user_id,
		accountId: account.id,
		username: account.username || "",
	};
}

/**
 * Fetch and decrypt a Threads token by user_id (owner).
 * Useful when you have the user's ID but not a specific account ID.
 * Returns the first active, non-reauth account found.
 */
export async function getDecryptedThreadsTokenByUser(
	userId: string,
): Promise<ThreadsTokenResult | null> {
	const { data: account } = await db()
		.from("accounts")
		.select("id, username, threads_user_id, threads_access_token_encrypted")
		.eq("user_id", userId)
		.eq("is_active", true)
		.or("needs_reauth.is.null,needs_reauth.eq.false")
		.not("threads_access_token_encrypted", "is", null)
		.limit(1)
		.maybeSingle();

	if (!account?.threads_access_token_encrypted) return null;

	const token = decrypt(account.threads_access_token_encrypted);
	if (!token) return null;

	return {
		token,
		threadsUserId: account.threads_user_id,
		accountId: account.id,
		username: account.username || "",
	};
}

// ============================================================================
// Instagram Token Access
// ============================================================================

/**
 * Fetch and decrypt an Instagram account token by account ID.
 * Returns null if account not found, inactive, needs reauth, or has no token.
 */
export async function getDecryptedIGToken(
	accountId: string,
): Promise<IGTokenResult | null> {
	const { data: account } = await db()
		.from("instagram_accounts")
		.select(
			"id, username, instagram_user_id, instagram_access_token_encrypted, facebook_page_access_token_encrypted, login_type, needs_reauth, is_active",
		)
		.eq("id", accountId)
		.maybeSingle();

	if (!account) return null;
	if (account.needs_reauth || !account.is_active) return null;
	if (!account.instagram_access_token_encrypted) return null;

	const token = decrypt(account.instagram_access_token_encrypted);
	if (!token) return null;

	let fbPageToken: string | undefined;
	if (account.facebook_page_access_token_encrypted) {
		fbPageToken =
			decrypt(account.facebook_page_access_token_encrypted) || undefined;
	}

	return {
		token,
		igUserId: account.instagram_user_id,
		accountId: account.id,
		username: account.username || "",
		loginType: account.login_type || "ig_basic",
		fbPageToken,
	};
}

/**
 * Fetch and decrypt an IG token by user_id (owner).
 * Returns the first active, non-reauth account found.
 */
export async function getDecryptedIGTokenByUser(
	userId: string,
): Promise<IGTokenResult | null> {
	const { data: account } = await db()
		.from("instagram_accounts")
		.select(
			"id, username, instagram_user_id, instagram_access_token_encrypted, facebook_page_access_token_encrypted, login_type",
		)
		.eq("user_id", userId)
		.eq("is_active", true)
		.or("needs_reauth.is.null,needs_reauth.eq.false")
		.not("instagram_access_token_encrypted", "is", null)
		.limit(1)
		.maybeSingle();

	if (!account?.instagram_access_token_encrypted) return null;

	const token = decrypt(account.instagram_access_token_encrypted);
	if (!token) return null;

	let fbPageToken: string | undefined;
	if (account.facebook_page_access_token_encrypted) {
		fbPageToken =
			decrypt(account.facebook_page_access_token_encrypted) || undefined;
	}

	return {
		token,
		igUserId: account.instagram_user_id,
		accountId: account.id,
		username: account.username || "",
		loginType: account.login_type || "ig_basic",
		fbPageToken,
	};
}
