// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * API Key authentication middleware for public API v1 endpoints.
 *
 * Validates X-API-Key header, checks scopes, applies rate limiting (100/min).
 * Keys are SHA-256 hashed — plaintext never stored.
 */

import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "./apiResponse.js";
import { logger } from "./logger.js";
import {
	getPrivilegedSupabase,
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./privilegedDb.js";
import { getRedis } from "./redis.js";

const db = () => getPrivilegedSupabase(PRIVILEGED_DB_REASONS.publicApiKeyAuth);
const dbAny = () =>
	getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.publicApiKeyAuth);

export function withApiKey(
	handler: (
		req: VercelRequest,
		res: VercelResponse,
		user: { id: string; scopes: string[]; apiKeyId: string; allowedAccountIds: string[] | null },
	) => Promise<VercelResponse | undefined>,
	requiredScope: "read" | "write" | "admin" = "read",
) {
	return async (req: VercelRequest, res: VercelResponse) => {
		// #599: CORS wildcard is intentional for public API (external consumers).
		// The dashboard UI uses separate endpoints with origin-locked CORS (juno33.com).
		// This public API is authenticated via X-API-Key, not cookies/sessions,
		// so wildcard origin does not weaken security.
		res.setHeader("Access-Control-Allow-Origin", "*");
		res.setHeader(
			"Access-Control-Allow-Methods",
			"GET,OPTIONS,POST,PUT,DELETE",
		);
		res.setHeader(
			"Access-Control-Allow-Headers",
			"Authorization, X-API-Key, Content-Type",
		);
		// Cache preflight responses for 24 hours to reduce OPTIONS requests
		res.setHeader("Access-Control-Max-Age", "86400");
		if (req.method === "OPTIONS") return res.status(200).end();

		const apiKey =
			(req.headers["x-api-key"] as string) ||
			(req.headers.authorization?.startsWith("Bearer juno_ak_")
				? req.headers.authorization.slice(7)
				: null);

		if (!apiKey?.startsWith("juno_ak_")) {
			return apiError(
				res,
				401,
				"Missing or invalid API key. Pass via X-API-Key header.",
			);
		}

		const keyHash = crypto.createHash("sha256").update(apiKey).digest("hex");

		try {
			const redis = getRedis();
			let keyRecord: {
				id: string;
				user_id: string;
				scopes: string[];
				allowed_account_ids: string[] | null;
				is_active: boolean;
				expires_at: string | null;
			} | null = null;

			// Check Redis cache first
			try {
				const cached = await redis.get(`apikey:${keyHash}`);
				if (cached) {
					keyRecord = typeof cached === "string" ? JSON.parse(cached) : cached;
				}
			} catch (err) {
				logger.debug("[withApiKey] Redis API key cache lookup failed", {
					error: String(err),
				});
				// Cache miss
			}

			if (!keyRecord) {
				const { data, error } = await dbAny()
					.from("api_keys")
					.select("id, user_id, scopes, allowed_account_ids, is_active, expires_at")
					.eq("key_hash", keyHash)
					.maybeSingle();

				if (error || !data) return apiError(res, 401, "Invalid API key");
				keyRecord = {
					...data,
					allowed_account_ids: Array.isArray(data.allowed_account_ids)
						? data.allowed_account_ids
						: null,
					is_active: data.is_active ?? false,
				};

				// Cache for 5 min
				try {
					await redis.set(`apikey:${keyHash}`, JSON.stringify(data), {
						ex: 300,
					});
				} catch (err) {
					logger.debug("[withApiKey] Redis API key cache write failed", {
						error: String(err),
					});
					// Non-fatal
				}
			}

			if (!keyRecord) return apiError(res, 401, "Invalid API key");
			if (!keyRecord.is_active)
				return apiError(res, 401, "API key is deactivated");
			if (keyRecord.expires_at && new Date(keyRecord.expires_at) < new Date()) {
				return apiError(res, 401, "API key has expired");
			}

			// Validate scopes is a valid non-empty array before checking
			if (!Array.isArray(keyRecord.scopes) || keyRecord.scopes.length === 0) {
				logger.warn("[withApiKey] Malformed or empty scopes", {
					keyId: keyRecord.id,
					scopes: keyRecord.scopes,
				});
				return apiError(res, 403, "API key has no valid scopes configured");
			}

			if (
				!keyRecord.scopes.includes(requiredScope) &&
				!keyRecord.scopes.includes("admin")
			) {
				return apiError(
					res,
					403,
					`API key missing required scope: ${requiredScope}`,
				);
			}

			const requestedAccountId = extractRequestedAccountId(req);
			const allowedAccountIds = Array.isArray(keyRecord.allowed_account_ids)
				? keyRecord.allowed_account_ids.filter(Boolean)
				: [];
			if (
				requestedAccountId &&
				allowedAccountIds.length > 0 &&
				!allowedAccountIds.includes(requestedAccountId)
			) {
				return apiError(res, 403, "API key is not allowed to access this account");
			}

			// Update last_used_at (fire-and-forget)
			Promise.resolve(
				db()
					.from("api_keys")
					.update({ last_used_at: new Date().toISOString() })
					.eq("id", keyRecord.id),
			).catch((err: unknown) =>
				logger.warn("[withApiKey] Failed to update last_used_at", {
					error: String(err),
				}),
			);

			// #602: Track daily API key usage via Redis counter
			// (PostHog is browser-only, so we use Redis counters instead)
			try {
				const today = new Date().toISOString().split("T")[0]!; // YYYY-MM-DD
				const usageKey = `api_key_usage:${keyRecord.id}:${today}`;
				const usageCount = await redis.incr(usageKey);
				// Set expiry on first increment (48h — enough to span the day + buffer)
				if (usageCount === 1) await redis.expire(usageKey, 172800);
			} catch (err) {
				// Non-fatal — don't block the request for usage tracking
				logger.debug("[withApiKey] Usage counter increment failed", {
					error: String(err),
				});
			}

			// Rate limit: 100 requests per minute per key
			try {
				const rateLimitKey = `apirl:${keyRecord.id}:${Math.floor(Date.now() / 60000)}`;
				const count = await redis.incr(rateLimitKey);
				if (count === 1) await redis.expire(rateLimitKey, 120);
				if (count > 100) {
					res.setHeader("Retry-After", "60");
					return apiError(res, 429, "Rate limit exceeded (100/min)");
				}
			} catch (err) {
				// #593: Fail-closed on rate limit Redis failure for public API
				logger.warn("[withApiKey] Rate limit check failed, blocking request", {
					error: String(err),
				});
				return apiError(res, 503, "Service temporarily unavailable");
			}

			return await handler(req, res, {
				id: keyRecord.user_id,
				scopes: keyRecord.scopes,
				apiKeyId: keyRecord.id,
				allowedAccountIds: allowedAccountIds.length ? allowedAccountIds : null,
			});
		} catch (err) {
			logger.error("[withApiKey] Error", { error: String(err) });
			return apiError(res, 500, "Internal server error");
		}
	};
}

function extractRequestedAccountId(req: VercelRequest): string | null {
	const queryAccount = req.query.account_id ?? req.query.accountId;
	if (typeof queryAccount === "string" && queryAccount.trim()) return queryAccount;

	const body = req.body;
	if (!body || typeof body !== "object" || Array.isArray(body)) return null;
	const record = body as Record<string, unknown>;
	for (const key of ["account_id", "accountId", "instagram_account_id", "instagramAccountId"]) {
		const value = record[key];
		if (typeof value === "string" && value.trim()) return value;
	}
	return null;
}
