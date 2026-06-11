/**
 * Instagram DM Templates API Route
 * POST /api/instagram/dm-templates?action=list|create|update|delete|increment-use
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database } from "../../../../types/supabase.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logAudit } from "../../auditLog.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { requireMinTier } from "../../tierGate.js";
import { z } from "../../zodCompat.js";

type DMTemplateUpdate = Database["public"]["Tables"]["ig_dm_templates"]["Update"];
type AdminDb = DbContext["adminDb"];
type UserDb = DbContext["userDb"];

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const ListSchema = z.object({
	category: z.string().optional(),
});

const CreateSchema = z.object({
	name: z.string().min(1, "name is required"),
	content: z.string().min(1, "content is required"),
	category: z.string().optional(),
	shortcut: z.string().nullable().optional(),
});

const UpdateSchema = z.object({
	templateId: z.string().min(1, "templateId is required"),
	name: z.string().optional(),
	content: z.string().optional(),
	category: z.string().optional(),
	shortcut: z.string().nullable().optional(),
});

const DeleteSchema = z.object({
	templateId: z.string().min(1, "templateId is required"),
});

const IncrementUseSchema = z.object({
	templateId: z.string().min(1, "templateId is required"),
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
	const { category } = parsed.data;

	let query = userDb
		.from("ig_dm_templates")
		.select("*")
		.eq("user_id", userId)
		.order("use_count", { ascending: false });

	if (category) {
		query = query.eq("category", category);
	}

	const { data: templates, error } = await query;

	if (error) {
		logger.error("[IG DM Templates] Error fetching", { error: String(error) });
		return apiError(res, 500, "Failed to fetch templates");
	}

	return apiSuccess(res, { templates });
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
	const { name, content, category, shortcut } = parsed.data;

	// Check for duplicate shortcut
	if (shortcut) {
		const { data: existing } = await userDb
			.from("ig_dm_templates")
			.select("id")
			.eq("user_id", userId)
			.eq("shortcut", shortcut)
			.maybeSingle();

		if (existing) {
			return apiError(res, 400, "Shortcut already in use");
		}
	}

	const { data: template, error } = await userDb
		.from("ig_dm_templates")
		.insert({
			user_id: userId,
			name,
			content,
			category: category || "general",
			shortcut: shortcut || null,
		})
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[IG DM Templates] Error creating", { error: String(error) });
		return apiError(res, 500, "Failed to create template");
	}

	return apiSuccess(res, { template });
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
	const { templateId, name, content, category, shortcut } = parsed.data;

	// Verify ownership
	const { data: existing } = await userDb
		.from("ig_dm_templates")
		.select("id")
		.eq("id", templateId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!existing) {
		return apiError(res, 404, "Template not found");
	}

	// Check for duplicate shortcut (excluding current template)
	if (shortcut) {
		const { data: duplicateShortcut } = await userDb
			.from("ig_dm_templates")
			.select("id")
			.eq("user_id", userId)
			.eq("shortcut", shortcut)
			.neq("id", templateId)
			.maybeSingle();

		if (duplicateShortcut) {
			return apiError(res, 400, "Shortcut already in use");
		}
	}

	const updateData: DMTemplateUpdate = {
		updated_at: new Date().toISOString(),
	};
	if (name !== undefined) updateData.name = name;
	if (content !== undefined) updateData.content = content;
	if (category !== undefined) updateData.category = category;
	if (shortcut !== undefined) updateData.shortcut = shortcut || null;

	const { data: template, error } = await userDb
		.from("ig_dm_templates")
		.update(updateData)
		.eq("id", templateId)
		.eq("user_id", userId)
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[IG DM Templates] Error updating", { error: String(error) });
		return apiError(res, 500, "Failed to update template");
	}

	return apiSuccess(res, { template });
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
	const { templateId } = parsed.data;

	const { error } = await userDb
		.from("ig_dm_templates")
		.delete()
		.eq("id", templateId)
		.eq("user_id", userId);

	if (error) {
		logger.error("[IG DM Templates] Error deleting", { error: String(error) });
		return apiError(res, 500, "Failed to delete template");
	}

	return apiSuccess(res);
}

async function handleIncrementUse(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	adminDb: AdminDb,
) {
	const parsed = IncrementUseSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { templateId } = parsed.data;

	const { error } = await adminDb.rpc("increment_dm_template_use", {
		p_template_id: templateId,
		p_user_id: userId,
	});

	if (error) {
		logger.error("[IG DM Templates] Failed to increment use count", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to increment template use count");
	}

	return apiSuccess(res);
}

export default withAuthDb(async (req, res, context) => {
	const { adminDb, user, userDb } = context;
	const userId = user.id;

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	// Tier gate: pro tier required — return structured upgrade prompt for free-tier users
	const { getUserTier } = await import("../../tierGate.js");
	const userTier = await getUserTier(userId);
	if (userTier === "free") {
		return apiError(res, 403, "DM templates require a Pro subscription", {
			code: "upgrade_required",
			details: `currentTier=${userTier}, requiredTier=pro`,
		});
	}
	const allowed = await requireMinTier(userId, "pro", res);
	if (!allowed) return;

	// Rate limit: 30 requests/60s per user
	const rl = await checkRateLimit({
		key: `ig-dm-templates:${userId}`,
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
				logAudit(userId, "dm-template.create", { req });
				return handleCreate(req, res, userId, userDb);
			case "update":
				logAudit(userId, "dm-template.update", { req });
				return handleUpdate(req, res, userId, userDb);
			case "delete":
				logAudit(userId, "dm-template.delete", { req });
				return handleDelete(req, res, userId, userDb);
			case "increment-use":
				return handleIncrementUse(req, res, userId, adminDb);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("[IG DM Templates] API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
