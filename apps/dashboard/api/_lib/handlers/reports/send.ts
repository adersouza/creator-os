import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { sendReportEmail } from "../../emailService.js";
import { logger } from "../../logger.js";
import { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } from "../../privilegedDb.js";
import { buildPdfReport } from "../../reportBuilder.js";
import { resolveReportScope } from "../../reportScope.js";
import { z } from "../../zodCompat.js";

const SendReportSchema = z.object({
	report_id: z.string().min(1).optional(),
	reportId: z.string().min(1).optional(),
});

type ReportRecipient = string | { email?: string | undefined };

interface ReportConfig {
	dateRange?: { start?: string | undefined; end?: string | undefined } | undefined;
	accountIds?: string[] | undefined;
	groupIds?: string[] | undefined;
	platform?: "threads" | "instagram" | "all" | undefined;
	metrics?: string[] | undefined;
	sections?: string[] | undefined;
	delivery?: "now" | "scheduled" | undefined;
}

type ReportConfigRecord = ReportConfig & Record<string, unknown>;

interface ReportRow {
	id: string;
	user_id: string;
	name: string;
	cadence: string;
	network: string | null;
	recipients: ReportRecipient[] | null;
	config: ReportConfigRecord | null;
}

const DAY_MS = 24 * 60 * 60 * 1000;

export async function sendReportById({
	reportId,
	userId,
	markNextRun = false,
	now = new Date(),
}: {
	reportId: string;
	userId: string;
	markNextRun?: boolean | undefined;
	now?: Date | undefined;
}) {
	const db = getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.reportDelivery);
	const { data: report, error } = await db
		.from("reports")
		.select("id, user_id, name, cadence, network, recipients, config")
		.eq("id", reportId)
		.eq("user_id", userId)
		.maybeSingle();

	if (error) throw error;
	if (!report) return { ok: false, status: 404, error: "Report not found" };

	const row = report as ReportRow;
	const recipients = extractRecipients(row.recipients);
	if (recipients.length === 0) {
		await insertSendLog(row.id, [], "skipped", "No recipients");
		return { ok: false, status: 400, error: "Report has no recipients" };
	}

	const scope = await resolveReportScope(row);
	if (!scope.ok) {
		await insertSendLog(row.id, recipients, "failed", scope.error);
		return { ok: false, status: scope.status, error: scope.error };
	}

	const dateRange = resolveDateRange(row, now);
	const reportType = cadenceToReportType(row.cadence);
	const pdfParams =
		scope.accountIds.length > 1
			? {
					reportType: "consolidated" as const,
					dateRange,
					platform: scope.platform,
					accountIds: scope.accountIds,
					clientName: row.name,
				}
			: {
					reportType,
					dateRange,
					platform: scope.platform,
					accountId: scope.accountIds[0],
					clientName: row.name,
				};

	const pdfResult = await buildPdfReport(userId, pdfParams);
	if (!pdfResult.success) {
		const errorMessage = "error" in pdfResult ? pdfResult.error : "PDF generation failed";
		await insertSendLog(row.id, recipients, "failed", errorMessage);
		return { ok: false, status: 500, error: errorMessage };
	}

	const html = reportEmailHtml(row, dateRange);
	const attachments = [
		{
			filename: pdfResult.filename,
			content: pdfResult.pdfBuffer.toString("base64"),
		},
	];

	let delivered = 0;
	let lastError: string | undefined;
	for (const email of recipients) {
		const result = await sendReportEmail(
			email,
			`Analytics Report: ${row.name}`,
			html,
			attachments,
		);
		if (result.success) delivered += 1;
		else lastError = result.error ?? "Email delivery failed";
	}

	const status = delivered > 0 ? "sent" : "failed";
	await insertSendLog(row.id, recipients, status, status === "failed" ? lastError : undefined);

	const nextRunAt = markNextRun ? nextRun(row.cadence, now) : undefined;
	await db
		.from("reports")
		.update({
			last_sent_at: now.toISOString(),
			last_run_at: now.toISOString(),
			status: nextRunAt ? "active" : "generated",
			...(nextRunAt !== undefined ? { next_run_at: nextRunAt } : {}),
			updated_at: now.toISOString(),
		})
		.eq("id", row.id)
		.eq("user_id", userId);

	return {
		ok: delivered > 0,
		status: delivered > 0 ? 200 : 502,
		delivered,
		recipients: recipients.length,
		scope: scope.scopeLabel,
		warnings: scope.warnings,
		error: delivered > 0 ? undefined : lastError,
	};
}

export default async function sendReportHandler(
	req: VercelRequest,
	res: VercelResponse,
	user: { id: string },
) {
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");
	const parsed = SendReportSchema.safeParse(req.body);
	if (!parsed.success) return apiError(res, 400, "report_id is required");
	const reportId = parsed.data.report_id ?? parsed.data.reportId;
	if (!reportId) return apiError(res, 400, "report_id is required");
	const result = await sendReportById({ reportId, userId: user.id });
	if (!result.ok) return apiError(res, result.status, result.error ?? "Send failed");
	return apiSuccess(res, result);
}

function extractRecipients(recipients: ReportRecipient[] | null | undefined): string[] {
	if (!Array.isArray(recipients)) return [];
	return recipients
		.map((recipient) =>
			typeof recipient === "string" ? recipient : recipient?.email ?? "",
		)
		.map((email) => email.trim())
		.filter((email) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email));
}

function resolveDateRange(report: ReportRow, now: Date): { start: string; end: string } {
	const configured = report.config?.dateRange;
	if (configured?.start && configured?.end) {
		return { start: configured.start, end: configured.end };
	}
	const days =
		report.cadence === "weekly" ? 7 : report.cadence === "quarterly" ? 90 : 30;
	const start = new Date(now.getTime() - days * DAY_MS);
	return { start: toDay(start), end: toDay(now) };
}

function cadenceToReportType(cadence: string): "weekly" | "monthly" | "custom" {
	if (cadence === "weekly") return "weekly";
	if (cadence === "monthly") return "monthly";
	return "custom";
}

function nextRun(cadence: string, from: Date): string | null {
	const next = new Date(from);
	next.setUTCHours(8, 0, 0, 0);
	if (cadence === "weekly") next.setUTCDate(next.getUTCDate() + 7);
	else if (cadence === "monthly") next.setUTCMonth(next.getUTCMonth() + 1);
	else if (cadence === "quarterly") next.setUTCMonth(next.getUTCMonth() + 3);
	else return null;
	return next.toISOString();
}

function toDay(date: Date): string {
	return date.toISOString().slice(0, 10);
}

async function insertSendLog(
	reportId: string,
	recipients: string[],
	status: "sent" | "failed" | "skipped",
	error?: string,
) {
	const db = getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.reportDelivery);
	const { error: insertError } = await db.from("report_send_log").insert({
		report_id: reportId,
		recipients,
		status,
		...(error ? { error } : {}),
	});
	if (insertError) {
		logger.warn("[reports/send] send log insert failed", {
			reportId,
			error: insertError.message,
		});
	}
}

function reportEmailHtml(report: ReportRow, dateRange: { start: string; end: string }) {
	return `
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#18181b">
      <h1 style="font-size:24px;margin:0 0 12px">${escapeHtml(report.name)}</h1>
      <p style="font-size:14px;line-height:1.6;margin:0 0 18px;color:#52525b">
        Your report for ${escapeHtml(dateRange.start)} to ${escapeHtml(dateRange.end)} is attached as a PDF.
      </p>
      <p style="font-size:12px;color:#71717a;margin:0">Sent by Juno33 Reports.</p>
    </div>
  `;
}

function escapeHtml(value: string): string {
	return value
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}
