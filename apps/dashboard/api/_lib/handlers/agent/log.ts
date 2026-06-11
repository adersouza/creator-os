/**
 * Agent Action Log
 *
 * GET  /api/agent/log  — read MCP tool call history
 * POST /api/agent/log  — write a tool call entry (called by MCP server)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database, Json } from "../../../../types/supabase.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { withAuthDb } from "../../middleware.js";
import { z, zRecord, zUnknown } from "../../zodCompat.js";

type AgentActionInsert = Database["public"]["Tables"]["agent_actions"]["Insert"];

const WriteSchema = z.object({
	session_id: z.string().min(1),
	tool_name: z.string().min(1),
	params_json: zRecord(zUnknown()).optional().nullable(),
	reason: z.string().max(500).optional().nullable(),
	result_summary: z.string().max(500).optional().nullable(),
	success: z.boolean().default(true),
	duration_ms: z.number().int().optional().nullable(),
});

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context: DbContext) => {
		const { user, userDb } = context;
		if (req.method === "GET") {
			const since = req.query.since as string | undefined;
			const limit = Math.min(
				parseInt(req.query.limit as string, 10) || 50,
				200,
			);
			const toolName = req.query.tool_name as string | undefined;
			const sessionId = req.query.session_id as string | undefined;

			let query = userDb
				.from("agent_actions")
				.select("*", { count: "exact" })
				.eq("user_id", user.id)
				.order("created_at", { ascending: false })
				.limit(limit);

			if (since) query = query.gte("created_at", since);
			if (toolName) query = query.eq("tool_name", toolName);
			if (sessionId) query = query.eq("session_id", sessionId);

			const { data, error, count } = await query;
			if (error) return apiError(res, 500, "Failed to fetch agent log");
			return apiSuccess(res, { actions: data || [], total: count ?? 0 });
		}

		if (req.method === "POST") {
			const parsed = WriteSchema.safeParse(req.body);
			if (!parsed.success)
				return apiError(
					res,
					400,
					parsed.error.issues[0]?.message || "Invalid input",
				);

			const payload: AgentActionInsert = {
				user_id: user.id,
				session_id: parsed.data.session_id,
				tool_name: parsed.data.tool_name,
				success: parsed.data.success,
			};
			if (parsed.data.params_json !== undefined) {
				payload.params_json = parsed.data.params_json as Json;
			}
			if (parsed.data.reason !== undefined) {
				payload.reason = parsed.data.reason;
			}
			if (parsed.data.result_summary !== undefined) {
				payload.result_summary = parsed.data.result_summary;
			}
			if (parsed.data.duration_ms !== undefined) {
				payload.duration_ms = parsed.data.duration_ms;
			}

			const { error } = await userDb
				.from("agent_actions")
				.insert(payload);

			if (error) return apiError(res, 500, "Failed to write agent log");
			return apiSuccess(res, { logged: true });
		}

		return apiError(res, 405, "Method not allowed");
	},
);
