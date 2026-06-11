/**
 * Chart Annotations — CRUD for user-created markers on time-series charts.
 *
 * GET  /api/analytics?action=annotations&accountId=X&startDate=Y&endDate=Z
 * POST /api/analytics?action=annotations  { accountId, date, label, color?, type? }
 * DELETE via POST with { id, _method: "DELETE" }
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

// biome-ignore lint/suspicious/noExplicitAny: table not in generated types yet
const db = (): any => getSupabase();

const GetSchema = z.object({
	accountId: z.string().min(1),
	startDate: z.string().optional(),
	endDate: z.string().optional(),
});

const CreateSchema = z.object({
	accountId: z.string().min(1),
	date: z.string().min(1),
	label: z.string().min(1).max(200),
	color: z.string().max(20).optional(),
	type: z.string().optional(),
});

const DeleteSchema = z.object({
	id: z.string().min(1),
	_method: z.string().optional(),
});

async function verifyAccountOwnership(accountId: string, userId: string) {
	const [threadsAccount, instagramAccount] = await Promise.all([
		db()
			.from("accounts")
			.select("id")
			.eq("id", accountId)
			.eq("user_id", userId)
			.maybeSingle(),
		db()
			.from("instagram_accounts")
			.select("id")
			.eq("id", accountId)
			.eq("user_id", userId)
			.maybeSingle(),
	]);

	return Boolean(threadsAccount.data || instagramAccount.data);
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method === "GET") {
			const parsed = parseQueryOrError(res, GetSchema, req.query);
			if (!parsed) return;
			if (!(await verifyAccountOwnership(parsed.accountId, user.id))) {
				return apiError(res, 404, "Account not found");
			}

			const query = db()
				.from("chart_annotations")
				.select("*")
				.eq("user_id", user.id)
				.eq("account_id", parsed.accountId)
				.order("annotation_date", { ascending: true });

			if (parsed.startDate) query.gte("annotation_date", parsed.startDate);
			if (parsed.endDate) query.lte("annotation_date", parsed.endDate);

			const { data, error } = await query;
			if (error) return apiError(res, 500, "Failed to fetch annotations");
			return apiSuccess(res, { annotations: data || [] });
		}

		if (req.method === "POST") {
			const body = req.body || {};

			// Handle DELETE via POST
			if (body._method === "DELETE") {
				const parsed = DeleteSchema.safeParse(body);
				if (!parsed.success)
					return apiError(res, 400, "Invalid delete request");

				const { error, count } = await db()
					.from("chart_annotations")
					.delete({ count: "exact" })
					.eq("id", parsed.data.id)
					.eq("user_id", user.id);

				if (error) return apiError(res, 500, "Failed to delete annotation");
				if (!count) return apiError(res, 404, "Annotation not found");
				return apiSuccess(res, { deleted: true });
			}

			// Create annotation
			const parsed = CreateSchema.safeParse(body);
			if (!parsed.success) return apiError(res, 400, "Invalid annotation data");
			if (!(await verifyAccountOwnership(parsed.data.accountId, user.id))) {
				return apiError(res, 404, "Account not found");
			}

			const { data, error } = await db()
				.from("chart_annotations")
				.upsert(
					{
						user_id: user.id,
						account_id: parsed.data.accountId,
						annotation_date: parsed.data.date,
						label: parsed.data.label,
						color: parsed.data.color || "#38bdf8",
						annotation_type: parsed.data.type || "line",
					},
					{ onConflict: "user_id,account_id,annotation_date,label" },
				)
				.select()
				.maybeSingle();

			if (error) return apiError(res, 500, "Failed to create annotation");
			return apiSuccess(res, data);
		}

		return apiError(res, 405, "Method not allowed");
	},
);
