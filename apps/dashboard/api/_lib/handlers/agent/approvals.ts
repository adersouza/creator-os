/**
 * Agent Approvals
 *
 * POST /api/agent/approvals        — request human approval (MCP → notifies user)
 * GET  /api/agent/approvals        — list pending/recent approvals
 * PATCH /api/agent/approvals       — approve or reject (user action)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { withAuthDb } from "../../middleware.js";
import { z, zArray, zEnum, zUnknown } from "../../zodCompat.js";

const CreateSchema = z.object({
	session_id: z.string().optional().nullable(),
	context: z.string().min(1).max(2000),
	proposed_actions: zArray(zUnknown()).optional(),
	urgency: zEnum(["low", "medium", "high"]).default("medium"),
	expires_in_hours: z.number().int().min(1).max(168).default(24),
});

const DecideSchema = z.object({
	id: z.string().uuid(),
	decision: zEnum(["approved", "rejected"]),
	note: z.string().max(500).optional().nullable(),
});

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context: DbContext) => {
		const { user, userDb } = context;
		// ── POST: Claude requests approval ────────────────────────────────────────
		if (req.method === "POST") {
			const parsed = CreateSchema.safeParse(req.body);
			if (!parsed.success)
				return apiError(
					res,
					400,
					parsed.error.issues[0]?.message || "Invalid input",
				);

			const {
				session_id,
				context,
				proposed_actions,
				urgency,
				expires_in_hours,
			} = parsed.data;

			const expiresAt = new Date(
				Date.now() + expires_in_hours * 3600 * 1000,
			).toISOString();
			const baseUrl =
				process.env.APP_URL ||
				(process.env.VERCEL_URL
					? `https://${process.env.VERCEL_URL}`
					: "https://juno33.com");

			const { data: approval, error } = await userDb
				.from("agent_approvals")
				.insert({
					user_id: user.id,
					session_id: session_id ?? null,
					context,
					proposed_actions: proposed_actions ?? [],
					urgency,
					status: "pending",
					expires_at: expiresAt,
				})
				.select("id")
				.single();

			if (error || !approval)
				return apiError(res, 500, "Failed to create approval request");

			// Fire-and-forget notification
			const urgencyEmoji =
				urgency === "high" ? "🔴" : urgency === "medium" ? "🟡" : "🟢";
			import("../../createNotification.js")
				.then(({ createNotification }) =>
					createNotification({
						userId: user.id,
						type: "agent_approval_requested",
						title: `${urgencyEmoji} Agent approval needed`,
						message: context.slice(0, 200),
						data: {
							approvalId: approval.id,
							urgency,
							expiresAt,
							reviewUrl: `${baseUrl}/approval-queue?approvalId=${approval.id}`,
						},
					}),
				)
				.catch(() => {});

			return apiSuccess(res, {
				approvalId: approval.id,
				status: "pending",
				urgency,
				expiresAt,
				message: "Approval request sent. Waiting for your decision.",
			});
		}

		// ── GET: list approvals ───────────────────────────────────────────────────
		if (req.method === "GET") {
			const { id, action } = req.query as { id?: string | undefined; action?: string | undefined };
			if (id && action && (action === "approve" || action === "reject")) {
				return apiError(
					res,
					405,
					"Approval decisions require authenticated PATCH from the approval queue.",
				);
			}

			const status = (req.query.status as string) || "pending";
			const limit = Math.min(
				parseInt(req.query.limit as string, 10) || 20,
				100,
			);

			let query = userDb
				.from("agent_approvals")
				.select("*")
				.eq("user_id", user.id)
				.order("created_at", { ascending: false })
				.limit(limit);

			if (status !== "all") query = query.eq("status", status);

			// Auto-expire
			await userDb
				.from("agent_approvals")
				.update({ status: "expired" })
				.eq("user_id", user.id)
				.eq("status", "pending")
				.lt("expires_at", new Date().toISOString());

			const { data, error } = await query;
			if (error) return apiError(res, 500, "Failed to fetch approvals");
			return apiSuccess(res, { approvals: data || [] });
		}

		// ── PATCH: approve or reject ──────────────────────────────────────────────
		if (req.method === "PATCH") {
			const parsed = DecideSchema.safeParse(req.body);
			if (!parsed.success)
				return apiError(
					res,
					400,
					parsed.error.issues[0]?.message || "Invalid input",
				);

			const { id, decision, note } = parsed.data;

			const { data, error } = await userDb
				.from("agent_approvals")
				.update({
					status: decision,
					decided_at: new Date().toISOString(),
					decision_note: note ?? null,
				})
				.eq("id", id)
				.eq("user_id", user.id)
				.eq("status", "pending")
				.select("id, status, decided_at")
				.single();

			if (error || !data)
				return apiError(res, 404, "Approval not found or already decided");
			return apiSuccess(res, {
				id: data.id,
				status: data.status,
				decidedAt: data.decided_at,
			});
		}

		return apiError(res, 405, "Method not allowed");
	},
);
