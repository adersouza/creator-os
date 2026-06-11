/**
 * Instagram Auto-Responders API Route
 * POST /api/instagram/auto-responders?action=list|create|update|delete|toggle
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database } from "../../../../types/supabase.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logAudit, trackUsage } from "../../auditLog.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { requireMinTier } from "../../tierGate.js";
import { z, zEnum } from "../../zodCompat.js";
import { verifyIgAccountOwnership } from "../helpers/verifyOwnership.js";

type AutoResponderUpdate =
	Database["public"]["Tables"]["ig_auto_responders"]["Update"];
type UserDb = DbContext["userDb"];

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const ListSchema = z.object({
	accountId: z.string().min(1).optional(),
});

const CreateSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	name: z.string().min(1, "name is required"),
	triggerType: zEnum(["keyword", "first_message", "mention", "story_reply"]),
	triggerKeywords: z.array(z.string()).nullable().optional(),
	templateId: z.string().nullable().optional(),
	customResponse: z.string().nullable().optional(),
	delaySeconds: z.number().optional(),
	onlyNewConversations: z.boolean().optional(),
	maxResponsesPerUser: z.number().optional(),
	useAiResponse: z.boolean().optional(),
	aiResponseIntent: z.string().optional(),
	aiConversationDepth: z.number().optional(),
	aiSystemPrompt: z.string().nullable().optional(),
});

const UpdateSchema = z.object({
	responderId: z.string().min(1, "responderId is required"),
	name: z.string().optional(),
	triggerType: zEnum([
		"keyword",
		"first_message",
		"mention",
		"story_reply",
	]).optional(),
	triggerKeywords: z.array(z.string()).nullable().optional(),
	templateId: z.string().nullable().optional(),
	customResponse: z.string().nullable().optional(),
	delaySeconds: z.number().optional(),
	onlyNewConversations: z.boolean().optional(),
	maxResponsesPerUser: z.number().optional(),
	useAiResponse: z.boolean().optional(),
	aiResponseIntent: z.string().optional(),
	aiConversationDepth: z.number().optional(),
	aiSystemPrompt: z.string().nullable().optional(),
});

const DeleteSchema = z.object({
	responderId: z.string().min(1, "responderId is required"),
});

const ToggleSchema = z.object({
	responderId: z.string().min(1, "responderId is required"),
	isEnabled: z.boolean(),
});

async function handleList(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	const parsed = ListSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId } = parsed.data;

	let query = userDb
		.from("ig_auto_responders")
		.select(`
      *,
      template:ig_dm_templates(id, name, content)
    `)
		.eq("user_id", userId)
		.order("created_at", { ascending: false });

	if (accountId) {
		query = query.eq("ig_account_id", accountId);
	}

	const { data: responders, error } = await query;

	if (error) {
		logger.error("[IG Auto-Responders] Error fetching", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to fetch auto-responders");
	}

	return apiSuccess(res, { responders });
}

async function handleCreate(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	const parsed = CreateSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const {
		accountId,
		name,
		triggerType,
		triggerKeywords,
		templateId,
		customResponse,
		delaySeconds,
		onlyNewConversations,
		maxResponsesPerUser,
		useAiResponse,
		aiResponseIntent,
		aiConversationDepth,
		aiSystemPrompt,
	} = parsed.data;

	if (!useAiResponse && !templateId && !customResponse) {
		return apiError(
			res,
			400,
			"Either templateId, customResponse, or useAiResponse is required",
		);
	}

	// Verify account ownership
	const account = await verifyIgAccountOwnership(res, accountId, userId, "id", userDb);
	if (!account) return;

	const { data: responder, error } = await userDb
		.from("ig_auto_responders")
		.insert({
			user_id: userId,
			ig_account_id: accountId,
			name,
			trigger_type: triggerType,
			trigger_keywords: triggerKeywords || null,
			template_id: templateId || null,
			custom_response: customResponse || null,
			delay_seconds: delaySeconds || 0,
			only_new_conversations: onlyNewConversations !== false,
			max_responses_per_user: maxResponsesPerUser ?? 1,
			use_ai_response: useAiResponse || false,
			ai_response_intent: aiResponseIntent || "engage",
			ai_conversation_depth: aiConversationDepth || 5,
			ai_system_prompt: aiSystemPrompt || null,
		})
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[IG Auto-Responders] Error creating", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to create auto-responder");
	}

	return apiSuccess(res, { responder });
}

async function handleUpdate(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	const parsed = UpdateSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const {
		responderId,
		name,
		triggerType,
		triggerKeywords,
		templateId,
		customResponse,
		delaySeconds,
		onlyNewConversations,
		maxResponsesPerUser,
		useAiResponse,
		aiResponseIntent,
		aiConversationDepth,
		aiSystemPrompt,
	} = parsed.data;

	// Verify ownership
	const { data: existing } = await userDb
		.from("ig_auto_responders")
		.select("id")
		.eq("id", responderId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!existing) {
		return apiError(res, 404, "Auto-responder not found");
	}

	const updateData: AutoResponderUpdate = {
		updated_at: new Date().toISOString(),
	};
	if (name !== undefined) updateData.name = name;
	if (triggerType !== undefined) updateData.trigger_type = triggerType;
	if (triggerKeywords !== undefined)
		updateData.trigger_keywords = triggerKeywords;
	if (templateId !== undefined) updateData.template_id = templateId || null;
	if (customResponse !== undefined)
		updateData.custom_response = customResponse || null;
	if (delaySeconds !== undefined) updateData.delay_seconds = delaySeconds;
	if (onlyNewConversations !== undefined)
		updateData.only_new_conversations = onlyNewConversations;
	if (maxResponsesPerUser !== undefined)
		updateData.max_responses_per_user = maxResponsesPerUser;
	if (useAiResponse !== undefined) updateData.use_ai_response = useAiResponse;
	if (aiResponseIntent !== undefined)
		updateData.ai_response_intent = aiResponseIntent;
	if (aiConversationDepth !== undefined)
		updateData.ai_conversation_depth = aiConversationDepth;
	if (aiSystemPrompt !== undefined)
		updateData.ai_system_prompt = aiSystemPrompt;

	const { data: responder, error } = await userDb
		.from("ig_auto_responders")
		.update(updateData)
		.eq("id", responderId)
		.eq("user_id", userId)
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[IG Auto-Responders] Error updating", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to update auto-responder");
	}

	return apiSuccess(res, { responder });
}

async function handleDelete(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	const parsed = DeleteSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { responderId } = parsed.data;

	const { error } = await userDb
		.from("ig_auto_responders")
		.delete()
		.eq("id", responderId)
		.eq("user_id", userId);

	if (error) {
		logger.error("[IG Auto-Responders] Error deleting", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to delete auto-responder");
	}

	return apiSuccess(res);
}

async function handleToggle(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	const parsed = ToggleSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { responderId, isEnabled } = parsed.data;

	const { data: responder, error } = await userDb
		.from("ig_auto_responders")
		.update({
			is_enabled: isEnabled,
			updated_at: new Date().toISOString(),
		})
		.eq("id", responderId)
		.eq("user_id", userId)
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[IG Auto-Responders] Error toggling", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to toggle auto-responder");
	}

	return apiSuccess(res, { responder });
}

export default withAuthDb(async (req, res, context) => {
	const { user, userDb } = context;
	const userId = user.id;

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	// Tier gate: pro tier required
	const allowed = await requireMinTier(userId, "pro", res);
	if (!allowed) return;

	// Rate limit: 30 requests/60s per user
	const rl = await checkRateLimit({
		key: `ig-auto-responders:${userId}`,
		limit: 30,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Rate limit exceeded. Please wait a moment.");
	}

	const action = req.query.action as string;

	try {
		switch (action) {
			case "list":
				return handleList(req, res, userId, userDb);
			case "create":
				logAudit(userId, "auto-responder.create", { req });
				trackUsage(userId, "instagram.auto-responders.create");
				return handleCreate(req, res, userId, userDb);
			case "update":
				logAudit(userId, "auto-responder.update", { req });
				return handleUpdate(req, res, userId, userDb);
			case "delete":
				logAudit(userId, "auto-responder.delete", { req });
				return handleDelete(req, res, userId, userDb);
			case "toggle":
				return handleToggle(req, res, userId, userDb);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("[IG Auto-Responders] API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
