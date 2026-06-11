import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database, Json } from "../../../../types/supabase.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { z, zEnum, zRecord, zUnknown } from "../../zodCompat.js";

type ReportUpdate = Database["public"]["Tables"]["reports"]["Update"];

const RecipientSchema = z.object({
	email: z.string().email(),
	name: z.string().optional(),
});

const UpdateReportSchema = z.object({
	report_id: z.string().min(1).optional(),
	reportId: z.string().min(1).optional(),
	name: z.string().min(1).max(160).optional(),
	type: zEnum(["scheduled", "one-off"]).optional(),
	cadence: zEnum(["weekly", "monthly", "quarterly", "one-off"]).optional(),
	status: zEnum(["active", "paused", "generated", "draft"]).optional(),
	network: z.string().nullable().optional(),
	recipients: z.array(RecipientSchema).optional(),
	next_run_at: z.string().nullable().optional(),
	nextRunAt: z.string().nullable().optional(),
	config: zRecord(zUnknown()).optional(),
});

export default async function updateReportHandler(
	req: VercelRequest,
	res: VercelResponse,
	context: DbContext,
) {
	const { user, userDb } = context;
	if (req.method !== "PUT") return apiError(res, 405, "Method not allowed");
	const parsed = UpdateReportSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(res, 400, parsed.error.issues[0]?.message ?? "Invalid body");
	}

	const body = parsed.data;
	const reportId = body.report_id ?? body.reportId;
	if (!reportId) return apiError(res, 400, "report_id is required");

	const patch: ReportUpdate = {};
	if (body.name !== undefined) patch.name = body.name;
	if (body.type !== undefined) patch.type = body.type;
	if (body.cadence !== undefined) patch.cadence = body.cadence;
	if (body.status !== undefined) patch.status = body.status;
	if (body.network !== undefined) patch.network = body.network;
	if (body.recipients !== undefined) patch.recipients = body.recipients as Json;
	if (body.next_run_at !== undefined) patch.next_run_at = body.next_run_at;
	if (body.nextRunAt !== undefined) patch.next_run_at = body.nextRunAt;
	if (body.config !== undefined) patch.config = body.config as Json;
	patch.updated_at = new Date().toISOString();

	const { data, error } = await userDb
		.from("reports")
		.update(patch)
		.eq("id", reportId)
		.eq("user_id", user.id)
		.select(
			"id, name, type, cadence, status, network, recipients, last_run_at, next_run_at, config, last_sent_at, created_at, updated_at",
		)
		.maybeSingle();

	if (error) throw error;
	if (!data) return apiError(res, 404, "Report not found");
	return apiSuccess(res, { report: data });
}
