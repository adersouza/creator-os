import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	badRequest,
	methodNotAllowed,
} from "../../apiResponse.js";
import { checkAIRateLimit } from "../../aiRateLimit.js";
import { withAuth } from "../../middleware.js";
import { getSupabaseAny } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";

const VALID_STATUSES = new Set(["accepted", "rejected"]);

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		const db = getSupabaseAny();

		if (req.method === "GET") {
			const rawKeys =
				typeof req.query.conversation_keys === "string"
					? req.query.conversation_keys
					: typeof req.query.conversation_key === "string"
						? req.query.conversation_key
						: "";
			const conversationKeys = rawKeys
				.split(",")
				.map((key) => key.trim())
				.filter(Boolean)
				.slice(0, 100);
			if (conversationKeys.length === 0) {
				return badRequest(res, "conversation_key is required");
			}

			const { data, error } = await db
				.from("inbox_ai_suggestions")
				.select("id,conversation_key,suggestion_text,reasoning,alternatives,status,created_at")
				.eq("user_id", user.id)
				.in("conversation_key", conversationKeys)
				.order("created_at", { ascending: false });

			if (error) {
				return apiError(res, 500, "Failed to fetch inbox suggestions", {
					details: error.message,
				});
			}

			return apiSuccess(res, { suggestions: data ?? [] });
		}

		if (req.method === "POST") {
			const { id, conversation_key, conversation_keys, status, regenerate } = req.body || {};

			if (
				Array.isArray(conversation_keys) &&
				!id &&
				!status &&
				!regenerate
			) {
				const conversationKeys = conversation_keys
					.filter((key: unknown): key is string => typeof key === "string")
					.map((key) => key.trim())
					.filter(Boolean)
					.slice(0, 100);
				if (conversationKeys.length === 0) {
					return badRequest(res, "conversation_key is required");
				}

				const { data, error } = await db
					.from("inbox_ai_suggestions")
					.select("id,conversation_key,suggestion_text,reasoning,alternatives,status,created_at")
					.eq("user_id", user.id)
					.in("conversation_key", conversationKeys)
					.order("created_at", { ascending: false });

				if (error) {
					return apiError(res, 500, "Failed to fetch inbox suggestions", {
						details: error.message,
					});
				}

				return apiSuccess(res, { suggestions: data ?? [] });
			}

			if (!conversation_key || typeof conversation_key !== "string") {
				return badRequest(res, "conversation_key is required");
			}

			if (regenerate) {
				if (!(await requireMinTier(user.id, "pro", res))) return;
				const rateLimit = await checkAIRateLimit(user.id, "inbox-suggestions");
				if (!rateLimit.allowed) {
					return apiError(res, 429, "AI rate limit exceeded. Try again shortly.");
				}
				const { regenerateInboxSuggestion } = await import(
					"../../cron/inbox-suggestions.js"
				);
				const suggestion = await regenerateInboxSuggestion(
					db,
					user.id,
					conversation_key,
				);
				return apiSuccess(res, { suggestion });
			}

			if (!id || typeof id !== "string") return badRequest(res, "id is required");
			if (!status || typeof status !== "string" || !VALID_STATUSES.has(status)) {
				return badRequest(res, "status must be accepted or rejected");
			}

			const { data, error } = await db
				.from("inbox_ai_suggestions")
				.update({ status })
				.eq("id", id)
				.eq("user_id", user.id)
				.eq("conversation_key", conversation_key)
				.select("id,conversation_key,suggestion_text,reasoning,alternatives,status,created_at")
				.maybeSingle();

			if (error) {
				return apiError(res, 500, "Failed to update inbox suggestion", {
					details: error.message,
				});
			}
			return apiSuccess(res, { suggestion: data });
		}

		return methodNotAllowed(res);
	},
);
