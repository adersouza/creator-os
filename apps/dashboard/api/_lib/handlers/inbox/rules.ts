/**
 * Inbox Auto-Reply Rules API Route
 * POST /api/inbox-rules?action=list
 * POST /api/inbox-rules?action=create
 * POST /api/inbox-rules?action=update
 * POST /api/inbox-rules?action=delete
 * POST /api/inbox-rules?action=toggle
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logAudit } from "../../auditLog.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { requireMinTier } from "../../tierGate.js";
import { verifyWorkspaceAccess } from "../../workspaceAccess.js";
import { z } from "../../zodCompat.js";

const ListRulesSchema = z.object({
	workspace_id: z.string().min(1, "workspace_id is required"),
});

const CreateRuleSchema = z.object({
	workspace_id: z.string().min(1, "workspace_id is required"),
	account_id: z.string().optional(),
	trigger_type: z.string().min(1, "trigger_type is required"),
	trigger_pattern: z.string().min(1, "trigger_pattern is required"),
	reply_text: z.string().min(1, "reply_text is required"),
});

const UpdateRuleSchema = z.object({
	id: z.string().min(1, "id is required"),
	trigger_type: z.string().optional(),
	trigger_pattern: z.string().optional(),
	reply_text: z.string().optional(),
	account_id: z.string().optional(),
	is_active: z.boolean().optional(),
});

const DeleteRuleSchema = z.object({
	id: z.string().min(1, "id is required"),
});

const ToggleRuleSchema = z.object({
	id: z.string().min(1, "id is required"),
	is_active: z.boolean(),
});

export default withAuthDb(async (req, res, { user, userDb }) => {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const { action } = req.query;
	const body = req.body || {};
	if (["create", "update", "delete", "toggle"].includes(String(action))) {
		if (!(await requireMinTier(user.id, "pro", res))) return;
	}
	// biome-ignore lint/suspicious/noExplicitAny: auto_reply_rules typing lags runtime schema in generated Supabase types
	const db = userDb as any;

	// IDOR fix: helper to verify workspace membership
	async function verifyWorkspaceMember(workspaceId: string): Promise<boolean> {
		return verifyWorkspaceAccess(db, user.id, workspaceId);
	}

	try {
		switch (action) {
			case "list": {
				const parsed = ListRulesSchema.safeParse(body);
				if (!parsed.success) {
					return apiError(
						res,
						400,
						`Invalid input: ${parsed.error.issues[0]?.message}`,
					);
				}

				if (!(await verifyWorkspaceMember(parsed.data.workspace_id))) {
					return apiError(res, 403, "Not a member of this workspace");
				}

				const { data, error } = await db
					.from("auto_reply_rules")
					.select("*")
					.eq("workspace_id", parsed.data.workspace_id)
					.order("created_at", { ascending: false });

				if (error) throw error;
				return apiSuccess(res, { rules: data || [] });
			}

			case "create": {
				const parsed = CreateRuleSchema.safeParse(body);
				if (!parsed.success) {
					return apiError(
						res,
						400,
						`Invalid input: ${parsed.error.issues[0]?.message}`,
					);
				}

				if (!(await verifyWorkspaceMember(parsed.data.workspace_id))) {
					return apiError(res, 403, "Not a member of this workspace");
				}

				const {
					workspace_id,
					account_id,
					trigger_type,
					trigger_pattern,
					reply_text,
				} = parsed.data;

				const { data, error } = await db
					.from("auto_reply_rules")
					.insert({
						workspace_id,
						account_id: account_id || null,
						trigger_type,
						trigger_pattern,
						reply_text,
						is_active: true,
					})
					.select()
					.maybeSingle();

				if (error) throw error;
				logAudit(user.id, "inbox-rule.create", {
					resourceType: "inbox_rule",
					resourceId: data?.id,
					req,
				});
				return apiSuccess(res, { rule: data }, 201);
			}

			case "update": {
				const parsed = UpdateRuleSchema.safeParse(body);
				if (!parsed.success) {
					return apiError(
						res,
						400,
						`Invalid input: ${parsed.error.issues[0]?.message}`,
					);
				}

				const { id, ...updates } = parsed.data;

				// IDOR fix: verify rule belongs to a workspace the user is a member of
				const { data: existingRule } = await db
					.from("auto_reply_rules")
					.select("workspace_id")
					.eq("id", id)
					.maybeSingle();
				if (
					!existingRule ||
					!(await verifyWorkspaceMember(existingRule.workspace_id))
				) {
					return apiError(res, 403, "Not authorized to modify this rule");
				}

				const allowedFields = [
					"trigger_type",
					"trigger_pattern",
					"reply_text",
					"account_id",
					"is_active",
				];
				const safeUpdates: Record<string, unknown> = {
					updated_at: new Date().toISOString(),
				};
				for (const key of allowedFields) {
					if (key in updates)
						safeUpdates[key] = (updates as Record<string, unknown>)[key];
				}

				const { data, error } = await db
					.from("auto_reply_rules")
					.update(safeUpdates)
					.eq("id", id)
					.select()
					.maybeSingle();

				if (error) throw error;
				return apiSuccess(res, { rule: data });
			}

			case "delete": {
				const parsed = DeleteRuleSchema.safeParse(body);
				if (!parsed.success) {
					return apiError(
						res,
						400,
						`Invalid input: ${parsed.error.issues[0]?.message}`,
					);
				}

				// IDOR fix: verify rule belongs to user's workspace
				const { data: ruleToDelete } = await db
					.from("auto_reply_rules")
					.select("workspace_id")
					.eq("id", parsed.data.id)
					.maybeSingle();
				if (
					!ruleToDelete ||
					!(await verifyWorkspaceMember(ruleToDelete.workspace_id))
				) {
					return apiError(res, 403, "Not authorized to delete this rule");
				}

				const { error } = await db
					.from("auto_reply_rules")
					.delete()
					.eq("id", parsed.data.id);

				if (error) throw error;
				logAudit(user.id, "inbox-rule.delete", {
					resourceType: "inbox_rule",
					resourceId: parsed.data.id,
					req,
				});
				return apiSuccess(res, {});
			}

			case "toggle": {
				const parsed = ToggleRuleSchema.safeParse(body);
				if (!parsed.success) {
					return apiError(
						res,
						400,
						`Invalid input: ${parsed.error.issues[0]?.message}`,
					);
				}

				// IDOR fix: verify rule belongs to user's workspace
				const { data: ruleToToggle } = await db
					.from("auto_reply_rules")
					.select("workspace_id")
					.eq("id", parsed.data.id)
					.maybeSingle();
				if (
					!ruleToToggle ||
					!(await verifyWorkspaceMember(ruleToToggle.workspace_id))
				) {
					return apiError(res, 403, "Not authorized to modify this rule");
				}

				const { data, error } = await db
					.from("auto_reply_rules")
					.update({
						is_active: parsed.data.is_active,
						updated_at: new Date().toISOString(),
					})
					.eq("id", parsed.data.id)
					.select()
					.maybeSingle();

				if (error) throw error;
				return apiSuccess(res, { rule: data });
			}

			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Inbox rules error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
