/**
 * Shared Report — Public endpoint for viewing shared reports.
 * No auth required — reads by share token.
 *
 * GET /api/shared-report?token=<share_token>
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import {
	enforceRouteRateLimit,
	getClientIp,
} from "./_lib/routeRateLimit.js";

type SharedReportRow = {
	id: string;
	report_type: string | null;
	title: string | null;
	generated_at: string | null;
	report_data: unknown;
	view_count: number | null;
	expires_at: string | null;
};

const SHARE_TOKEN_PATTERN = /^[A-Za-z0-9_-]{24,128}$/;

type SharedReportsClient = {
	from: (_table: "shared_reports") => {
		select: (_fields: string) => {
			eq: (
				_column: string,
				_value: string,
			) => {
				maybeSingle: () => Promise<{
					data: SharedReportRow | null;
					error: unknown;
				}>;
			};
		};
		update: (_values: { view_count: number }) => {
			eq: (_column: string, _value: string) => Promise<unknown>;
		};
	};
	rpc: (
		_fn: "increment_field",
		_args: {
			table_name: "shared_reports";
			row_id: string;
			field_name: "view_count";
			amount: number;
		},
	) => Promise<unknown>;
};

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const allowed = await enforceRouteRateLimit(res, {
		key: `shared-report:ip:${getClientIp(req)}:minute`,
		limit: 60,
		windowSeconds: 60,
		failMode: "open",
		message: "Too many shared report requests. Try again shortly.",
	});
	if (!allowed) return;

	const token = req.query.token as string;
	if (!token) {
		return apiError(res, 400, "Token required");
	}
	if (!SHARE_TOKEN_PATTERN.test(token)) {
		return apiError(res, 400, "Invalid token");
	}

	try {
		const { getPrivilegedSupabase, PRIVILEGED_DB_REASONS } = await import(
			"./_lib/privilegedDb.js"
		);
		const db = getPrivilegedSupabase(
			PRIVILEGED_DB_REASONS.publicSharedReport,
		) as unknown as SharedReportsClient;
		const baseDataFields =
			"id, report_type, title, generated_at, report_data, view_count, expires_at";

		const { data, error } = await db
			.from("shared_reports")
			.select(baseDataFields)
			.eq("share_token", token)
			.maybeSingle();

		if (error || !data) {
			return apiError(res, 404, "Report not found");
		}

		// Check expiry
		if (data.expires_at && new Date(data.expires_at) < new Date()) {
			return apiError(res, 410, "Report link has expired");
		}

		// Atomic view count increment
		await db
			.rpc("increment_field", {
				table_name: "shared_reports",
				row_id: data.id,
				field_name: "view_count",
				amount: 1,
			})
			.catch(() => {
				// Fallback to non-atomic if RPC doesn't exist
				db.from("shared_reports")
					.update({ view_count: (data.view_count || 0) + 1 })
					.eq("id", data.id);
			});

		return apiSuccess(res, data);
	} catch {
		return apiError(res, 500, "Internal server error");
	}
}
