/**
 * Fleet health — per-account grid.
 *
 * GET /api/analytics?action=fleet-health-accounts&limit=10
 *
 * Complements get_fleet_health() RPC (fleet-level rollup). Returns a
 * per-account traffic-light breakdown sorted worst-first (crit → warn →
 * healthy), so operators see which accounts to fix before the rest.
 *
 * Classification mirrors the RPC logic to stay consistent:
 *   crit    — needs_reauth=true OR token expired
 *   warn    — last_synced_at > 72h ago
 *   healthy — otherwise
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuthDb } from "../../middleware.js";
import { parseQueryOrError } from "../../validation.js";

const QuerySchema = z.object({
	limit: z.coerce.number().int().min(1).max(50).optional().default(10),
});

const DORMANT_MS = 72 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

type Bucket = "crit" | "warn" | "healthy";
const BUCKET_RANK: Record<Bucket, number> = { crit: 0, warn: 1, healthy: 2 };

function classify(row: {
	needs_reauth: boolean | null;
	token_expires_at: string | null;
	last_synced_at: string | null;
}): Bucket {
	const now = Date.now();
	if (row.needs_reauth === true) return "crit";
	if (row.token_expires_at && Date.parse(row.token_expires_at) < now) return "crit";
	if (row.last_synced_at && now - Date.parse(row.last_synced_at) > DORMANT_MS) return "warn";
	return "healthy";
}

function reasonFor(row: {
	needs_reauth: boolean | null;
	token_expires_at: string | null;
	last_synced_at: string | null;
}): string | null {
	const now = Date.now();
	if (row.needs_reauth === true) return "Needs reauth";
	if (row.token_expires_at && Date.parse(row.token_expires_at) < now) return "Token expired";
	if (row.last_synced_at && now - Date.parse(row.last_synced_at) > DORMANT_MS) {
		const hours = Math.round((now - Date.parse(row.last_synced_at)) / (60 * 60 * 1000));
		return `No sync in ${hours}h`;
	}
	return null;
}

function tokenDaysLeft(tokenExpiresAt: string | null, now: number): number | null {
	if (!tokenExpiresAt) return null;
	const expiresMs = Date.parse(tokenExpiresAt);
	if (!Number.isFinite(expiresMs)) return null;
	return Math.ceil((expiresMs - now) / DAY_MS);
}

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, { user, userDb }) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { limit } = parsed;
		// biome-ignore lint/suspicious/noExplicitAny: simplifies the cross-table account shape
		const db = userDb as any;

		const [threadsRes, igRes] = await Promise.all([
			db
				.from("accounts")
				.select(
					"id, username, needs_reauth, token_expires_at, last_synced_at, group_id",
				)
				.eq("user_id", user.id)
				.eq("is_active", true)
				.eq("is_retired", false),
			db
				.from("instagram_accounts")
				.select(
					"id, username, needs_reauth, token_expires_at, last_synced_at, group_id",
				)
				.eq("user_id", user.id)
				.eq("is_active", true),
		]);

		type Row = {
			id: string;
			username: string | null;
			needs_reauth: boolean | null;
			token_expires_at: string | null;
			last_synced_at: string | null;
			group_id: string | null;
		};

		const rows = [
			...((threadsRes.data || []) as Row[]).map((r) => ({ ...r, platform: "threads" as const })),
			...((igRes.data || []) as Row[]).map((r) => ({ ...r, platform: "instagram" as const })),
		];

		const now = Date.now();
		const classified = rows
			.map((r) => ({
				accountId: r.id,
				username: r.username,
				platform: r.platform,
				bucket: classify(r),
				reason: reasonFor(r),
				lastSyncedAt: r.last_synced_at,
				groupId: r.group_id,
				tokenDaysLeft: tokenDaysLeft(r.token_expires_at, now),
			}))
			.sort((a, b) => {
				const diff = BUCKET_RANK[a.bucket] - BUCKET_RANK[b.bucket];
				if (diff !== 0) return diff;
				return (a.username || "").localeCompare(b.username || "");
			});

		const tokenDayValues = classified
			.map((a) => a.tokenDaysLeft)
			.filter((v): v is number => v !== null);

		const summary = {
			total: classified.length,
			crit: classified.filter((a) => a.bucket === "crit").length,
			warn: classified.filter((a) => a.bucket === "warn").length,
			healthy: classified.filter((a) => a.bucket === "healthy").length,
			minTokenDaysLeft:
				tokenDayValues.length > 0 ? Math.min(...tokenDayValues) : null,
		};

		return apiSuccess(res, {
			accounts: classified.slice(0, limit),
			summary,
		});
	},
);
