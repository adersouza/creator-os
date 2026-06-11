/**
 * Resolve an account ID to either a Threads or Instagram account.
 * Used by features that need to work across both platforms.
 */

import { logger } from "./logger.js";
import type { Platform } from "./platform.js";
import { getSupabase } from "./supabase.js";

interface ThreadsAccountDbRow {
	id: string;
	user_id: string;
	username: string | null;
	threads_user_id: string | null;
	threads_access_token_encrypted: string | null;
	is_active?: boolean | null | undefined;
	needs_reauth?: boolean | null | undefined;
	status?: string | null | undefined;
	token_expires_at?: string | null | undefined;
	group_id?: string | null | undefined;
}

interface IGAccountDbRow {
	id: string;
	user_id: string;
	username: string | null;
	instagram_user_id: string | null;
	ig_user_id?: string | null | undefined;
	instagram_access_token_encrypted: string | null;
	login_type?: string | null | undefined;
	facebook_page_access_token_encrypted?: string | null | undefined;
	is_active?: boolean | null | undefined;
	needs_reauth?: boolean | null | undefined;
	status?: string | null | undefined;
	token_expires_at?: string | null | undefined;
	group_id?: string | null | undefined;
}

export interface ResolvedAccount {
	platform: Platform;
	id: string;
	userId: string;
	username: string;
	/** Threads: threads_user_id, IG: instagram_user_id */
	platformUserId: string;
	/** Encrypted access token */
	encryptedToken: string;
	/** IG-specific: login_type for choosing graph base URL */
	loginType?: string | undefined;
	/** IG-specific: encrypted Facebook page token */
	encryptedFbPageToken?: string | undefined;
	/** Raw row from the database */
	raw: Record<string, unknown>;
}

export type AccountLifecycleFields = {
	is_active?: boolean | null | undefined;
	needs_reauth?: boolean | null | undefined;
	status?: string | null | undefined;
	token_expires_at?: string | null | undefined;
};

const BLOCKED_ACCOUNT_STATUSES = new Set([
	"inactive",
	"suspended",
	"needs_reauth",
	"disabled",
	"retired",
]);

export function getAccountLifecycleBlock(
	account: AccountLifecycleFields,
): string | null {
	if (account.is_active === false) {
		return "Account is inactive";
	}
	if (account.needs_reauth === true) {
		return "Account needs reconnection";
	}
	const status = account.status?.trim().toLowerCase();
	if (status && BLOCKED_ACCOUNT_STATUSES.has(status)) {
		return `Account is ${status}`;
	}
	if (account.token_expires_at) {
		const expiresAt = Date.parse(account.token_expires_at);
		if (Number.isFinite(expiresAt) && expiresAt <= Date.now()) {
			return "Account token has expired";
		}
	}
	return null;
}

/**
 * Look up accountId in `accounts` (Threads) first, then `instagram_accounts` (IG).
 * Returns null if not found or not owned by the user.
 */
export async function resolveAccount(
	accountId: string,
	userId: string,
): Promise<ResolvedAccount | null> {
	const db = getSupabase();

	// Try Threads first
	const { data: threadsAccount, error: threadsError } = await db
		.from("accounts")
		.select(
			"id, user_id, username, threads_user_id, threads_access_token_encrypted, is_active, needs_reauth, status, token_expires_at, group_id",
		)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!threadsError && threadsAccount) {
		const row = threadsAccount as unknown as ThreadsAccountDbRow;
		return {
			platform: "threads",
			id: row.id,
			userId: row.user_id,
			username: row.username || "",
			platformUserId: row.threads_user_id || "",
			encryptedToken: row.threads_access_token_encrypted || "",
			raw: row as unknown as Record<string, unknown>,
		};
	}

	// Try Instagram
	const { data: igAccount, error: igError } = await db
		.from("instagram_accounts")
		.select(
			"id, user_id, username, instagram_user_id, instagram_access_token_encrypted, login_type, facebook_page_access_token_encrypted, is_active, needs_reauth, status, token_expires_at, group_id",
		)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!igError && igAccount) {
		const row = igAccount as unknown as IGAccountDbRow;
		return {
			platform: "instagram",
			id: row.id,
			userId: row.user_id,
			username: row.username || "",
			platformUserId: row.instagram_user_id || row.ig_user_id || "",
			encryptedToken: row.instagram_access_token_encrypted || "",
			loginType: row.login_type ?? undefined,
			encryptedFbPageToken:
				row.facebook_page_access_token_encrypted ?? undefined,
			raw: row as unknown as Record<string, unknown>,
		};
	}

	logger.warn("[resolveAccount] Account not found", { accountId, userId });
	return null;
}

export async function resolveSendAccount(
	accountId: string,
	userId: string,
): Promise<
	| { ok: true; account: ResolvedAccount }
	| { ok: false; status: 403 | 404; message: string }
> {
	const account = await resolveAccount(accountId, userId);
	if (!account) {
		return { ok: false, status: 404, message: "Account not found" };
	}
	const blockReason = getAccountLifecycleBlock(account.raw);
	if (blockReason) {
		return {
			ok: false,
			status: 403,
			message: `${blockReason}. Reconnect or reactivate it before sending.`,
		};
	}
	return { ok: true, account };
}
