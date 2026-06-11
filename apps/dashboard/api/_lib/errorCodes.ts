/**
 * Standardized Error Codes
 *
 * Machine-readable error codes returned in API error responses.
 * These pair with the `code` field in apiResponse.ts error shapes.
 *
 * Usage:
 *   import { ERROR_CODES } from './_lib/errorCodes.js';
 *   return apiError(res, 401, "Token expired", { code: ERROR_CODES.AUTH_EXPIRED });
 */

export const ERROR_CODES = {
	// Auth
	AUTH_MISSING: "AUTH_MISSING",
	AUTH_INVALID: "AUTH_INVALID",
	AUTH_EXPIRED: "AUTH_EXPIRED",

	// Rate limits
	RATE_LIMIT_HOURLY: "RATE_LIMIT_HOURLY",
	RATE_LIMIT_DAILY: "RATE_LIMIT_DAILY",
	RATE_LIMIT_ENDPOINT: "RATE_LIMIT_ENDPOINT",

	// Resources
	ACCOUNT_NOT_FOUND: "ACCOUNT_NOT_FOUND",
	POST_NOT_FOUND: "POST_NOT_FOUND",
	ACCOUNT_SUSPENDED: "ACCOUNT_SUSPENDED",

	// Platform
	THREADS_API_ERROR: "THREADS_API_ERROR",
	INSTAGRAM_API_ERROR: "INSTAGRAM_API_ERROR",
	TOKEN_EXPIRED: "TOKEN_EXPIRED",

	// Tier
	TIER_INSUFFICIENT: "TIER_INSUFFICIENT",
	FEATURE_GATED: "FEATURE_GATED",

	// Input
	VALIDATION_ERROR: "VALIDATION_ERROR",
	INVALID_ACTION: "INVALID_ACTION",
} as const;

export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];
