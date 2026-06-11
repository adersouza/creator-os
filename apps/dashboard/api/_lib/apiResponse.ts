/**
 * Standardized API Response Helpers
 *
 * Ensures consistent error/success shapes across all API routes.
 *
 * Error shape:  { error: string, code?: string, details?: string }
 * Success shape: { success: true, ...data }
 */

import type { VercelResponse } from "@vercel/node";
// biome-ignore lint/style/useNodejsImportProtocol: Vercel requires bare "crypto"
import * as crypto from "crypto";
import { logger } from "./logger.js";

// ============================================================================
// Error Response
// ============================================================================

interface ApiErrorOptions {
	/** Machine-readable error code (e.g., "UNAUTHORIZED", "RATE_LIMITED") */
	code?: string | undefined;
	/** Extra debug info (stripped in production for 500s, kept for 4xx) */
	details?: string | undefined;
	/** Extra fields merged into response body (e.g., currentCount, maxAllowed for limit errors) */
	extra?: Record<string, unknown> | undefined;
}

const ERROR_CODES = {
	400: "BAD_REQUEST",
	401: "UNAUTHORIZED",
	403: "FORBIDDEN",
	404: "NOT_FOUND",
	405: "METHOD_NOT_ALLOWED",
	409: "CONFLICT",
	429: "RATE_LIMITED",
	500: "INTERNAL_ERROR",
} as const;

/**
 * Send a standardized error response.
 *
 * Usage:
 *   return apiError(res, 401, "Not authenticated");
 *   return apiError(res, 500, "Database query failed", { details: err.message });
 */
export function apiError(
	res: VercelResponse,
	status: number,
	message: string,
	options?: ApiErrorOptions,
): VercelResponse {
	const body: Record<string, unknown> = {
		error: message,
		code:
			options?.code ||
			ERROR_CODES[status as keyof typeof ERROR_CODES] ||
			"UNKNOWN",
	};

	if (options?.details) {
		// Auto-sanitize details for 500+ responses, and suppress them entirely
		// in production so callers can log diagnostics without leaking internals.
		if (status < 500 || process.env.NODE_ENV !== "production") {
			body.details =
				status >= 500 ? sanitizeErrorDetails(options.details) : options.details;
		}
	}

	if (options?.extra) {
		Object.assign(body, options.extra);
	}

	return res.status(status).json(body);
}

// ============================================================================
// Success Response
// ============================================================================

/**
 * Send a standardized success response.
 *
 * Usage:
 *   return apiSuccess(res, { posts, total });
 *   return apiSuccess(res, { created: true }, 201);
 */
export function apiSuccess(
	res: VercelResponse,
	data: Record<string, unknown> = {},
	status: number = 200,
): VercelResponse {
	return res.status(status).json({ success: true, ...data });
}

// ============================================================================
// Common Error Shortcuts
// ============================================================================

export function unauthorized(res: VercelResponse, message = "Unauthorized") {
	return apiError(res, 401, message);
}

export function badRequest(res: VercelResponse, message: string) {
	return apiError(res, 400, message);
}

export function notFound(res: VercelResponse, message = "Not found") {
	return apiError(res, 404, message);
}

export function methodNotAllowed(res: VercelResponse) {
	return apiError(res, 405, "Method not allowed");
}

/**
 * Require authentication before returning router-level errors such as
 * "unknown action". This keeps private thin routers from exposing their action
 * surface to unauthenticated callers while avoiding double-wrapping valid
 * actions whose handlers already enforce auth.
 */
export async function authenticatedRouteError(
	req: { headers: { authorization?: string | undefined; "x-forwarded-for"?: string | undefined } },
	res: VercelResponse,
	status: number,
	message: string,
) {
	const user = await getAuthUserOrError(req, res);
	if (!user) return;
	return apiError(res, status, message);
}

export function rateLimited(
	res: VercelResponse,
	message = "Rate limit exceeded",
) {
	return apiError(res, 429, message, { code: "RATE_LIMITED" });
}

export function serverError(
	res: VercelResponse,
	message: string,
	details?: string,
) {
	return apiError(
		res,
		500,
		message,
		details ? { details: sanitizeErrorDetails(details) } : undefined,
	);
}

/**
 * #709: Strip sensitive data from error messages before returning to clients.
 * Removes access tokens, internal URLs, file paths, and stack traces.
 */
export function sanitizeErrorDetails(details: string): string {
	return (
		details
			// Strip access tokens (Meta API, Bearer, etc.)
			.replace(/access_token=[^\s&]+/gi, "access_token=[REDACTED]")
			.replace(/Bearer\s+[A-Za-z0-9._-]+/g, "Bearer [REDACTED]")
			// Strip internal URLs / API endpoints with tokens
			.replace(
				/https?:\/\/graph\.(facebook|instagram|threads)\.com\/[^\s"]*/g,
				"[META_API_URL]",
			)
			// Strip file paths
			.replace(/\/(?:var|Users|home|tmp|opt)\/[^\s"]+/g, "[PATH]")
			// Strip stack traces
			.replace(/\n\s*at .+/g, "")
			.trim()
			.slice(0, 500)
	);
}

// ============================================================================
// Instagram Token Auth Error Handler
// ============================================================================

const IG_AUTH_ERROR_PATTERNS = [
	"session has been invalidated",
	"validating access token",
	"oauthexception",
	"token has expired",
	"token is invalid",
	"password has been changed",
	"password or facebook has changed",
	"session for security reasons",
	"error validating access token",
];

/**
 * Check whether an error message indicates a permanent token auth failure.
 */
export function isIgTokenAuthError(errorMsg: string): boolean {
	const lower = errorMsg.toLowerCase();
	return IG_AUTH_ERROR_PATTERNS.some((p) => lower.includes(p));
}

/**
 * Handle an IG API result error — detects token auth errors and flags the
 * account for re-authentication immediately (rather than waiting for the
 * daily cron). For non-auth errors, returns a standard 500.
 *
 * Usage:
 *   if (!result.success) {
 *     return await handleIgAuthError(res, accountId, userId, result.error || "Unknown error");
 *   }
 */
export async function handleIgAuthError(
	res: VercelResponse,
	accountId: string,
	userId: string,
	errorMsg: string,
): Promise<VercelResponse> {
	if (isIgTokenAuthError(errorMsg)) {
		const { logger } = await import("./logger.js");
		logger.warn("[IG] Token auth error — flagging needs_reauth", {
			accountId,
			error: errorMsg,
		});

		try {
			const { getSupabase } = await import("./supabase.js");
			await getSupabase()
				.from("instagram_accounts")
				.update({
					needs_reauth: true,
					is_active: false,
					status: "needs_reauth",
					updated_at: new Date().toISOString(),
				})
				.eq("id", accountId)
				.eq("user_id", userId);

			const { deliverNotification } = await import("./deliverNotification.js");
			await deliverNotification({
				userId,
				type: "token_reauth_needed",
				title: "Instagram account needs reconnection",
				message:
					"Your Instagram account has been disconnected because the access token was invalidated. Please reconnect it in Settings.",
				data: { accountId, platform: "instagram" },
			});
		} catch {
			// Best-effort — don't block the response
		}

		return apiError(
			res,
			401,
			"Your Instagram session has expired. Please reconnect your account in Settings.",
		);
	}

	return apiError(res, 500, errorMsg);
}

// ============================================================================
// Auth Helper
// ============================================================================

/**
 * Extract and validate user from Bearer token.
 * Returns user object or sends 401 and returns null.
 *
 * Usage:
 *   const user = await getAuthUserOrError(req, res);
 *   if (!user) return; // 401 already sent
 */
export async function getAuthUserOrError(
	req: { headers: { authorization?: string | undefined; "x-forwarded-for"?: string | undefined } },
	res: VercelResponse,
): Promise<{ id: string; email?: string | undefined } | null> {
	const authHeader = req.headers.authorization;
	if (!authHeader?.startsWith("Bearer ")) {
		unauthorized(res);
		return null;
	}

	// Check auth lockout before attempting validation
	const {
		checkAuthLockout,
		recordAuthFailure,
		resetAuthFailures,
		getLockoutIdentifier,
	} = await import("./authLockout.js");
	const lockoutId = getLockoutIdentifier(req);
	const lockout = await checkAuthLockout(lockoutId);
	if (lockout) {
		res.setHeader("Retry-After", String(lockout.retryAfterSec));
		return rateLimited(
			res,
			`Too many failed attempts. Try again in ${Math.ceil(lockout.retryAfterSec / 60)} minutes.`,
		) as unknown as null;
	}

	const token = authHeader.slice(7);

	// API keys are intentionally not valid session credentials. Public API
	// routes that support them must use withApiKey(requiredScope), which enforces
	// per-key scopes. Accepting them here lets low-scope keys act as full users.
	if (token.startsWith("juno_ak_")) {
		recordAuthFailure(lockoutId).catch((recordError) => {
			logger.warn("[apiResponse] Failed to record API key session-auth attempt", {
				lockoutId,
				error: String(recordError),
			});
		});
		unauthorized(res);
		return null;
	}

	// JWT path
	const { getSupabase } = await import("./supabase.js");
	const {
		data: { user },
		error,
	} = await getSupabase().auth.getUser(token);
	if (error || !user) {
		recordAuthFailure(lockoutId).catch((recordError) => {
			logger.warn("[apiResponse] Failed to record JWT auth failure", {
				lockoutId,
				error: String(recordError),
			});
		});
		unauthorized(res);
		return null;
	}

	resetAuthFailures(lockoutId).catch((resetError) => {
		logger.warn("[apiResponse] Failed to reset JWT auth failures", {
			lockoutId,
			error: String(resetError),
		});
	});
	return user;
}

// ============================================================================
// Cron Auth Helper
// ============================================================================

/**
 * Validate CRON_SECRET for cron job endpoints.
 * Returns true if authorized, or sends 401 and returns false.
 *
 * Usage:
 *   if (!verifyCronAuth(req, res)) return;
 */
export function verifyCronAuth(
	req: { headers: { authorization?: string | undefined } },
	res: VercelResponse,
): boolean {
	const expectedSecret = process.env.CRON_SECRET;
	if (!expectedSecret) {
		unauthorized(res, "Cron secret not configured");
		return false;
	}
	const cronSecret = req.headers.authorization || "";
	const expected = `Bearer ${expectedSecret}`;
	if (
		cronSecret.length !== expected.length ||
		!crypto.timingSafeEqual(Buffer.from(cronSecret), Buffer.from(expected))
	) {
		unauthorized(res, "Invalid cron secret");
		return false;
	}
	return true;
}

/**
 * Validate OAuth state parameter (CSRF protection).
 * Returns true if valid, or sends 400 and returns false.
 * Used by all 3 OAuth callback routes (Threads, IG, FB-IG).
 */
export function validateOAuthState(
	state: unknown,
	res: VercelResponse,
): state is string {
	if (!state || typeof state !== "string" || state.trim() === "") {
		apiError(res, 400, "Missing or empty OAuth state parameter");
		return false;
	}
	// State must be alphanumeric/dash/underscore (UUID or random string), max 128 chars
	if (!/^[a-zA-Z0-9_-]{8,128}$/.test(state)) {
		apiError(res, 400, "Invalid OAuth state parameter format");
		return false;
	}
	return true;
}
