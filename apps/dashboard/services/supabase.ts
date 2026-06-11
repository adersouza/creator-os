/// <reference path="../vite-env.d.ts" />
/**
 * Supabase Client Configuration
 *
 * Initialize Supabase client for auth and database operations
 * Supports concurrent sessions from multiple browsers (e.g., AdsPower)
 */

import { createClient } from "@supabase/supabase-js";
import type { Database } from "../types/supabase.js";

// Lazy import to break circular dep: realtimeManager ↔ supabase
const unsubscribeAllChannels = () =>
	import("./realtimeManager.js").then((m) => m.unsubscribeAll());

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
}

// --- Proactive JWT refresh fetch wrapper ---
// Supabase returns errors without CORS headers when the JWT is expired,
// which Safari reports as "access control checks" failures. This wrapper
// ensures the token is fresh before every REST request, eliminating the
// race between background-tab timer throttling and token expiry.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
// biome-ignore lint/suspicious/noExplicitAny: Supabase client reference held before initialization
let _supabaseRef: any = null;
let _refreshPromise: Promise<void> | null = null;

const SESSION_REFRESH_BUFFER_MS = 60_000; // refresh if <60s until expiry

async function ensureFreshSession(): Promise<void> {
	if (!_supabaseRef) return;

	// Coalesce concurrent refresh attempts into a single request
	if (_refreshPromise) return _refreshPromise;

	_refreshPromise = (async () => {
		try {
			const {
				data: { session },
			} = await _supabaseRef.auth.getSession();
			if (!session) return; // not logged in — nothing to refresh

			const expiresAt = (session.expires_at ?? 0) * 1000; // seconds → ms
			const remaining = expiresAt - Date.now();

			if (remaining < SESSION_REFRESH_BUFFER_MS) {
				await _supabaseRef?.auth.refreshSession();
			}
		} catch {
			// Refresh failed — let the original request proceed;
			// the auth state listener will handle redirect if truly expired.
		}
	})();

	try {
		await _refreshPromise;
	} finally {
		_refreshPromise = null;
	}
}

const sessionAwareFetch: typeof globalThis.fetch = async (input, init) => {
	// Only intercept Supabase REST calls (not realtime, not external)
	const url =
		typeof input === "string"
			? input
			: input instanceof URL
				? input.href
				: (input as Request).url;
	if (url.includes(supabaseUrl || "__none__") && url.includes("/rest/")) {
		await ensureFreshSession();
	}
	return globalThis.fetch(input, init);
};

export const supabase = createClient(supabaseUrl || "", supabaseAnonKey || "", {
	auth: {
		autoRefreshToken: true,
		persistSession: true,
		// Disable automatic URL detection to prevent redirect loops
		// We handle auth state manually in App.tsx
		detectSessionInUrl: false,
	},
	realtime: {
		params: {
			// Throttle reconnection to reduce WebSocket spam on flaky networks
			heartbeat_interval: 30,
		},
		reconnectAfterMs: (attempts: number) => {
			// Exponential backoff: 1s, 2s, 4s, 8s, ... capped at 30s
			return Math.min(1000 * 2 ** attempts, 30000);
		},
	},
	global: {
		fetch: sessionAwareFetch,
		headers: {
			// Allow concurrent sessions from multiple browsers
			"x-client-info": `threads-dashboard/${Date.now()}`,
		},
	},
});

// Wire the back-reference so ensureFreshSession can access auth methods
_supabaseRef = supabase;

// Storage key for clearing auth data
export const _getStorageKey = () =>
	`sb-${supabaseUrl?.split("//")[1]?.split(".")[0]}-auth-token`;

// Track intentional sign-outs to avoid showing "session expired" message
export let _isManualSignOut = false;

// Clean up realtime channels + module-level caches on sign out
supabase.auth.onAuthStateChange((event) => {
	if (event === "SIGNED_OUT") {
		unsubscribeAllChannels();
		// Clear module-scoped caches that persist across user sessions
		import("@/src/hooks/useAgencyBranding.js")
			.then((m) => m.resetAgencyBrandingCache())
			.catch(() => {});
		import("@/src/hooks/useReflectionBatch.js")
			.then((m) => m.resetReflectionCache())
			.catch(() => {});
		import("@/src/stores/useAIProviderStore.js")
			.then((m) => m.useAIProviderStore.getState().reset())
			.catch(() => {});
	}
});

// Suppress auth-related unhandled rejections (Supabase throws these
// when refresh tokens expire — the React auth flow handles the redirect)
window.addEventListener("unhandledrejection", (event) => {
	const error = event.reason;
	if (
		error?.message?.includes("Refresh Token Not Found") ||
		error?.message?.includes("Invalid Refresh Token") ||
		error?.message?.includes("invalid_grant") ||
		error?.name === "AuthApiError"
	) {
		event.preventDefault();
	}
});

/**
 * Handle auth errors gracefully - especially for concurrent session scenarios
 * When refresh token is invalid (e.g., from another browser session),
 * clear local storage and let React auth flow handle the redirect
 */
// biome-ignore lint/suspicious/noExplicitAny: auth error shape varies by Supabase version
export const handleAuthError = async (error: any): Promise<boolean> => {
	const isRefreshTokenError =
		error?.message?.includes("Refresh Token") ||
		error?.message?.includes("refresh_token") ||
		error?.message?.includes("invalid_grant") ||
		error?.code === "refresh_token_not_found" ||
		error?.status === 400;

	if (isRefreshTokenError) {
		try {
			await supabase.auth.signOut({ scope: "local" });
		} catch {
			// ignore
		}
		return true; // Error was handled — React auth state will redirect
	}

	return false; // Error was not an auth error
};

// Auth helper functions
export const supabaseAuth = {
	/**
	 * Sign up with email and password
	 */
	signUp: async (email: string, password: string) => {
		const { data, error } = await supabase.auth.signUp({
			email,
			password,
		});
		if (error) throw error;
		return data;
	},

	/**
	 * Sign in with email and password
	 */
	signIn: async (email: string, password: string) => {
		const { data, error } = await supabase.auth.signInWithPassword({
			email,
			password,
		});
		if (error) throw error;
		return data;
	},

	/**
	 * Sign in with Google OAuth
	 */
	signInWithGoogle: async () => {
		const { data, error } = await supabase.auth.signInWithOAuth({
			provider: "google",
			options: {
				redirectTo: `${window.location.origin}/auth/callback`,
			},
		});
		if (error) throw error;
		return data;
	},

	/**
	 * Sign in with Apple OAuth
	 */
	signInWithApple: async () => {
		const { data, error } = await supabase.auth.signInWithOAuth({
			provider: "apple",
			options: {
				redirectTo: `${window.location.origin}/auth/callback`,
			},
		});
		if (error) throw error;
		return data;
	},

	/**
	 * Sign out
	 */
	signOut: async () => {
		_isManualSignOut = true;
		const { error } = await supabase.auth.signOut();
		if (error) {
			_isManualSignOut = false;
			throw error;
		}
	},

	/**
	 * Get current session
	 */
	getSession: async () => {
		const { data, error } = await supabase.auth.getSession();
		if (error) throw error;
		return data.session;
	},

	/**
	 * Get current user
	 */
	getUser: async () => {
		const { data, error } = await supabase.auth.getUser();
		if (error) throw error;
		return data.user;
	},

	/**
	 * Send password reset email
	 */
	resetPassword: async (email: string) => {
		const { error } = await supabase.auth.resetPasswordForEmail(email, {
			redirectTo: `${window.location.origin}/auth/reset-password`,
		});
		if (error) throw error;
	},

	/**
	 * Verify OTP (Email or SMS)
	 */
	verifyOtp: async (
		email: string,
		token: string,
		type: "email" | "recovery" | "signup" | "invite" = "signup",
	) => {
		const { data, error } = await supabase.auth.verifyOtp({
			email,
			token,
			type,
		});
		if (error) throw error;
		return data;
	},

	/**
	 * Resend OTP
	 */
	resendOtp: async (
		email: string,
		type: "signup" | "email_change" = "signup",
	) => {
		const { error } = await supabase.auth.resend({
			email,
			type,
		});
		if (error) throw error;
	},

	/**
	 * Update password
	 */
	updatePassword: async (newPassword: string) => {
		const { error } = await supabase.auth.updateUser({
			password: newPassword,
		});
		if (error) throw error;
	},

	/**
	 * Listen to auth state changes
	 */
	// biome-ignore lint/suspicious/noExplicitAny: Supabase session type not exported
	onAuthStateChange: (callback: (event: string, session: any) => void) => {
		return supabase.auth.onAuthStateChange(callback);
	},
};

// Database helper functions
export const supabaseDb = {
	/**
	 * Get user profile
	 */
	getProfile: async (userId: string) => {
		const { data, error } = await supabase
			.from("profiles")
			.select("*")
			.eq("id", userId)
			.maybeSingle();
		if (error) throw error;
		return data;
	},

	/**
	 * Update user profile
	 */
	updateProfile: async (
		userId: string,
		updates: Partial<Database["public"]["Tables"]["profiles"]["Update"]>,
	) => {
		const { data, error } = await supabase
			.from("profiles")
			.update(updates)
			.eq("id", userId)
			.select()
			.maybeSingle();
		if (error) throw error;
		return data;
	},

	/**
	 * Get user's Threads accounts
	 */
	getAccounts: async (userId: string) => {
		const { data, error } = await supabase
			.from("accounts")
			.select("*")
			.eq("user_id", userId)
			.order("created_at", { ascending: false });
		if (error) throw error;
		return data;
	},

	/**
	 * Get single account
	 */
	getAccount: async (accountId: string) => {
		const { data, error } = await supabase
			.from("accounts")
			.select("*")
			.eq("id", accountId)
			.maybeSingle();
		if (error) throw error;
		return data;
	},

	/**
	 * Get user's posts
	 */
	getPosts: async (
		userId: string,
		options?: { limit?: number | undefined; offset?: number | undefined; status?: string | undefined },
	) => {
		let query = supabase
			.from("posts")
			.select("*")
			.eq("user_id", userId)
			.order("created_at", { ascending: false });

		if (options?.status) {
			query = query.eq("status", options.status);
		}
		if (options?.limit) {
			query = query.limit(options.limit);
		}
		if (options?.offset) {
			query = query.range(
				options.offset,
				options.offset + (options.limit || 50) - 1,
			);
		}

		const { data, error } = await query;
		if (error) throw error;
		return data;
	},

	/**
	 * Create a post
	 */
	createPost: async (post: Database["public"]["Tables"]["posts"]["Insert"]) => {
		const { data, error } = await supabase
			.from("posts")
			.insert(post)
			.select()
			.maybeSingle();
		if (error) throw error;
		return data;
	},

	/**
	 * Update a post
	 */
	updatePost: async (
		postId: string,
		updates: Database["public"]["Tables"]["posts"]["Update"],
	) => {
		const { data, error } = await supabase
			.from("posts")
			.update(updates)
			.eq("id", postId)
			.select()
			.maybeSingle();
		if (error) throw error;
		return data;
	},

	/**
	 * Delete a post
	 */
	deletePost: async (postId: string) => {
		const { error } = await supabase.from("posts").delete().eq("id", postId);
		if (error) throw error;
	},

	/**
	 * Get notifications
	 */
	getNotifications: async (userId: string, unreadOnly = false) => {
		let query = supabase
			.from("notifications")
			.select("*")
			.eq("user_id", userId)
			.order("created_at", { ascending: false })
			.limit(50);

		if (unreadOnly) {
			query = query.eq("read", false);
		}

		const { data, error } = await query;
		if (error) throw error;
		return data;
	},

	/**
	 * Mark notification as read
	 */
	markNotificationRead: async (notificationId: string) => {
		const { error } = await supabase
			.from("notifications")
			.update({ read: true })
			.eq("id", notificationId);
		if (error) throw error;
	},
};

// Storage helper functions
export const supabaseStorage = {
	/**
	 * Upload a file to Supabase Storage
	 * Bucket: 'media'
	 */
	uploadMedia: async (
		userId: string,
		file: File,
		fileName?: string,
	): Promise<{ path: string; url: string }> => {
		const timestamp = Date.now();
		const safeName = (fileName || file.name).replace(/[^a-zA-Z0-9.-]/g, "_");
		const storagePath = `${userId}/${timestamp}_${safeName}`;

		const { data, error } = await supabase.storage
			.from("media")
			.upload(storagePath, file, {
				cacheControl: "3600",
				upsert: false,
			});

		if (error) throw error;

		// Get public URL
		const {
			data: { publicUrl },
		} = supabase.storage.from("media").getPublicUrl(data.path);

		return {
			path: data.path,
			url: publicUrl,
		};
	},

	/**
	 * Delete a file from Supabase Storage
	 */
	deleteMedia: async (storagePath: string): Promise<void> => {
		const { error } = await supabase.storage
			.from("media")
			.remove([storagePath]);

		if (error) throw error;
	},

	/**
	 * Delete multiple files from Supabase Storage
	 */
	deleteMediaBatch: async (storagePaths: string[]): Promise<void> => {
		if (storagePaths.length === 0) return;

		const { error } = await supabase.storage.from("media").remove(storagePaths);

		if (error) throw error;
	},

	/**
	 * Get public URL for a file
	 */
	getPublicUrl: (storagePath: string): string => {
		const {
			data: { publicUrl },
		} = supabase.storage.from("media").getPublicUrl(storagePath);
		return publicUrl;
	},
};

export default supabase;
