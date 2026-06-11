import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	badRequest,
	methodNotAllowed,
} from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getWorkspaceAccess, verifyWorkspaceAccess } from "../../workspaceAccess.js";

/**
 * POST /api/inbox/assign  — Assign an inbox item to a team member
 * Body: { workspaceId, source, messageId, assignedTo, note? }
 *
 * DELETE /api/inbox/assign — Unassign an inbox item
 * Body: { workspaceId, source, messageId }
 *
 * GET /api/inbox/assign?workspaceId=X — List all assignments for workspace
 */
export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		// Rate limit: 30 requests per minute per user
		const rl = await checkRateLimit({
			key: `inbox-assign:${user.id}`,
			limit: 30,
			windowSeconds: 60,
			failMode: "open",
		});
		if (!rl.allowed) {
			return apiError(res, 429, "Too many requests. Please wait a moment.");
		}

		const { getSupabase } = await import("../../supabase.js");
		const supabase = getSupabase();

		if (req.method === "GET") {
			const workspaceId = req.query.workspaceId as string;
			if (!workspaceId) return badRequest(res, "workspaceId required");

			// Verify membership
			const hasWorkspaceAccess = await verifyWorkspaceAccess(
				supabase,
				user.id,
				workspaceId,
			);
			if (!hasWorkspaceAccess) {
				return apiError(res, 403, "Not a workspace member");
			}

			const { data, error } = await supabase
				.from("inbox_assignments")
				.select(
					"*, assignee:profiles!inbox_assignments_assigned_to_fkey(id, display_name, avatar_url)",
				)
				.eq("workspace_id", workspaceId);

			if (error)
				return apiError(res, 500, "Failed to fetch assignments", {
					details: error.message,
				});
			return apiSuccess(res, { assignments: data });
		}

		if (req.method === "POST") {
			const { workspaceId, source, messageId, assignedTo, note } =
				req.body || {};
			if (!workspaceId || !source || !messageId || !assignedTo) {
				return badRequest(
					res,
					"workspaceId, source, messageId, and assignedTo are required",
				);
			}

			const validSources = [
				"threads_reply",
				"threads_mention",
				"ig_comment",
				"ig_mention",
				"ig_dm",
			];
			if (!validSources.includes(source)) {
				return badRequest(
					res,
					`Invalid source. Must be one of: ${validSources.join(", ")}`,
				);
			}

			// Verify user is workspace member with assign permission
			const workspaceAccess = await getWorkspaceAccess(
				supabase,
				user.id,
				workspaceId,
			);
			if (!workspaceAccess.hasAccess) {
				return apiError(res, 403, "Not a workspace member");
			}
			const role = workspaceAccess.role ?? "owner";

			// Members can only self-assign; admins/owners can assign anyone
			if (role === "member" && assignedTo !== user.id) {
				return apiError(res, 403, "Members can only self-assign");
			}

			// Verify assignee is workspace member
			if (assignedTo !== user.id) {
				const assigneeHasWorkspaceAccess = await verifyWorkspaceAccess(
					supabase,
					assignedTo,
					workspaceId,
				);
				if (!assigneeHasWorkspaceAccess)
					return badRequest(res, "Assignee is not a workspace member");
			}

			const { data, error } = await supabase
				.from("inbox_assignments")
				.upsert(
					{
						workspace_id: workspaceId,
						source,
						message_id: messageId,
						assigned_to: assignedTo,
						assigned_by: user.id,
						note: note || null,
						assigned_at: new Date().toISOString(),
					},
					{ onConflict: "workspace_id,source,message_id" },
				)
				.select(
					"*, assignee:profiles!inbox_assignments_assigned_to_fkey(id, display_name, avatar_url)",
				)
				.maybeSingle();

			if (error)
				return apiError(res, 500, "Failed to assign", {
					details: error.message,
				});

			// Fire notification to assignee (if not self-assign)
			if (assignedTo !== user.id) {
				import("../../createNotification.js")
					.then(({ createNotification }) =>
						createNotification({
							userId: assignedTo,
							type: "team_updates",
							title: "Inbox item assigned to you",
							message: `You've been assigned an inbox item${note ? `: ${note}` : ""}`,
							data: { source, messageId, assignedBy: user.id },
						}),
					)
					.catch(() => {});
			}

			return apiSuccess(res, { assignment: data }, 201);
		}

		if (req.method === "DELETE") {
			const { workspaceId, source, messageId } = req.body || {};
			if (!workspaceId || !source || !messageId) {
				return badRequest(
					res,
					"workspaceId, source, and messageId are required",
				);
			}

			// Verify membership
			const workspaceAccess = await getWorkspaceAccess(
				supabase,
				user.id,
				workspaceId,
			);
			if (!workspaceAccess.hasAccess) {
				return apiError(res, 403, "Not a workspace member");
			}
			const role = workspaceAccess.role ?? "owner";

			// Members can only unassign themselves; admins/owners can unassign anyone
			if (role === "member") {
				const { data: existing } = await supabase
					.from("inbox_assignments")
					.select("assigned_to")
					.eq("workspace_id", workspaceId)
					.eq("source", source)
					.eq("message_id", messageId)
					.maybeSingle();
				if (existing && existing.assigned_to !== user.id) {
					return apiError(res, 403, "Members can only unassign themselves");
				}
			}

			const { error } = await supabase
				.from("inbox_assignments")
				.delete()
				.eq("workspace_id", workspaceId)
				.eq("source", source)
				.eq("message_id", messageId);

			if (error)
				return apiError(res, 500, "Failed to unassign", {
					details: error.message,
				});
			return apiSuccess(res, { unassigned: true });
		}

		return methodNotAllowed(res);
	},
);
