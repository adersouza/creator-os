/**
 * Trending Topics Config API
 *
 * GET  /api/trending-config?groupId=xxx  — Read config for an account group
 * POST /api/trending-config               — Upsert config for an account group
 *
 * Empire tier only.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database, Json } from "../../../../types/supabase.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { withAuthDb } from "../../middleware.js";
import { parseBodyOrError, parseQueryOrError } from "../../validation.js";
import { z, zUnknown } from "../../zodCompat.js";

type ApiUser = DbContext["user"];
type UserDb = DbContext["userDb"];
type TrendingTopicConfigInsert =
	Database["public"]["Tables"]["trending_topic_config"]["Insert"];

const GetConfigQuerySchema = z.object({
	groupId: z.string().min(1, "groupId is required"),
});

// ============================================================================
// Zod Schema for POST body
// ============================================================================

const UpsertConfigSchema = z.object({
	accountGroupId: z.string().min(1, "accountGroupId is required"),
	keywords: z.array(z.string()).max(20).optional(),
	scan_frequency_hours: z.number().int().min(2).max(12).optional(),
	daily_post_cap: z.number().int().min(1).max(10).optional(),
	blocklist: z.array(z.string()).max(100).optional(),
	enabled: z.boolean().optional(),
	content_preferences: zUnknown().optional(),
});

// ============================================================================
// Handler
// ============================================================================

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context) => {
		const { user, userDb } = context;
		try {
			if (req.method === "GET") {
				return await handleGet(req, res, user, userDb);
			}
			if (req.method === "POST") {
				return await handlePost(req, res, user, userDb);
			}
			return apiError(res, 405, "Method not allowed");
		} catch (err) {
			return apiError(
				res,
				500,
				err instanceof Error ? err.message : "Internal error",
			);
		}
	},
);

// ============================================================================
// GET — Read config by groupId
// ============================================================================

async function handleGet(
	req: VercelRequest,
	res: VercelResponse,
	user: ApiUser,
	userDb: UserDb,
) {
	const parsed = parseQueryOrError(res, GetConfigQuerySchema, req.query);
	if (!parsed) return;
	const { groupId } = parsed;

	// Empire tier gate
	const { requireMinTier } = await import("../../tierGate.js");
	const allowed = await requireMinTier(user.id, "empire", res);
	if (!allowed) return;

	const { data, error } = await userDb
		.from("trending_topic_config")
		.select("*")
		.eq("account_group_id", groupId)
		.eq("user_id", user.id)
		.maybeSingle();

	if (error) {
		return apiError(res, 500, "Failed to fetch trending config", {
			details: error?.message,
		});
	}

	return apiSuccess(res, { data });
}

// ============================================================================
// POST — Upsert config
// ============================================================================

async function handlePost(
	req: VercelRequest,
	res: VercelResponse,
	user: ApiUser,
	userDb: UserDb,
) {
	const parsed = parseBodyOrError(res, UpsertConfigSchema, req.body);
	if (!parsed) return;

	const { accountGroupId, ...fields } = parsed;

	// Empire tier gate
	const { requireMinTier } = await import("../../tierGate.js");
	const allowed = await requireMinTier(user.id, "empire", res);
	if (!allowed) return;

	const { data: accountGroup } = await userDb
		.from("account_groups")
		.select("id")
		.eq("id", accountGroupId)
		.eq("user_id", user.id)
		.maybeSingle();

	if (!accountGroup) {
		return apiError(res, 404, "Account group not found");
	}

	const upsertPayload: TrendingTopicConfigInsert = {
		account_group_id: accountGroupId,
		user_id: user.id,
		updated_at: new Date().toISOString(),
	};

	// Only include fields that were explicitly provided
	if (fields.keywords !== undefined) upsertPayload.keywords = fields.keywords;
	if (fields.scan_frequency_hours !== undefined)
		upsertPayload.scan_frequency_hours = fields.scan_frequency_hours;
	if (fields.daily_post_cap !== undefined)
		upsertPayload.daily_post_cap = fields.daily_post_cap;
	if (fields.blocklist !== undefined)
		upsertPayload.blocklist = fields.blocklist;
	if (fields.enabled !== undefined) upsertPayload.enabled = fields.enabled;
	if (fields.content_preferences !== undefined)
		upsertPayload.content_preferences = fields.content_preferences as Json;

	const { data, error } = await userDb
		.from("trending_topic_config")
		.upsert(upsertPayload, { onConflict: "account_group_id" })
		.select("*")
		.maybeSingle();

	if (error) {
		return apiError(res, 500, "Failed to upsert trending config", {
			details: error.message,
		});
	}

	return apiSuccess(res, { data });
}
