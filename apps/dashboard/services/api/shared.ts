/// <reference path="../../vite-env.d.ts" />
/**
 * Shared utilities and context for API service modules
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { emitApiError } from "../../src/utils/apiErrorEmitter.js";
import type { Database } from "../../types/supabase.js";
import logger from "@/utils/logger";
import { supabase } from "../supabase.js";

export { logger, supabase };

/**
 * Returns the shared Supabase client for service modules.
 * Critical for complex queries and custom views.
 */
export function getSupabaseAny(): SupabaseClient<Database> {
	return supabase;
}

/**
 * Supabase `.neq()` excludes NULL rows because SQL three-valued logic treats
 * NULL != value as unknown. Use this for nullable status/flag columns where
 * NULL means "not the excluded value".
 */
export function neqOrNull<T extends { or: (clause: string) => T }>(
	query: T,
	column: string,
	value: string | number | boolean,
): T {
	const encodedValue =
		typeof value === "string" ? value.replace(/"/g, '\\"') : String(value);
	return query.or(`${column}.neq.${encodedValue},${column}.is.null`);
}

// Simple concurrency limiter for parallel processing
export function createConcurrencyLimiter(maxConcurrency: number) {
	let running = 0;
	const queue: (() => void)[] = [];

	const runNext = () => {
		if (queue.length > 0 && running < maxConcurrency) {
			const next = queue.shift();
			if (!next) return;
			running++;
			next();
		}
	};

	return async <T>(fn: () => Promise<T>): Promise<T> => {
		return new Promise((resolve, reject) => {
			const run = async () => {
				try {
					const result = await fn();
					resolve(result);
				} catch (error) {
					reject(error);
				} finally {
					running--;
					runNext();
				}
			};

			if (running < maxConcurrency) {
				running++;
				run();
			} else {
				queue.push(run);
			}
		});
	};
}

// Retry helper with exponential backoff for transient Supabase errors (502, timeouts)
export async function withRetry<T>(
	fn: () => Promise<T>,
	options: { retries?: number | undefined; baseDelay?: number | undefined; name?: string | undefined } = {},
): Promise<T> {
	const { retries = 3, baseDelay = 1000, name = "operation" } = options;
	let lastError: Error | null = null;

	for (let attempt = 0; attempt < retries; attempt++) {
		try {
			return await fn();
		} catch (error: unknown) {
			lastError = error instanceof Error ? error : new Error(String(error));
			const msg = lastError.message;

			// Never retry auth errors — they won't resolve with retries
			const isAuthError =
				msg?.includes("401") ||
				msg?.includes("403") ||
				msg?.includes("Unauthorized") ||
				msg?.includes("Forbidden") ||
				msg?.includes("Not authenticated") ||
				(error as { status?: number | undefined })?.status === 401 ||
				(error as { status?: number | undefined })?.status === 403;
			if (isAuthError) {
				throw error;
			}

			const isNetworkDown = msg?.includes("Load failed");
			const isRetryable =
				isNetworkDown ||
				msg?.includes("502") ||
				msg?.includes("503") ||
				msg?.includes("timeout") ||
				(error as { code?: string | undefined })?.code === "PGRST301"; // Supabase timeout

			// For "Load failed" (network down), only retry once instead of 3 times
			const maxRetries = isNetworkDown ? 1 : retries;
			if (!isRetryable || attempt >= maxRetries - 1) {
				throw error;
			}

			const delay = baseDelay * 2 ** attempt; // 1s, 2s, 4s
			logger.warn(
				`[Retry] ${name} failed (attempt ${attempt + 1}/${retries}), retrying in ${delay}ms...`,
			);
			await new Promise((resolve) => setTimeout(resolve, delay));
		}
	}

	throw lastError;
}

/**
 * #475: Auto-retry wrapper for frontend GET fetch requests.
 * Retries once after 1 second on network errors (TypeError: Failed to fetch)
 * or 5xx status codes. Only used for idempotent GET requests — never for
 * POST/PUT/DELETE to avoid duplicate side effects.
 */
export async function fetchWithGetRetry(
	url: string,
	options?: RequestInit,
): Promise<Response> {
	const method = (options?.method || "GET").toUpperCase();

	// Only retry GET requests (idempotent). Non-GET requests pass through directly.
	if (method !== "GET") {
		return fetch(url, options);
	}

	try {
		const response = await fetch(url, options);

		// Retry once on 5xx server errors
		if (response.status >= 500) {
			logger.warn(
				`[fetchWithGetRetry] GET ${url} returned ${response.status}, retrying in 1s...`,
			);
			await new Promise((resolve) => setTimeout(resolve, 1000));
			return fetch(url, options);
		}

		return response;
	} catch (error: unknown) {
		// Retry once on network errors (TypeError: Failed to fetch / Load failed)
		const isNetworkError =
			error instanceof TypeError &&
			(error.message.includes("Failed to fetch") ||
				error.message.includes("Load failed") ||
				error.message.includes("NetworkError"));

		if (isNetworkError) {
			logger.warn(
				`[fetchWithGetRetry] GET ${url} network error, retrying in 1s...`,
			);
			await new Promise((resolve) => setTimeout(resolve, 1000));
			return fetch(url, options);
		}

		throw error;
	}
}

// Type for unsubscribe function
export type Unsubscribe = () => void;

/**
 * Safely parse JSON response, handling non-JSON responses gracefully
 * In local dev, Vite returns HTML with 200 status for missing API routes
 */
export const safeJsonParse = async <T = unknown>(
	response: Response,
	context: string,
): Promise<T> => {
	const contentType = response.headers.get("content-type");
	const isJson = contentType?.includes("application/json");

	if (response.status === 429) {
		const retryAfter = parseInt(
			response.headers.get("Retry-After") || "30",
			10,
		);
		emitApiError({
			type: "rate_limit",
			message: "Rate limit reached. Please wait.",
			retryAfter,
		});
		throw new Error("Rate limit reached. Please try again later.");
	}

	// #468: Emit auth error on 401/403 to trigger re-auth UI
	if (response.status === 401 || response.status === 403) {
		emitApiError({
			type: "auth",
			message:
				response.status === 401
					? "Session expired. Please reconnect your account."
					: "Access denied. Your account may need to be reconnected.",
		});
		throw new Error(`Authentication error (${response.status})`);
	}

	if (response.status === 404) {
		throw new Error(`${context} API not available (requires deployment)`);
	}

	// In local dev, Vite returns HTML (200) for missing API routes (SPA fallback)
	if (!isJson) {
		const isDev = import.meta.env.DEV;
		if (isDev) {
			throw new Error(`${context} API not available (requires deployment)`);
		}
		throw new Error(
			`Invalid response from ${context} API (${response.status})`,
		);
	}

	return (await response.json()) as T;
};

// Get current user ID (async) — retries briefly to handle session restoration on page refresh
export async function getUserIdAsync(): Promise<string> {
	// First try: session may already be ready
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (session?.user) {
		return session.user.id;
	}

	// Session not ready yet — fall back to localStorage (instant, no network)
	try {
		return getUserId();
	} catch {
		// localStorage also empty
	}

	// Last resort: wait briefly for async session restoration then retry
	for (let i = 0; i < 5; i++) {
		await new Promise((r) => setTimeout(r, 200));
		const {
			data: { session: retrySession },
		} = await supabase.auth.getSession();
		if (retrySession?.user) {
			return retrySession.user.id;
		}
	}

	throw new Error("User not authenticated");
}

// Sync version for compatibility (uses localStorage)
export function getUserId(): string {
	const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
	if (!supabaseUrl?.includes("//")) {
		logger.error("[apiService] Invalid VITE_SUPABASE_URL configuration");
		throw new Error("User not authenticated");
	}
	const projectRef = supabaseUrl.split("//")[1]?.split(".")[0];
	if (!projectRef) {
		logger.error(
			"[apiService] Could not extract project ref from Supabase URL",
		);
		throw new Error("User not authenticated");
	}
	const storageKey = `sb-${projectRef}-auth-token`;
	const sessionStr = localStorage.getItem(storageKey);
	if (sessionStr) {
		try {
			const session = JSON.parse(sessionStr);
			if (session?.user?.id) {
				return session.user.id;
			}
		} catch {
			// ignore parse errors
		}
	}
	throw new Error("User not authenticated");
}

// Helper to get current session
export async function getSession() {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	return session;
}

// Helper to detect media type from URL (fast extension check + HEAD fallback)
export function detectMediaType(url: string): "image" | "video" {
	const lowerUrl = url.toLowerCase();
	const videoExtensions = [".mp4", ".mov", ".avi", ".webm", ".m4v", ".mkv"];
	const hasVideoExtension = videoExtensions.some((ext) =>
		lowerUrl.includes(ext),
	);
	const hasVideoInPath =
		lowerUrl.includes("/video/") || lowerUrl.includes("video=");
	return hasVideoExtension || hasVideoInPath ? "video" : "image";
}

/**
 * Async media type detection with HEAD request fallback.
 * Use this when the URL has no recognizable extension (e.g., CDN URLs with query params).
 * Falls back to the fast extension-based check first, then tries a HEAD request.
 */
export async function detectMediaTypeAsync(
	url: string,
): Promise<"image" | "video"> {
	// Fast path: try extension-based detection first
	const lowerUrl = url.toLowerCase();
	const videoExtensions = [".mp4", ".mov", ".avi", ".webm", ".m4v", ".mkv"];
	const imageExtensions = [
		".jpg",
		".jpeg",
		".png",
		".gif",
		".webp",
		".bmp",
		".svg",
		".avif",
	];
	const hasVideoExtension = videoExtensions.some((ext) =>
		lowerUrl.includes(ext),
	);
	if (
		hasVideoExtension ||
		lowerUrl.includes("/video/") ||
		lowerUrl.includes("video=")
	) {
		return "video";
	}
	const hasImageExtension = imageExtensions.some((ext) =>
		lowerUrl.includes(ext),
	);
	if (hasImageExtension) {
		return "image";
	}

	// Slow path: no recognizable extension — try HEAD request for Content-Type
	try {
		const controller = new AbortController();
		const timeout = setTimeout(() => controller.abort(), 5000);
		const response = await fetch(url, {
			method: "HEAD",
			signal: controller.signal,
		});
		clearTimeout(timeout);

		const contentType = response.headers.get("content-type") || "";
		if (contentType.startsWith("video/")) {
			return "video";
		}
		// image/*, application/octet-stream, or anything else defaults to image
	} catch {
		// HEAD request failed (CORS, network, timeout) — fall back to image
	}

	return "image";
}

/**
 * Execute a Supabase query with standardized error handling.
 * Logs errors with the provided context string.
 * If a fallback is provided, returns it on error instead of throwing.
 */
export async function dbQuery<T>(
	query: PromiseLike<{ data: T | null; error: unknown }>,
	context: string,
	fallback?: T,
): Promise<T> {
	const { data, error } = await query;
	if (error) {
		logger.error(`${context}:`, error);
		if (fallback !== undefined) return fallback;
		throw error;
	}
	return data as T;
}

/**
 * Create a prefixed logger for a service module.
 * Every log call automatically prepends [serviceName].
 */
export function createServiceLogger(serviceName: string) {
	return {
		error: (msg: string, ...args: unknown[]) =>
			logger.error(`[${serviceName}] ${msg}`, ...args),
		warn: (msg: string, ...args: unknown[]) =>
			logger.warn(`[${serviceName}] ${msg}`, ...args),
		info: (msg: string, ...args: unknown[]) =>
			logger.info(`[${serviceName}] ${msg}`, ...args),
		debug: (msg: string, ...args: unknown[]) =>
			logger.debug(`[${serviceName}] ${msg}`, ...args),
		log: (msg: string, ...args: unknown[]) =>
			logger.log(`[${serviceName}] ${msg}`, ...args),
	};
}
