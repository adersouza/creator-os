// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Post Templates CRUD API Route
 * POST /api/post-templates?action=list|create|update|delete|apply|increment-use
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database, Json } from "../../../../types/supabase.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logAudit } from "../../auditLog.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getUserTier } from "../../tierGate.js";
import { z, zRecord, zString, zUnknown } from "../../zodCompat.js";

type PostTemplateUpdate = Database["public"]["Tables"]["post_templates"]["Update"];
type UserDb = DbContext["userDb"];

// ---------------------------------------------------------------------------
// Tier Limits
// ---------------------------------------------------------------------------

const TEMPLATE_LIMITS: Record<string, number> = {
	free: 5,
	pro: 50,
	agency: 200,
	empire: Infinity,
};

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const ListSchema = z.object({
	category: z.string().optional(),
	platform: z.string().optional(),
});

const CreateSchema = z.object({
	name: z.string().min(1, "name is required"),
	text_template: z.string().min(1, "text_template is required"),
	category: z.string().optional(),
	platform: z.string().optional(),
	hashtags: z.array(z.string()).optional(),
	poll_options: zRecord(zString(), zUnknown()).nullable().optional(),
});

const UpdateSchema = z.object({
	templateId: z.string().min(1, "templateId is required"),
	name: z.string().optional(),
	text_template: z.string().optional(),
	category: z.string().optional(),
	platform: z.string().optional(),
	hashtags: z.array(z.string()).optional(),
	poll_options: zRecord(zString(), zUnknown()).nullable().optional(),
	is_shared: z.boolean().optional(),
});

const DeleteSchema = z.object({
	templateId: z.string().min(1, "templateId is required"),
});

const ApplySchema = z.object({
	templateId: z.string().min(1, "templateId is required"),
	variables: z
		.object({
			accountName: z.string().optional(),
			groupName: z.string().optional(),
		})
		.optional(),
});

const IncrementUseSchema = z.object({
	templateId: z.string().min(1, "templateId is required"),
});

// ---------------------------------------------------------------------------
// Template Variable Helpers
// ---------------------------------------------------------------------------

const DAYS = [
	"Sunday",
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
];
const MONTHS = [
	"Jan",
	"Feb",
	"Mar",
	"Apr",
	"May",
	"Jun",
	"Jul",
	"Aug",
	"Sep",
	"Oct",
	"Nov",
	"Dec",
];
const EMOJIS = ["🔥", "✨", "💡", "🎯", "🚀", "💪", "👀", "🎉"];

function buildTemplateVariables(
	extra?: { accountName?: string | undefined; groupName?: string | undefined } | null,
): Record<string, string> {
	const now = new Date();
	const hours = now.getHours();
	const minutes = now.getMinutes();
	const ampm = hours >= 12 ? "PM" : "AM";
	const h12 = hours % 12 || 12;
	const mm = minutes.toString().padStart(2, "0");

	const vars: Record<string, string> = {
		"{{date}}": `${MONTHS[now.getMonth()]} ${now.getDate()}`,
		"{{day}}": DAYS[now.getDay()]!,
		"{{time}}": `${h12}:${mm} ${ampm}`,
		"{{random_emoji}}": EMOJIS[Math.floor(Math.random() * EMOJIS.length)]!,
	};

	if (extra?.accountName) {
		vars["{{accountName}}"] = extra.accountName;
	}
	if (extra?.groupName) {
		vars["{{groupName}}"] = extra.groupName;
	}

	return vars;
}

function applyVariables(
	template: string,
	vars: Record<string, string>,
): string {
	let result = template;
	for (const [key, value] of Object.entries(vars)) {
		result = result.split(key).join(value);
	}
	return result;
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

async function handleList(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	const parsed = ListSchema.safeParse(req.body || {});
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { category, platform } = parsed.data;

	let query = userDb
		.from("post_templates")
		.select("*")
		.eq("user_id", userId)
		.order("times_used", { ascending: false });

	if (category) {
		query = query.eq("category", category);
	}
	if (platform) {
		query = query.eq("platform", platform);
	}

	const { data: templates, error } = await query;

	if (error) {
		logger.error("[Post Templates] Error fetching", { error: String(error) });
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
	const { name, text_template, category, platform, hashtags, poll_options } =
		parsed.data;

	// Enforce tier-based template limits
	const userTier = await getUserTier(userId);
	const limit = TEMPLATE_LIMITS[userTier] ?? TEMPLATE_LIMITS.free;

	if (limit !== Infinity) {
		const { count, error: countError } = await userDb
			.from("post_templates")
			.select("id", { count: "exact", head: true })
			.eq("user_id", userId);

		if (countError) {
			logger.error("[Post Templates] Error counting", {
				error: String(countError),
			});
			return apiError(res, 500, "Failed to check template count");
		}

		if ((count ?? 0) >= limit!) {
			return apiError(
				res,
				403,
				`Template limit reached (${limit} for ${userTier} tier). Upgrade to create more.`,
				{ code: "TEMPLATE_LIMIT_REACHED" },
			);
		}
	}

	const { data: template, error } = await userDb
		.from("post_templates")
		.insert({
			user_id: userId,
			name,
			text_template,
			category: category || "general",
			platform: platform || "threads",
			hashtags: hashtags || [],
			poll_options: (poll_options || null) as Json | null,
		})
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[Post Templates] Error creating", { error: String(error) });
		return apiError(res, 500, "Failed to create template");
	}

	return apiSuccess(res, { template }, 201);
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
		templateId,
		name,
		text_template,
		category,
		platform,
		hashtags,
		poll_options,
		is_shared,
	} = parsed.data;

	// Verify ownership
	const { data: existing } = await userDb
		.from("post_templates")
		.select("id")
		.eq("id", templateId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!existing) {
		return apiError(res, 404, "Template not found");
	}

	const updateData: PostTemplateUpdate = {};
	if (name !== undefined) updateData.name = name;
	if (text_template !== undefined) updateData.text_template = text_template;
	if (category !== undefined) updateData.category = category;
	if (platform !== undefined) updateData.platform = platform;
	if (hashtags !== undefined) updateData.hashtags = hashtags;
	if (poll_options !== undefined)
		updateData.poll_options = (poll_options || null) as Json | null;
	if (is_shared !== undefined) updateData.is_shared = is_shared;

	// #IDOR-fix: include user_id filter to prevent cross-user template update
	const { data: template, error } = await userDb
		.from("post_templates")
		.update(updateData)
		.eq("id", templateId)
		.eq("user_id", userId)
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[Post Templates] Error updating", { error: String(error) });
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

	// Verify ownership via user_id filter
	const { error } = await userDb
		.from("post_templates")
		.delete()
		.eq("id", templateId)
		.eq("user_id", userId);

	if (error) {
		logger.error("[Post Templates] Error deleting", { error: String(error) });
		return apiError(res, 500, "Failed to delete template");
	}

	return apiSuccess(res);
}

async function handleApply(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	const parsed = ApplySchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { templateId, variables } = parsed.data;

	// Fetch template (verify ownership)
	const { data: template, error } = await userDb
		.from("post_templates")
		.select("*")
		.eq("id", templateId)
		.eq("user_id", userId)
		.maybeSingle();

	if (error) {
		logger.error("[Post Templates] Error fetching for apply", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to fetch template");
	}
	if (!template) {
		return apiError(res, 404, "Template not found");
	}

	const vars = buildTemplateVariables(variables);
	const filledContent = applyVariables(template.text_template, vars);

	return apiSuccess(res, {
		content: filledContent,
		hashtags: template.hashtags || [],
		poll_options: template.poll_options || null,
		variables_used: vars,
	});
}

async function handleIncrementUse(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
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

	// Verify ownership and increment atomically
	const { data: existing } = await userDb
		.from("post_templates")
		.select("id, times_used")
		.eq("id", templateId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!existing) {
		return apiError(res, 404, "Template not found");
	}

	const { error } = await userDb
		.from("post_templates")
		.update({
			times_used: (existing.times_used || 0) + 1,
			last_used_at: new Date().toISOString(),
		})
		.eq("id", templateId)
		.eq("user_id", userId);

	if (error) {
		logger.error("[Post Templates] Failed to increment use count", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to increment template use count");
	}

	return apiSuccess(res);
}

// ---------------------------------------------------------------------------
// Main Handler
// ---------------------------------------------------------------------------

export default withAuthDb(async (req, res, context) => {
	const { user, userDb } = context;
	const userId = user.id;

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	// Rate limit: 30 requests/60s per user
	const rl = await checkRateLimit({
		key: `post-templates:${userId}`,
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
				logAudit(userId, "post-template.create", { req });
				return handleCreate(req, res, userId, userDb);
			case "update":
				logAudit(userId, "post-template.update", { req });
				return handleUpdate(req, res, userId, userDb);
			case "delete":
				logAudit(userId, "post-template.delete", { req });
				return handleDelete(req, res, userId, userDb);
			case "apply":
				return handleApply(req, res, userId, userDb);
			case "increment-use":
				return handleIncrementUse(req, res, userId, userDb);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("[Post Templates] API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
