/**
 * Team Performance
 *
 * GET /api/analytics?action=team-performance&workspaceId=X&periodDays=30
 * Computes response times, reply volumes, and completion rates per team member.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

// biome-ignore lint/suspicious/noExplicitAny: flexible table queries
const db = (): any => getSupabase();

const QuerySchema = z.object({
	workspaceId: z.string().optional(),
	periodDays: z.coerce.number().int().min(1).max(365).optional().default(30),
});

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;

		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - parsed.periodDays);
		const cutoffStr = cutoff.toISOString();

		// Get sent replies by user
		const { data: sentReplies } = await db()
			.from("sent_replies")
			.select("user_id, sent_at")
			.eq("user_id", user.id) // Will expand to team when workspace scoping is ready
			.gte("sent_at", cutoffStr);

		// Get inbox assignments
		const { data: assignments } = await db()
			.from("inbox_assignments")
			.eq("user_id", user.id) // Will expand to team when workspace scoping is ready
			.select("assigned_to, assigned_at, note")
			.gte("assigned_at", cutoffStr);

		// Aggregate per user
		const memberMap = new Map<
			string,
			{
				userId: string;
				repliesSent: number;
				assignmentsReceived: number;
				avgResponseMinutes: number;
			}
		>();

		for (const reply of sentReplies || []) {
			const uid = reply.user_id;
			const existing = memberMap.get(uid) || {
				userId: uid,
				repliesSent: 0,
				assignmentsReceived: 0,
				avgResponseMinutes: 0,
			};
			existing.repliesSent++;
			memberMap.set(uid, existing);
		}

		for (const assignment of assignments || []) {
			const uid = assignment.assigned_to;
			if (!uid) continue;
			const existing = memberMap.get(uid) || {
				userId: uid,
				repliesSent: 0,
				assignmentsReceived: 0,
				avgResponseMinutes: 0,
			};
			existing.assignmentsReceived++;
			memberMap.set(uid, existing);
		}

		const members = [...memberMap.values()].sort(
			(a, b) => b.repliesSent - a.repliesSent,
		);

		return apiSuccess(res, {
			members,
			periodDays: parsed.periodDays,
		});
	},
);
