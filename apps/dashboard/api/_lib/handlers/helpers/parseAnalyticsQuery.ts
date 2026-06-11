// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Common Analytics Query Parameter Parser
 *
 * Extracts and validates common analytics query params with sensible defaults.
 * Eliminates the repeated pattern:
 *   const days = Math.min(Math.max(parseInt(req.query.days as string) || 30, 1), 90);
 *   const accountId = req.query.accountId as string;
 *
 * Usage:
 *   const params = parseAnalyticsQuery(req.query);
 *   // params.accountId, params.days, params.limit, params.offset, params.period
 */

import type { VercelRequest } from "@vercel/node";

export interface AnalyticsQueryParams {
	/** Account ID (may be undefined if not provided) */
	accountId: string | undefined;
	/** Number of days to look back (clamped 1-maxDays, default 30) */
	days: number;
	/** Max results to return (clamped 1-maxLimit, default 50) */
	limit: number;
	/** Pagination offset (clamped 0-10000, default 0) */
	offset: number;
	/** Optional platform filter */
	platform: string | undefined;
	/** ISO cutoff timestamp for the given days */
	cutoff: string;
	/** ISO cutoff date string (YYYY-MM-DD) for date columns */
	cutoffDate: string;
}

export interface ParseAnalyticsOptions {
	/** Default days if not specified (default: 30) */
	defaultDays?: number | undefined;
	/** Maximum allowed days (default: 90) */
	maxDays?: number | undefined;
	/** Default limit if not specified (default: 50) */
	defaultLimit?: number | undefined;
	/** Maximum allowed limit (default: 500) */
	maxLimit?: number | undefined;
}

/**
 * Parse common analytics query parameters from a request's query object.
 */
export function parseAnalyticsQuery(
	query: VercelRequest["query"],
	options: ParseAnalyticsOptions = {},
): AnalyticsQueryParams {
	const {
		defaultDays = 30,
		maxDays = 90,
		defaultLimit = 50,
		maxLimit = 500,
	} = options;

	const accountId = (query.accountId as string) || undefined;
	const days = Math.min(
		Math.max(parseInt(query.days as string, 10) || defaultDays, 1),
		maxDays,
	);
	const limit = Math.min(
		Math.max(parseInt(query.limit as string, 10) || defaultLimit, 1),
		maxLimit,
	);
	const offset = Math.min(
		Math.max(parseInt(query.offset as string, 10) || 0, 0),
		10000,
	);
	const platform = (query.platform as string) || undefined;

	const cutoffMs = Date.now() - days * 86_400_000;
	const cutoff = new Date(cutoffMs).toISOString();
	const cutoffDate = cutoff.split("T")[0]!;

	return { accountId, days, limit, offset, platform, cutoff, cutoffDate: cutoffDate! };
}
