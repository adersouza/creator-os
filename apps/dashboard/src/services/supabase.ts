/**
 * Supabase Client Configuration
 *
 * Initialize Supabase client for auth and database operations
 * Supports concurrent sessions from multiple browsers (e.g., AdsPower)
 */

import { createClient } from "@supabase/supabase-js";
import type { Session, User } from "@supabase/supabase-js";
import type { Database } from "@/types/supabase";
import { queryClient, queryPersister } from "@/lib/queryClient";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
const supabaseClientUrl = supabaseUrl || "https://placeholder.supabase.co";
const supabaseClientAnonKey = supabaseAnonKey || "test-anon-key";
const AUTH_BOOT_TIMEOUT_MS = 3500;
const AUTH_PASSWORD_TOKEN_TIMEOUT_MS = 15_000;
const AUTH_PASSWORD_TOKEN_RETRIES = 2;

if (!supabaseUrl || !supabaseAnonKey) {
	// biome-ignore lint/suspicious/noConsole: dev-only env var guard
	if (import.meta.env.DEV) console.warn('[supabase] Missing env vars: VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY');
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

			const expiresAt = (session.expires_at ?? 0) * 1000; // seconds -> ms
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

function isPasswordTokenRequest(url: string, init?: RequestInit) {
	const method =
		init?.method ??
		(typeof init === "undefined" ? undefined : "GET");
	return (
		url.includes(supabaseUrl || "__none__") &&
		url.includes("/auth/v1/token") &&
		url.includes("grant_type=password") &&
		(!method || method.toUpperCase() === "POST")
	);
}

function delay(ms: number) {
	return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isRetryableAuthResponse(response: Response) {
	return response.status === 502 || response.status === 503 || response.status === 504;
}

function isRetryableAuthError(error: unknown) {
	const name = error instanceof Error ? error.name : "";
	const message = error instanceof Error ? error.message : "";
	return (
		name === "AbortError" ||
		message.includes("Failed to fetch") ||
		message.includes("NetworkError") ||
		message.includes("Load failed")
	);
}

async function fetchPasswordTokenWithRetry(
	input: Parameters<typeof globalThis.fetch>[0],
	init: Parameters<typeof globalThis.fetch>[1],
) {
	let lastError: unknown;

	for (let attempt = 0; attempt <= AUTH_PASSWORD_TOKEN_RETRIES; attempt += 1) {
		const controller = new AbortController();
		const timeout = window.setTimeout(
			() => controller.abort(),
			AUTH_PASSWORD_TOKEN_TIMEOUT_MS,
		);

		try {
			const requestInput = input instanceof Request ? input.clone() : input;
			const response = await globalThis.fetch(requestInput, {
				...init,
				signal: controller.signal,
			});
			window.clearTimeout(timeout);

			if (!isRetryableAuthResponse(response) || attempt === AUTH_PASSWORD_TOKEN_RETRIES) {
				return response;
			}
		} catch (error) {
			window.clearTimeout(timeout);
			lastError = error;
			if (!isRetryableAuthError(error) || attempt === AUTH_PASSWORD_TOKEN_RETRIES) {
				throw error;
			}
		}

		await delay(600 * (attempt + 1));
	}

	throw lastError instanceof Error ? lastError : new Error("Auth token request failed");
}

const sessionAwareFetch: typeof globalThis.fetch = async (input, init) => {
	// Only intercept Supabase REST calls (not realtime, not external)
	const url =
		typeof input === "string"
			? input
			: input instanceof URL
				? input.href
				: (input as Request).url;
	if (isPasswordTokenRequest(url, init)) {
		return fetchPasswordTokenWithRetry(input, init);
	}
	if (url.includes(supabaseUrl || "__none__") && url.includes("/rest/")) {
		await ensureFreshSession();
	}
	return globalThis.fetch(input, init);
};

export const supabase = createClient(supabaseClientUrl, supabaseClientAnonKey, {
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

function withTimeout<T>(
	promise: Promise<T>,
	timeoutMs: number,
	fallback: T,
): Promise<T> {
	return new Promise((resolve) => {
		let settled = false;
		const timer = window.setTimeout(() => {
			if (settled) return;
			settled = true;
			resolve(fallback);
		}, timeoutMs);

		promise
			.then((value) => {
				if (settled) return;
				settled = true;
				window.clearTimeout(timer);
				resolve(value);
			})
			.catch(() => {
				if (settled) return;
				settled = true;
				window.clearTimeout(timer);
				resolve(fallback);
			});
	});
}

function readStoredSession(): Session | null {
	if (typeof window === "undefined") return null;
	try {
		const raw = localStorage.getItem(_getStorageKey());
		if (!raw) return null;
		const parsed = JSON.parse(raw);
		const candidate = parsed?.currentSession ?? parsed;
		if (
			candidate &&
			typeof candidate === "object" &&
			candidate.access_token &&
			candidate.refresh_token &&
			candidate.user?.id
		) {
			// Don't serve an expired session as fallback (30s clock-skew buffer)
			const expiresMs = (candidate.expires_at ?? 0) * 1000;
			if (expiresMs > 0 && expiresMs < Date.now() - 30_000) return null;
			return candidate as Session;
		}
	} catch {
		// ignore parse/storage errors
	}
	return null;
}

export function getStoredSession(): Session | null {
	return readStoredSession();
}

export function getStoredUser(): User | null {
	return readStoredSession()?.user ?? null;
}

const originalGetSession = supabase.auth.getSession.bind(supabase.auth);
const originalGetUser = supabase.auth.getUser.bind(supabase.auth);

supabase.auth.getSession = (async () => {
	const fallback = getStoredSession();
	if (fallback) {
		// Supabase's Web Locks session read can stall under React StrictMode when
		// many dashboard hooks mount together. A valid stored session is the same
		// token the client would read, so serve it immediately and let downstream
		// API/Supabase calls prove freshness.
		return { data: { session: fallback }, error: null };
	}
	return withTimeout(
		originalGetSession(),
		AUTH_BOOT_TIMEOUT_MS,
		// biome-ignore lint/suspicious/noExplicitAny: union narrowing fallback for TS6
		{ data: { session: null }, error: null } as any,
	);
}) as typeof supabase.auth.getSession;

supabase.auth.getUser = (async () => {
	const fallback = getStoredUser();
	if (fallback) {
		return { data: { user: fallback }, error: null };
	}
	return withTimeout(
		originalGetUser(),
		AUTH_BOOT_TIMEOUT_MS,
		// biome-ignore lint/suspicious/noExplicitAny: union narrowing fallback for TS6
		{ data: { user: null }, error: null } as any,
	);
}) as typeof supabase.auth.getUser;

// Track intentional sign-outs to avoid showing "session expired" message
export let _isManualSignOut = false;

// Clean up realtime channels + module-level caches on sign out
supabase.auth.onAuthStateChange((event) => {
	if (event === "SIGNED_OUT") {
		// Nuke every TanStack Query cache entry so the next signed-in user
		// never sees the previous user's data. Without this, the (now 24h)
		// gcTime keeps User A's payloads alive in memory after sign-out —
		// a real tenant-leak window on shared devices. Also drop the IDB
		// snapshot so the next hard refresh doesn't rehydrate User A's
		// cache before the new auth session resolves.
		queryClient.clear();
		void queryPersister.removeClient();
		// Belt-and-suspenders: also clear module-scoped caches that live
		// outside TanStack's cache.
		import("@/hooks/useAgencyBranding")
			.then((m) => m.resetAgencyBrandingCache())
			.catch(() => {});
		import("@/hooks/useReflectionBatch")
			.then((m) => m.resetReflectionCache())
			.catch(() => {});
		import("@/stores/useAIProviderStore")
			.then((m) => m.useAIProviderStore.getState().reset())
			.catch(() => {});
	}
});

// Suppress auth-related unhandled rejections.
// Three categories we quietly drop:
// 1. Refresh-token failures — the React auth flow handles the redirect
// 2. AuthApiError — caller-facing errors are thrown elsewhere; these are
//    background refresh attempts we can safely swallow
// 3. AbortError from "Lock was stolen by another request" — happens
//    constantly in React StrictMode dev because effects double-invoke and
//    each pass races for sb-<ref>-auth-token. The winning call still
//    resolves; the loser's rejection is noise.
window.addEventListener("unhandledrejection", (event) => {
	const error = event.reason;
	const msg = error?.message || "";
	if (
		msg.includes("Refresh Token Not Found") ||
		msg.includes("Invalid Refresh Token") ||
		msg.includes("invalid_grant") ||
		// Cover every lock-race variant supabase-js throws:
		//   "Lock was stolen by another request" (AbortError)
		//   "Lock ... was released because another request stole it" (Error)
		msg.includes("Lock was stolen") ||
		msg.includes("was released because another request stole it") ||
		msg.includes("lock:sb-") ||
		error?.name === "AuthApiError" ||
		(error?.name === "AbortError" && msg.includes("Lock"))
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

// MFA challenge state returned by `signIn` / `getMfaStatus`. When
// `needsMfa` is true the caller must block navigation until the user
// completes `verifyMfa(factorId, code)`.
export type MfaStatus =
	| { needsMfa: false }
	| { needsMfa: true; factorId: string };

export type SignInResult =
	| { status: "signed-in" }
	| { status: "mfa-required"; factorId: string };

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
	 * Sign in with email and password.
	 *
	 * Returns a discriminated result so the UI can distinguish between a
	 * fully-signed-in session (AAL2 or no MFA enrolled) and one that still
	 * owes a TOTP challenge. Callers MUST NOT treat `mfa-required` as "signed
	 * in" — the session is AAL1 and every protected route bounces back here.
	 */
	signIn: async (
		email: string,
		password: string,
	): Promise<SignInResult> => {
		const { error } = await supabase.auth.signInWithPassword({
			email,
			password,
		});
		if (error) throw error;
		const mfa = await supabaseAuth.getMfaStatus();
		return mfa.needsMfa && mfa.factorId
			? { status: "mfa-required", factorId: mfa.factorId }
			: { status: "signed-in" };
	},

	/**
	 * Inspect the current session's AAL. When a user has enrolled TOTP but
	 * only cleared password (AAL1), Supabase reports nextLevel=aal2 — we use
	 * that plus a verified-factor lookup as the single source of truth for
	 * "needs challenge". Callable on any active session, including one that
	 * was just established by signInWithPassword.
	 */
	getMfaStatus: async (): Promise<MfaStatus> => {
		return withTimeout(
			(async () => {
				const { data: aal, error: aalErr } =
					await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
				if (aalErr || !aal) return { needsMfa: false };
				if (aal.currentLevel !== "aal1" || aal.nextLevel !== "aal2") {
					return { needsMfa: false };
				}
				const { data: factors, error: listErr } =
					await supabase.auth.mfa.listFactors();
				if (listErr) return { needsMfa: false };
				const totp = factors?.totp?.find((f) => f.status === "verified");
				return totp ? { needsMfa: true, factorId: totp.id } : { needsMfa: false };
			})(),
			AUTH_BOOT_TIMEOUT_MS,
			{ needsMfa: false },
		);
	},

	/**
	 * Complete the TOTP challenge. On success the session is upgraded to
	 * AAL2 automatically by the Supabase client; callers just await this
	 * and navigate on resolve.
	 *
	 * Some auth-lock races (realtime socket contending with the auth
	 * token write) leave verify()'s promise hanging even though the
	 * server-side upgrade succeeded. We race a short timeout and fall
	 * back to polling AAL — if it's aal2, the upgrade landed and we
	 * proceed regardless of the stuck promise.
	 */
	verifyMfa: async (factorId: string, code: string): Promise<void> => {
		const { data: ch, error: e1 } = await supabase.auth.mfa.challenge({
			factorId,
		});
		if (e1 || !ch) throw e1 ?? new Error("Challenge failed");

		const verifyPromise = supabase.auth.mfa
			.verify({ factorId, challengeId: ch.id, code })
			.then(({ error }) => {
				if (error) throw error;
			});

		let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
		const timeoutPromise = new Promise<"timeout">((resolve) => {
			timeoutHandle = setTimeout(() => resolve("timeout"), 2500);
		});

		const outcome = await Promise.race([
			verifyPromise.then(() => "ok" as const),
			timeoutPromise,
		]);

		if (timeoutHandle !== undefined) clearTimeout(timeoutHandle);

		if (outcome === "ok") return;

		// Verify promise hung — check if the upgrade actually landed.
		const { data: aal } =
			await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
		if (aal?.currentLevel === "aal2") return;

		// Not upgraded — let the original verify error propagate, or throw generic.
		await verifyPromise;
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
		const fallback = getStoredSession();
		if (fallback) return fallback;
		return withTimeout(
			originalGetSession().then(({ data, error }) => {
				if (error) throw error;
				return data.session;
			}),
			AUTH_BOOT_TIMEOUT_MS,
			fallback,
		);
	},

	/**
	 * Get current user
	 */
	getUser: async () => {
		const fallback = getStoredUser();
		if (fallback) return fallback;
		return withTimeout(
			originalGetUser().then(({ data, error }) => {
				if (error) throw error;
				return data.user;
			}),
			AUTH_BOOT_TIMEOUT_MS,
			fallback,
		);
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
