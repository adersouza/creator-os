import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import type { DbContext } from "./_lib/dbContext.js";
import { logger } from "./_lib/logger.js";
import { withAuthDb } from "./_lib/middleware.js";
import { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } from "./_lib/privilegedDb.js";
import { checkRateLimit } from "./_lib/rateLimiter.js";
import { buildPdfReport, type ReportParams } from "./_lib/reportBuilder.js";
import { resolveReportScope } from "./_lib/reportScope.js";
import { requireMinTier } from "./_lib/tierGate.js";
import { z, zEnum } from "./_lib/zodCompat.js";

const GenerateReportSchema = z.object({
	accountId: z.string().min(1, "accountId is required").optional(),
	reportType: zEnum(["weekly", "monthly", "custom", "consolidated"], {
		message: "reportType must be weekly, monthly, custom, or consolidated",
	}),
	dateRange: z.object({
		start: z.string().min(1, "dateRange.start is required"),
		end: z.string().min(1, "dateRange.end is required"),
	}),
	includeRecommendations: z.boolean().optional(),
	clientName: z.string().max(100).optional(),
	platform: zEnum(["threads", "instagram"]).optional(),
	accountIds: z.array(z.string()).optional(),
});

async function generateReport(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = GenerateReportSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const result = await buildPdfReport(userId, parsed.data as ReportParams);
	if (result.success === false) {
		return apiError(res, result.status, result.error);
	}

	return apiSuccess(res, {
		pdf: result.pdfBase64,
		filename: result.filename,
		stats: result.stats,
	});
}

const GenerateFromReportSchema = z.object({
	reportId: z.string().min(1, "reportId is required"),
});

async function enforceReportRateLimit(
	action: string,
	userId: string,
	res: VercelResponse,
): Promise<boolean> {
	const limits: Record<string, { limit: number; windowSeconds: number }> = {
		generate: { limit: 10, windowSeconds: 3600 },
		generateFromReport: { limit: 10, windowSeconds: 3600 },
		send: { limit: 5, windowSeconds: 3600 },
		update: { limit: 60, windowSeconds: 60 },
	};
	const config = limits[action] ?? { limit: 30, windowSeconds: 60 };
	const rl = await checkRateLimit({
		key: `reports:${action}:${userId}`,
		limit: config.limit,
		windowSeconds: config.windowSeconds,
		failMode: action === "update" ? "open" : "closed",
	});
	res.setHeader("X-RateLimit-Limit", String(config.limit));
	res.setHeader("X-RateLimit-Remaining", String(rl.remaining));
	if (rl.retryAfterSeconds) {
		res.setHeader("Retry-After", String(rl.retryAfterSeconds));
	}
	if (!rl.allowed) {
		apiError(res, 429, "Rate limit exceeded. Please wait a moment.", {
			code: "RATE_LIMITED",
		});
		return false;
	}
	return true;
}

// Map the /reports page cadence values to the existing generator's reportType
// vocabulary. Quarterly + one-off fall back to "custom" with a cadence-derived
// date range; the generator doesn't care about the label, only the window.
function cadenceToWindow(cadence: string): {
	reportType: "weekly" | "monthly" | "custom";
	days: number;
} {
	switch (cadence) {
		case "weekly":
			return { reportType: "weekly", days: 7 };
		case "monthly":
			return { reportType: "monthly", days: 30 };
		case "quarterly":
			return { reportType: "custom", days: 90 };
		default: // one-off + anything unexpected — 30d default
			return { reportType: "custom", days: 30 };
	}
}

/**
 * Wire for the Reports page Download button: client sends `{ reportId }`, we
 * look up the row under RLS, resolve account set + date range from the stored
 * metadata, and hand off to `generateReport`.
 */
async function generateFromReport(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = GenerateFromReportSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { reportId } = parsed.data;
	const supabase = getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.reportGeneration);

	const { data: report, error: reportErr } = await supabase
		.from("reports")
		.select("id, user_id, name, cadence, network, config")
		.eq("id", reportId)
		.eq("user_id", userId)
		.maybeSingle();
	if (reportErr) {
		logger.error("Report lookup failed", { error: reportErr.message });
		return apiError(res, 500, "Could not load report");
	}
	if (!report) return apiError(res, 404, "Report not found");

	const scope = await resolveReportScope(report);
	if (!scope.ok) {
		return apiError(res, scope.status, scope.error, {
			code: "REPORT_SCOPE_UNAVAILABLE",
			extra: {
				scope: scope.scopeLabel,
				warnings: scope.warnings,
			},
		});
	}

	const { reportType, days } = cadenceToWindow(String(report.cadence));
	const end = new Date();
	const start = new Date();
	start.setDate(start.getDate() - days);
	const toDay = (d: Date): string => d.toISOString().slice(0, 10);

	const effectiveReportType =
		scope.accountIds.length > 1 ? "consolidated" : reportType;
	const body =
		effectiveReportType === "consolidated"
			? {
					reportType: "consolidated",
					dateRange: { start: toDay(start), end: toDay(end) },
					platform: scope.platform,
					accountIds: scope.accountIds,
					clientName: String(report.name),
				}
			: {
					reportType,
					dateRange: { start: toDay(start), end: toDay(end) },
					platform: scope.platform,
					accountId: scope.accountIds[0],
					clientName: String(report.name),
				};
	req.body = body;

	await generateReport(req, res, userId);

	if (res.statusCode === 200) {
		supabase
			.from("reports")
			.update({
				last_run_at: new Date().toISOString(),
				status: "generated",
				updated_at: new Date().toISOString(),
			})
			.eq("id", reportId)
			.then(({ error }: { error: { message?: string | undefined } | null }) => {
				if (error) {
					logger.error("last_run_at update failed", {
						reportId,
						error: error.message,
					});
				}
			});
	}
}

export default withAuthDb(async (req, res, context: DbContext) => {
	const { user } = context;
	if (!(await requireMinTier(user.id, "pro", res))) return;

	if (req.method !== "POST" && req.method !== "PUT") {
		return apiError(res, 405, "Method not allowed");
	}

	const action = req.query.action as string;

	try {
		if (!(await enforceReportRateLimit(action, user.id, res))) return;

		if (action === "generate") {
			return await generateReport(req, res, user.id);
		}
		if (action === "generateFromReport") {
			return await generateFromReport(req, res, user.id);
		}
		if (action === "update") {
			return (await import("./_lib/handlers/reports/update.js")).default(
				req,
				res,
				context,
			);
		}
		if (action === "send") {
			return (await import("./_lib/handlers/reports/send.js")).default(
				req,
				res,
				user,
			);
		}
		return apiError(res, 400, `Unknown action: ${action}`);
	} catch (error: unknown) {
		logger.error("Reports error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
