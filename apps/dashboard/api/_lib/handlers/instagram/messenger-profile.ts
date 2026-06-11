/**
 * Instagram Messenger Profile API Route
 * POST /api/instagram/messenger-profile?action=
 *   persistent-menu-set|persistent-menu-get|persistent-menu-delete
 *   ice-breakers-set|ice-breakers-get|ice-breakers-delete
 *   welcome-flows-create|welcome-flows-list|welcome-flows-delete
 */

import { apiError, apiSuccess, handleIgAuthError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";
import { z } from "../../zodCompat.js";

// ============================================================================
// Helper: get account with token
// ============================================================================

async function getAccount(accountId: string, userId: string) {
	const { data, error } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		data: {
			instagram_access_token_encrypted: string;
			instagram_user_id: string;
			login_type: string;
		} | null;
		error: { message: string } | null;
	};

	if (error || !data?.instagram_access_token_encrypted) return null;
	return data;
}

// ============================================================================
// Schemas
// ============================================================================

const AccountIdSchema = z.object({ accountId: z.string().min(1) });

const PersistentMenuSetSchema = z.object({
	accountId: z.string().min(1),
	menu: z
		.array(
			z.object({
				locale: z.string().default("default"),
				composer_input_disabled: z.boolean().default(false),
				call_to_actions: z
					.array(
						z.object({
							type: z.string(),
							title: z.string().min(1),
							url: z.string().url().optional(),
							payload: z.string().optional(),
							webview_height_ratio: z.string().optional(),
						}),
					)
					.min(1),
			}),
		)
		.min(1),
});

const IceBreakersSetSchema = z.object({
	accountId: z.string().min(1),
	iceBreakers: z
		.array(
			z.object({
				locale: z.string().optional(),
				call_to_actions: z
					.array(
						z.object({
							question: z.string().min(1),
							payload: z.string().min(1),
						}),
					)
					.min(1)
					.max(4),
			}),
		)
		.min(1),
});

const WelcomeFlowCreateSchema = z.object({
	accountId: z.string().min(1),
	name: z.string().min(1),
	welcomeText: z.string().min(1),
	quickReplies: z
		.array(
			z.object({
				content_type: z.string(),
				title: z.string().min(1),
				payload: z.string().min(1),
			}),
		)
		.min(1),
});

const WelcomeFlowDeleteSchema = z.object({
	accountId: z.string().min(1),
	flowId: z.string().min(1),
});

// ============================================================================
// Handlers
// ============================================================================

export default withAuth(async (req, res, user) => {
	const userId = user.id;

	// Tier gate: pro tier required for Messenger profile features
	if (!(await requireMinTier(userId, "pro", res))) return;

	const action = req.query.action as string;

	try {
		switch (action) {
			// ---- Persistent Menu ----
			case "persistent-menu-set": {
				if (req.method !== "POST")
					return apiError(res, 405, "Method not allowed");
				const parsed = PersistentMenuSetSchema.safeParse(req.body);
				if (!parsed.success)
					return apiError(
						res,
						400,
						parsed.error.issues[0]?.message || "Invalid input",
					);
				const account = await getAccount(parsed.data.accountId, userId);
				if (!account) return apiError(res, 404, "Account not found");
				const { setPersistentMenu } = await import("../../instagramApi.js");
				const result = await setPersistentMenu(
					account.instagram_access_token_encrypted,
					account.instagram_user_id,
					parsed.data.menu,
					account.login_type || "instagram",
				);
				if (!result.success)
					return await handleIgAuthError(
						res,
						parsed.data.accountId,
						userId,
						result.error || "Failed",
					);
				return apiSuccess(res, { success: true });
			}

			case "persistent-menu-get": {
				const parsed = AccountIdSchema.safeParse(
					req.method === "GET" ? req.query : req.body,
				);
				if (!parsed.success) return apiError(res, 400, "accountId required");
				const account = await getAccount(parsed.data.accountId, userId);
				if (!account) return apiError(res, 404, "Account not found");
				const { getPersistentMenu } = await import("../../instagramApi.js");
				const result = await getPersistentMenu(
					account.instagram_access_token_encrypted,
					account.instagram_user_id,
					account.login_type || "instagram",
				);
				if (!result.success)
					return await handleIgAuthError(
						res,
						parsed.data.accountId,
						userId,
						result.error || "Failed",
					);
				return apiSuccess(res, { menu: result.menu });
			}

			case "persistent-menu-delete": {
				if (req.method !== "POST" && req.method !== "DELETE")
					return apiError(res, 405, "Method not allowed");
				const parsed = AccountIdSchema.safeParse(req.body || req.query);
				if (!parsed.success) return apiError(res, 400, "accountId required");
				const account = await getAccount(parsed.data.accountId, userId);
				if (!account) return apiError(res, 404, "Account not found");
				const { deletePersistentMenu } = await import("../../instagramApi.js");
				const result = await deletePersistentMenu(
					account.instagram_access_token_encrypted,
					account.instagram_user_id,
					account.login_type || "instagram",
				);
				if (!result.success)
					return await handleIgAuthError(
						res,
						parsed.data.accountId,
						userId,
						result.error || "Failed",
					);
				return apiSuccess(res, { success: true });
			}

			// ---- Ice Breakers ----
			case "ice-breakers-set": {
				if (req.method !== "POST")
					return apiError(res, 405, "Method not allowed");
				const parsed = IceBreakersSetSchema.safeParse(req.body);
				if (!parsed.success)
					return apiError(
						res,
						400,
						parsed.error.issues[0]?.message || "Invalid input",
					);
				const account = await getAccount(parsed.data.accountId, userId);
				if (!account) return apiError(res, 404, "Account not found");
				const { setIceBreakers } = await import("../../instagramApi.js");
				const result = await setIceBreakers(
					account.instagram_access_token_encrypted,
					account.instagram_user_id,
					parsed.data.iceBreakers,
					account.login_type || "instagram",
				);
				if (!result.success)
					return await handleIgAuthError(
						res,
						parsed.data.accountId,
						userId,
						result.error || "Failed",
					);
				return apiSuccess(res, { success: true });
			}

			case "ice-breakers-get": {
				const parsed = AccountIdSchema.safeParse(
					req.method === "GET" ? req.query : req.body,
				);
				if (!parsed.success) return apiError(res, 400, "accountId required");
				const account = await getAccount(parsed.data.accountId, userId);
				if (!account) return apiError(res, 404, "Account not found");
				const { getIceBreakers } = await import("../../instagramApi.js");
				const result = await getIceBreakers(
					account.instagram_access_token_encrypted,
					account.instagram_user_id,
					account.login_type || "instagram",
				);
				if (!result.success)
					return await handleIgAuthError(
						res,
						parsed.data.accountId,
						userId,
						result.error || "Failed",
					);
				return apiSuccess(res, { iceBreakers: result.iceBreakers });
			}

			case "ice-breakers-delete": {
				if (req.method !== "POST" && req.method !== "DELETE")
					return apiError(res, 405, "Method not allowed");
				const parsed = AccountIdSchema.safeParse(req.body || req.query);
				if (!parsed.success) return apiError(res, 400, "accountId required");
				const account = await getAccount(parsed.data.accountId, userId);
				if (!account) return apiError(res, 404, "Account not found");
				const { deleteIceBreakers } = await import("../../instagramApi.js");
				const result = await deleteIceBreakers(
					account.instagram_access_token_encrypted,
					account.instagram_user_id,
					account.login_type || "instagram",
				);
				if (!result.success)
					return await handleIgAuthError(
						res,
						parsed.data.accountId,
						userId,
						result.error || "Failed",
					);
				return apiSuccess(res, { success: true });
			}

			// ---- Welcome Message Flows ----
			case "welcome-flows-create": {
				if (req.method !== "POST")
					return apiError(res, 405, "Method not allowed");
				const parsed = WelcomeFlowCreateSchema.safeParse(req.body);
				if (!parsed.success)
					return apiError(
						res,
						400,
						parsed.error.issues[0]?.message || "Invalid input",
					);
				const account = await getAccount(parsed.data.accountId, userId);
				if (!account) return apiError(res, 404, "Account not found");
				const { createWelcomeMessageFlow } = await import(
					"../../instagramApi.js"
				);
				const result = await createWelcomeMessageFlow(
					account.instagram_access_token_encrypted,
					account.instagram_user_id,
					parsed.data.name,
					parsed.data.welcomeText,
					parsed.data.quickReplies,
					account.login_type || "instagram",
				);
				if (!result.success)
					return await handleIgAuthError(
						res,
						parsed.data.accountId,
						userId,
						result.error || "Failed",
					);
				return apiSuccess(res, { flowId: result.flowId });
			}

			case "welcome-flows-list": {
				const parsed = AccountIdSchema.safeParse(
					req.method === "GET" ? req.query : req.body,
				);
				if (!parsed.success) return apiError(res, 400, "accountId required");
				const account = await getAccount(parsed.data.accountId, userId);
				if (!account) return apiError(res, 404, "Account not found");
				const { getWelcomeMessageFlows } = await import(
					"../../instagramApi.js"
				);
				const result = await getWelcomeMessageFlows(
					account.instagram_access_token_encrypted,
					account.instagram_user_id,
					account.login_type || "instagram",
				);
				if (!result.success)
					return await handleIgAuthError(
						res,
						parsed.data.accountId,
						userId,
						result.error || "Failed",
					);
				return apiSuccess(res, { flows: result.flows });
			}

			case "welcome-flows-delete": {
				if (req.method !== "POST" && req.method !== "DELETE")
					return apiError(res, 405, "Method not allowed");
				const parsed = WelcomeFlowDeleteSchema.safeParse(req.body || req.query);
				if (!parsed.success)
					return apiError(res, 400, "accountId and flowId required");
				const account = await getAccount(parsed.data.accountId, userId);
				if (!account) return apiError(res, 404, "Account not found");
				const { deleteWelcomeMessageFlow } = await import(
					"../../instagramApi.js"
				);
				const result = await deleteWelcomeMessageFlow(
					account.instagram_access_token_encrypted,
					account.instagram_user_id,
					parsed.data.flowId,
					account.login_type || "instagram",
				);
				if (!result.success)
					return await handleIgAuthError(
						res,
						parsed.data.accountId,
						userId,
						result.error || "Failed",
					);
				return apiSuccess(res, { success: true });
			}

			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Instagram messenger-profile API error", {
			error: String(error),
		});
		return apiError(res, 500, "Internal server error");
	}
});
