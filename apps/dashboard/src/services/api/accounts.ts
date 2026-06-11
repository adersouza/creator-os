/**
 * Account management API operations
 */

import { neqOrNull } from "@/lib/supabaseSafe";
import { randomUUID } from "@/lib/uuid";
import type {
	AccountRow,
	InstagramAccountRow,
	PostRow,
} from "@/types/database";
import type { InstagramAccount, ThreadAccount, ThreadPost } from "@/types/index";
import { getUserIdAsync, logger, supabase, withRetry } from "./shared";

import { apiUrl } from '@/lib/apiUrl';
type OAuthExchangeResponse = {
	success: boolean;
	error?: string | undefined;
	[key: string]: unknown;
};

type ServiceThreadAccount = ThreadAccount & {
	createdAt?: string | null | undefined;
	updatedAt?: string | null | undefined;
	tokenExpiresAt?: Date | null | undefined;
	needsReauth?: boolean | undefined;
	ai_config?: AccountRow["ai_config"] | undefined;
	posting_method?: AccountRow["posting_method"] | undefined;
};

type ServiceInstagramAccount = Omit<
	InstagramAccount,
	"lastSyncedAt" | "tokenExpiresAt" | "createdAt" | "updatedAt"
> & {
	facebookPageName?: string | undefined;
	accountType?: string | undefined;
	loginType?: "instagram" | "facebook" | undefined;
	groupId?: string | undefined;
	ai_config?: InstagramAccountRow["ai_config"] | undefined;
	createdAt?: string | undefined;
	updatedAt?: string | undefined;
	lastSyncedAt?: Date | undefined;
	tokenExpiresAt?: Date | null | undefined;
};

type ServiceAccount = ServiceThreadAccount | ServiceInstagramAccount;
type ServiceThreadPost = {
	id: string;
	content: string;
	status: ThreadPost["status"];
	accountId: string;
	publishedAt?: string | undefined;
	threadId?: string | undefined;
	permalink?: string | undefined;
	platform?: ThreadPost["platform"] | undefined;
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	mediaUrls: string[];
	[key: string]: unknown;
};

function normalizePlatform(
	platform: string | null | undefined,
): ThreadPost["platform"] {
	return platform === "threads" ||
		platform === "instagram" ||
		platform === "bluesky" ||
		platform === "tiktok"
		? platform
		: undefined;
}

function normalizeStatus(
	status: string | null | undefined,
): "active" | "suspended" | "pending" {
	return status === "suspended" || status === "pending" ? status : "active";
}

function mapThreadAccount(
	row: Pick<
		AccountRow,
		| "id"
		| "username"
		| "avatar_url"
		| "followers_count"
		| "is_active"
		| "status"
		| "threads_user_id"
		| "created_at"
		| "updated_at"
		| "last_synced_at"
		| "token_expires_at"
		| "needs_reauth"
		| "group_id"
		| "ai_config"
	> &
		Partial<Pick<AccountRow, "posting_method">>,
): ServiceThreadAccount {
	return {
		id: row.id,
		platform: "threads",
		handle: row.username || "",
		avatarUrl: row.avatar_url || "",
		followers: row.followers_count || 0,
		isActive: row.is_active ?? true,
		status: normalizeStatus(row.status),
		username: row.username || undefined,
		followersCount: row.followers_count || 0,
		threadsUserId: row.threads_user_id || undefined,
		createdAt: row.created_at || undefined,
		updatedAt: row.updated_at || undefined,
		lastSyncedAt: row.last_synced_at ? new Date(row.last_synced_at) : undefined,
		tokenExpiresAt: row.token_expires_at
			? new Date(row.token_expires_at)
			: null,
		needsReauth: row.needs_reauth ?? false,
		groupId: row.group_id || undefined,
		ai_config: row.ai_config,
		posting_method: row.posting_method,
	};
}

function mapInstagramServiceAccount(
	row: Pick<
		InstagramAccountRow,
		| "id"
		| "username"
		| "display_name"
		| "avatar_url"
		| "instagram_user_id"
		| "facebook_page_id"
		| "facebook_page_name"
		| "account_type"
		| "login_type"
		| "follower_count"
		| "following_count"
		| "media_count"
		| "is_active"
		| "status"
		| "needs_reauth"
		| "token_expires_at"
		| "last_synced_at"
		| "group_id"
		| "ai_config"
		| "created_at"
		| "updated_at"
	>,
): ServiceInstagramAccount {
	return {
		id: row.id,
		platform: "instagram",
		handle: row.username || "",
		avatarUrl: row.avatar_url || "",
		followers: row.follower_count || 0,
		isActive: row.is_active ?? true,
		status: normalizeStatus(row.status),
		username: row.username || undefined,
		displayName: row.display_name || undefined,
		followersCount: row.follower_count || 0,
		followingCount: row.following_count || 0,
		mediaCount: row.media_count || 0,
		instagramUserId: row.instagram_user_id || "",
		needsReauth: row.needs_reauth ?? false,
		loginType:
			row.login_type === "facebook" || row.login_type === "instagram"
				? row.login_type
				: undefined,
		facebookPageId: row.facebook_page_id || undefined,
		facebookPageName: row.facebook_page_name || undefined,
		accountType: row.account_type || undefined,
		groupId: row.group_id || undefined,
		ai_config: row.ai_config,
		createdAt: row.created_at || undefined,
		updatedAt: row.updated_at || undefined,
		lastSyncedAt: row.last_synced_at ? new Date(row.last_synced_at) : undefined,
		tokenExpiresAt: row.token_expires_at
			? new Date(row.token_expires_at)
			: null,
	};
}

function mapPublishedThread(row: PostRow): ServiceThreadPost {
	return {
		...row,
		id: row.id,
		content: row.content,
		status: row.status as ThreadPost["status"],
		accountId: row.account_id || "",
		publishedAt: row.published_at || undefined,
		threadId: row.threads_post_id || undefined,
		permalink: row.permalink || undefined,
		platform: normalizePlatform(row.platform),
		views: row.views_count || 0,
		likes: row.likes_count || 0,
		replies: row.replies_count || 0,
		reposts: row.reposts_count || 0,
		mediaUrls: row.media_urls || [],
	};
}

/**
 * Store OAuth state in Redis via server endpoint.
 * Callbacks fail closed on server-side state verification, so the redirect must
 * not start unless this reservation succeeds.
 */
async function storeOAuthStateOnServer(state: string): Promise<void> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) {
		throw new Error("Sign in before connecting an account.");
	}

	const response = await fetch(apiUrl("/api/auth/oauth-state"), {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session.access_token}`,
		},
		body: JSON.stringify({ state }),
	});
	if (!response.ok) {
		const body = await response.json().catch(() => ({}));
		throw new Error(
			typeof body?.error === "string"
				? body.error
				: "Could not start secure OAuth flow. Please try again.",
		);
	}
}

// --- AUTHENTICATION ---
export async function initiateLogin(): Promise<{
	authUrl: string;
	state: string;
}> {
	const clientId = import.meta.env.VITE_THREADS_CLIENT_ID;
	const redirectUri =
		import.meta.env.VITE_THREADS_REDIRECT_URI ||
		`${window.location.origin}/auth/threads/callback`;
	const state = randomUUID();

	localStorage.setItem("threads_oauth_state", state);
	await storeOAuthStateOnServer(state);

	const authUrl = `https://threads.net/oauth/authorize?client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&scope=threads_basic,threads_content_publish,threads_manage_insights,threads_manage_replies,threads_read_replies,threads_manage_mentions,threads_profile_discovery,threads_keyword_search,threads_location_tagging,threads_delete,threads_share_to_instagram&response_type=code&state=${state}`;

	return { authUrl, state };
}

export async function initiateInstagramLogin(options?: {
	forceReauth?: boolean | undefined;
}): Promise<{
	authUrl: string;
	state: string;
}> {
	const clientId = import.meta.env.VITE_INSTAGRAM_CLIENT_ID;
	const redirectUri =
		import.meta.env.VITE_INSTAGRAM_REDIRECT_URI ||
		`${window.location.origin}/auth/instagram/callback`;
	const state = randomUUID();

	localStorage.setItem("instagram_oauth_state", state);
	await storeOAuthStateOnServer(state);

	const scopes = [
		"instagram_business_basic",
		"instagram_business_content_publish",
		"instagram_business_manage_comments",
		"instagram_business_manage_insights",
		"instagram_business_manage_messages",
	].join(",");

	let authUrl = `https://www.instagram.com/oauth/authorize?client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&scope=${scopes}&response_type=code&state=${state}`;
	if (options?.forceReauth) {
		authUrl += "&force_reauth=true";
	}

	return { authUrl, state };
}

export async function initiateFacebookLogin(): Promise<{
	authUrl: string;
	state: string;
}> {
	const appId = import.meta.env.VITE_FACEBOOK_APP_ID;
	const redirectUri =
		import.meta.env.VITE_FACEBOOK_REDIRECT_URI ||
		`${window.location.origin}/auth/facebook/callback`;
	const state = randomUUID();

	localStorage.setItem("facebook_oauth_state", state);
	await storeOAuthStateOnServer(state);

	const scopes = [
		"pages_show_list",
		"pages_read_engagement",
		"instagram_basic",
		"instagram_content_publish",
		"instagram_manage_contents",
		"instagram_manage_comments",
		"instagram_manage_engagement",
		"instagram_manage_insights",
	].join(",");

	const authUrl = `https://www.facebook.com/v25.0/dialog/oauth?client_id=${appId}&redirect_uri=${encodeURIComponent(redirectUri)}&scope=${scopes}&response_type=code&state=${state}`;

	return { authUrl, state };
}

export async function exchangeToken(
	code: string,
	state: string,
): Promise<OAuthExchangeResponse> {
	const storedState = localStorage.getItem("threads_oauth_state");
	if (state !== storedState) {
		throw new Error("Invalid OAuth state");
	}

	const {
		data: { session },
	} = await supabase.auth.getSession();

	if (!session?.user) {
		throw new Error("User not authenticated");
	}

	const response = await fetch(apiUrl("/api/auth/threads/callback"), {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session.access_token}`,
		},
		body: JSON.stringify({
			code,
			userId: session.user.id,
		}),
	});

	if (!response.ok) {
		const error = await response.json();
		throw new Error(error.error || "Failed to exchange token");
	}

	localStorage.removeItem("threads_oauth_state");
	return (await response.json()) as OAuthExchangeResponse;
}

export async function checkAuthStatus(accountId: string): Promise<{
	isAuthenticated: boolean;
	isExpired: boolean;
	expiresAt?: string | undefined;
}> {
	try {
		const userId = await getUserIdAsync();
		const { data, error } = await supabase
			.from("accounts")
			.select("token_expires_at")
			.eq("id", accountId)
			.eq("user_id", userId)
			.maybeSingle();

		if (error || !data) {
			return { isAuthenticated: false, isExpired: true };
		}

		// If token_expires_at exists, the account was connected (has a token)
		const hasToken = !!data.token_expires_at;
		const expiresAt = data.token_expires_at
			? new Date(data.token_expires_at)
			: null;
		const isExpired = expiresAt ? expiresAt < new Date() : false;

		return {
			isAuthenticated: hasToken,
			isExpired,
			expiresAt: expiresAt?.toISOString(),
		};
	} catch {
		return { isAuthenticated: false, isExpired: true };
	}
}

// --- ACCOUNTS ---
export async function getAccounts(options?: {
	excludeSuspended?: boolean | undefined;
}): Promise<ServiceThreadAccount[]> {
	const userId = await getUserIdAsync();

	const { data, error } = (await withRetry(
		async () => {
			let query = supabase
				.from("accounts")
				.select(
					"id, username, display_name, avatar_url, bio, followers_count, following_count, is_active, status, needs_reauth, threads_user_id, created_at, updated_at, last_synced_at, token_expires_at, group_id, ai_config",
				)
				.eq("user_id", userId)
				.order("created_at", { ascending: false })
				.limit(500);

			if (options?.excludeSuspended) {
				query = neqOrNull(query, "status", "suspended");
			}

			return query;
		},
		{ name: "getAccounts" },
	)) as { data: AccountRow[] | null; error: unknown };

	if (error) {
		logger.error("Failed to fetch accounts from Supabase:", error);
		throw error;
	}

	return (data || []).map(mapThreadAccount);
}

export async function getAccount(id: string): Promise<ServiceAccount> {
	const userId = await getUserIdAsync();

	const { data, error } = await supabase
		.from("accounts")
		.select(
			"id, username, display_name, avatar_url, bio, followers_count, following_count, is_active, status, needs_reauth, threads_user_id, created_at, updated_at, last_synced_at, token_expires_at, group_id, ai_config, posting_method",
		)
		.eq("id", id)
		.eq("user_id", userId)
		.maybeSingle();

	if (!error && data) {
		return mapThreadAccount(data);
	}

	// Fall back to Instagram accounts table
	const { data: igData, error: igError } = await supabase
		.from("instagram_accounts")
		.select(
			"id, username, display_name, avatar_url, instagram_user_id, facebook_page_id, facebook_page_name, account_type, login_type, follower_count, following_count, media_count, is_active, status, needs_reauth, token_expires_at, last_synced_at, group_id, ai_config, created_at, updated_at",
		)
		.eq("id", id)
		.eq("user_id", userId)
		.maybeSingle();

	if (igError || !igData) {
		throw new Error("Account not found");
	}

	return mapInstagramServiceAccount(igData);
}

export async function getAccountThreads(
	id: string,
): Promise<ServiceThreadPost[]> {
	const userId = await getUserIdAsync();
	const { data, error } = await supabase
		.from("posts")
		.select("*")
		.eq("user_id", userId)
		.eq("account_id", id)
		.eq("status", "published")
		.order("published_at", { ascending: false })
		.limit(100);

	if (error) {
		logger.error("Failed to fetch account threads:", error);
		throw error;
	}

	return (data || []).map(mapPublishedThread);
}
