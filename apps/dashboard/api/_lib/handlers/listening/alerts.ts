/**
 * Social Listening Alerts — CRUD
 *
 * GET    /api/listening/alerts?workspace_id=X  — list alerts
 * POST   /api/listening/alerts                  — create alert
 * PUT    /api/listening/alerts?id=X             — update alert
 * DELETE /api/listening/alerts?id=X             — delete alert
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database } from "../../../../types/supabase.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { withAuthDb } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { requireMinTier } from "../../tierGate.js";
import { verifyWorkspaceAccess } from "../../workspaceAccess.js";
import { z, zEnum } from "../../zodCompat.js";

const AlertSchema = z.object({
	keyword: z.string().min(1).max(200),
	alert_type: zEnum(["spike", "threshold"]).default("spike"),
	threshold_value: z.number().int().min(1).max(10000).default(10),
	is_active: z.boolean().default(true),
	workspace_id: z.string().optional(),
});

type ListeningAlertUpdate =
	Database["public"]["Tables"]["listening_alerts"]["Update"];
type UserDb = DbContext["userDb"];

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context) => {
		const { user, userDb } = context;
		const allowed = await requireMinTier(user.id, "pro", res);
		if (!allowed) return;

		if (req.method !== "GET") {
			const rl = await checkRateLimit({
				key: `listening-alerts:${user.id}`,
				limit: 30,
				windowSeconds: 60,
				failMode: "open",
			});
			if (!rl.allowed) {
				return apiError(res, 429, "Rate limit exceeded. Try again shortly.");
			}
		}

		if (req.method === "GET") {
			const workspaceId = req.query.workspace_id as string | undefined;

			let alertQuery = userDb
				.from("listening_alerts")
				.select("*")
				.eq("user_id", user.id)
				.order("created_at", { ascending: false });

			if (workspaceId) {
				alertQuery = alertQuery.eq("workspace_id", workspaceId);
			}

			const { data, error } = await alertQuery;

			if (error) return apiError(res, 500, "Failed to load alerts");
			return apiSuccess(res, { alerts: data || [] });
		}

		if (req.method === "POST") {
			const parsed = AlertSchema.safeParse(req.body);
			if (!parsed.success)
				return apiError(
					res,
					400,
					parsed.error.issues[0]?.message || "Invalid input",
				);

			// Validate workspace membership to prevent cross-tenant IDOR
			if (parsed.data.workspace_id) {
				const hasAccess = await verifyWorkspaceAccess(
					userDb as Parameters<typeof verifyWorkspaceAccess>[0],
					user.id,
					parsed.data.workspace_id,
				);
				if (!hasAccess) {
					return apiError(res, 403, "Not authorized for this workspace");
				}
			}

			// biome-ignore lint/suspicious/noExplicitAny: listening_alerts Insert type mismatch with workspace_id nullability
			const { data, error } = await (userDb as UserDb & { from: (table: "listening_alerts") => any })
				.from("listening_alerts")
				.insert({
					user_id: user.id,
					keyword: parsed.data.keyword,
					alert_type: parsed.data.alert_type as string,
					threshold_value: parsed.data.threshold_value,
					is_active: parsed.data.is_active,
					workspace_id: parsed.data.workspace_id || null,
				})
				.select()
				.maybeSingle();

			if (error) return apiError(res, 500, "Failed to create alert");
			return apiSuccess(res, { alert: data });
		}

		if (req.method === "PUT") {
			const id = req.query.id as string;
			if (!id) return apiError(res, 400, "id required");

			const parsed = AlertSchema.partial().safeParse(req.body);
			if (!parsed.success)
				return apiError(
					res,
					400,
					parsed.error.issues[0]?.message || "Invalid input",
				);

			// Strip workspace_id to prevent reassignment
			const { workspace_id, ...updateData } = parsed.data;
			const alertUpdate: ListeningAlertUpdate = {};
			if (updateData.keyword !== undefined)
				alertUpdate.keyword = updateData.keyword;
			if (updateData.alert_type !== undefined) {
				alertUpdate.alert_type = updateData.alert_type;
			}
			if (updateData.threshold_value !== undefined) {
				alertUpdate.threshold_value = updateData.threshold_value;
			}
			if (updateData.is_active !== undefined) {
				alertUpdate.is_active = updateData.is_active;
			}

			const { data, error } = await userDb
				.from("listening_alerts")
				.update(alertUpdate)
				.eq("id", id)
				.eq("user_id", user.id)
				.select()
				.maybeSingle();

			if (error) return apiError(res, 500, "Failed to update alert");
			if (!data) return apiError(res, 404, "Alert not found");
			return apiSuccess(res, { alert: data });
		}

		if (req.method === "DELETE") {
			const id = req.query.id as string;
			if (!id) return apiError(res, 400, "id required");

			const { data, error } = await userDb
				.from("listening_alerts")
				.delete()
				.eq("id", id)
				.eq("user_id", user.id)
				.select("id")
				.maybeSingle();

			if (error) {
				return apiError(res, 500, "Failed to delete alert");
			}
			if (!data) return apiError(res, 404, "Alert not found");
			return apiSuccess(res, { deleted: true });
		}

		return apiError(res, 405, "Method not allowed");
	},
);
