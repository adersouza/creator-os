/**
 * API Key Management — CRUD for developer API keys
 *
 * GET    /api/developer/keys          — list keys (prefix + metadata)
 * POST   /api/developer/keys          — create key (returns full key ONCE)
 * DELETE /api/developer/keys?id=X     — revoke key
 * PUT    /api/developer/keys?id=X     — update name/scopes/active
 */

import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database } from "../../../../types/supabase.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { requireStepUp, withAuthDb } from "../../middleware.js";
import { getRedis } from "../../redis.js";
import { requireMinTier } from "../../tierGate.js";
import { z, zEnum } from "../../zodCompat.js";

const CreateKeySchema = z.object({
	name: z.string().min(1).max(100),
	scopes: z
		.array(zEnum(["read", "write", "admin", "mcp"]))
		.min(1)
		.default(["read"]),
	allowed_account_ids: z.array(z.string().min(1).max(100)).max(500).optional().nullable(),
	expires_at: z.string().optional().nullable(),
});

const UpdateKeySchema = z.object({
	name: z.string().min(1).max(100).optional(),
	scopes: z
		.array(zEnum(["read", "write", "admin", "mcp"]))
		.min(1)
		.optional(),
	allowed_account_ids: z.array(z.string().min(1).max(100)).max(500).optional().nullable(),
	is_active: z.boolean().optional(),
});

type ApiKeyUpdate = Database["public"]["Tables"]["api_keys"]["Update"] & {
	allowed_account_ids?: string[] | null;
};

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context) => {
		const { user, userDb } = context;
		const allowed = await requireMinTier(user.id, "pro", res);
		if (!allowed) return;

		// Minting / revoking / mutating API keys is equivalent to handing out
		// bearer tokens. Require a fresh TOTP on mutations if MFA is enrolled.
		if (req.method !== "GET") {
			const stepUp = await requireStepUp(req, res, user.id);
			if (stepUp) return stepUp;
		}

		if (req.method === "GET") {
			const { data, error } = await userDb
				.from("api_keys")
				.select(
					"id, name, key_prefix, scopes, allowed_account_ids, is_active, last_used_at, expires_at, created_at",
				)
				.eq("user_id", user.id)
				.order("created_at", { ascending: false });

			if (error) return apiError(res, 500, "Failed to load API keys");
			return apiSuccess(res, { keys: data || [] });
		}

		if (req.method === "POST") {
			const parsed = CreateKeySchema.safeParse(req.body);
			if (!parsed.success)
				return apiError(
					res,
					400,
					parsed.error.issues[0]?.message || "Invalid input",
				);

			// Limit to 10 keys per user
			const { count } = await userDb
				.from("api_keys")
				.select("id", { count: "exact", head: true })
				.eq("user_id", user.id);

			if ((count || 0) >= 10)
				return apiError(res, 400, "Maximum 10 API keys per user");

			// Generate key
			const rawKey = `juno_ak_${crypto.randomBytes(32).toString("hex")}`;
			const keyHash = crypto.createHash("sha256").update(rawKey).digest("hex");
			const keyPrefix = rawKey.substring(0, 16);

			const { data, error } = await userDb
				.from("api_keys")
				.insert({
					user_id: user.id,
					name: parsed.data.name,
					key_hash: keyHash,
					key_prefix: keyPrefix,
					scopes: parsed.data.scopes,
					allowed_account_ids: normalizeAllowedAccountIds(parsed.data.allowed_account_ids),
					expires_at: parsed.data.expires_at || null,
				})
				.select("id, name, key_prefix, scopes, allowed_account_ids, is_active, created_at")
				.maybeSingle();

			if (error) return apiError(res, 500, "Failed to create API key");

			// #596: Audit log key creation
			logger.info("[api-keys] Key created", {
				userId: user.id,
				keyId: data?.id,
				name: parsed.data.name,
			});

			// Return the full key ONCE — it's never stored in plaintext
			return apiSuccess(res, { key: data, rawKey });
		}

		if (req.method === "PUT") {
			const id = req.query.id as string;
			if (!id) return apiError(res, 400, "id required");

			const parsed = UpdateKeySchema.safeParse(req.body);
			if (!parsed.success)
				return apiError(
					res,
					400,
					parsed.error.issues[0]?.message || "Invalid input",
				);

			const updateData: ApiKeyUpdate = {};
			if (parsed.data.name !== undefined) updateData.name = parsed.data.name;
			if (parsed.data.scopes !== undefined) {
				updateData.scopes = parsed.data.scopes;
			}
			if (parsed.data.allowed_account_ids !== undefined) {
				updateData.allowed_account_ids = normalizeAllowedAccountIds(parsed.data.allowed_account_ids);
			}
			if (parsed.data.is_active !== undefined) {
				updateData.is_active = parsed.data.is_active;
			}

			const { data, error } = await userDb
				.from("api_keys")
				.update(updateData)
				.eq("id", id)
				.eq("user_id", user.id)
				.select()
				.maybeSingle();

			if (error) return apiError(res, 500, "Failed to update API key");
			if (!data) return apiError(res, 404, "API key not found");

			// #596: Audit log key update
			logger.info("[api-keys] Key updated", {
				userId: user.id,
				keyId: id,
				changes: Object.keys(parsed.data),
			});

			// #595: Invalidate Redis cache when key is deactivated
			if (
				(parsed.data.is_active === false ||
					parsed.data.scopes !== undefined ||
					parsed.data.allowed_account_ids !== undefined) &&
				data?.key_hash
			) {
				try {
					await getRedis().del(`apikey:${data.key_hash}`);
				} catch (e) {
					logger.warn("Failed to invalidate API key cache", {
						id,
						error: String(e),
					});
				}
			}

			return apiSuccess(res, { key: data });
		}

		if (req.method === "DELETE") {
			const id = req.query.id as string;
			if (!id) return apiError(res, 400, "id required");

			// #595: Get key_hash before deleting to invalidate Redis cache
			const { data: keyToDelete } = await userDb
				.from("api_keys")
				.select("key_hash")
				.eq("id", id)
				.eq("user_id", user.id)
				.maybeSingle();

			const { error, count } = await userDb
				.from("api_keys")
				.delete({ count: "exact" })
				.eq("id", id)
				.eq("user_id", user.id);

			if (error) return apiError(res, 500, "Failed to delete API key");
			if (!count) return apiError(res, 404, "API key not found");

			// #596: Audit log key deletion
			logger.info("[api-keys] Key deleted", { userId: user.id, keyId: id });

			// Invalidate Redis cache
			if (keyToDelete?.key_hash) {
				try {
					await getRedis().del(`apikey:${keyToDelete.key_hash}`);
				} catch (e) {
					logger.warn("Failed to invalidate API key cache", {
						id,
						error: String(e),
					});
				}
			}

			return apiSuccess(res, { deleted: true });
		}

		return apiError(res, 405, "Method not allowed");
	},
);

function normalizeAllowedAccountIds(value: string[] | null | undefined): string[] | null {
	if (!value) return null;
	const ids = [...new Set(value.map((item) => item.trim()).filter(Boolean))];
	return ids.length ? ids : null;
}
