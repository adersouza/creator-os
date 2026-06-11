/**
 * Revenue Snapshots
 *
 * GET  /api/analytics/revenue  — list snapshots (?accountGroupId, ?days=30)
 * POST /api/analytics/revenue  — log or delete a snapshot
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

function parseBoundedNumber(
	value: unknown,
	field: string,
	max: number,
): { ok: true; value: number | null } | { ok: false; message: string } {
	if (value === undefined || value === null || value === "") {
		return { ok: true, value: null };
	}
	const num = typeof value === "number" ? value : Number(value);
	if (!Number.isFinite(num) || num < 0 || num > max) {
		return {
			ok: false,
			message: `${field} must be a finite number between 0 and ${max}`,
		};
	}
	return { ok: true, value: num };
}

function parseRecordedAt(value: unknown):
	| { ok: true; value: string }
	| { ok: false; message: string } {
	const date = value ? new Date(String(value)) : new Date();
	const ts = date.getTime();
	if (!Number.isFinite(ts)) {
		return { ok: false, message: "recordedAt must be a valid date" };
	}
	const now = Date.now();
	const earliest = now - 366 * 86_400_000;
	const latest = now + 24 * 60 * 60 * 1000;
	if (ts < earliest || ts > latest) {
		return {
			ok: false,
			message: "recordedAt must be within the last 366 days and not more than 24 hours in the future",
		};
	}
	return { ok: true, value: date.toISOString() };
}

function labelManualSnapshot<T extends Record<string, unknown>>(row: T): T & {
	metric_source: "manual";
} {
	return { ...row, metric_source: "manual" };
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		const userId = user.id;

		if (req.method === "GET") {
			const accountGroupId = req.query.accountGroupId as string | undefined;
			const days = Math.min(
				Math.max(parseInt(req.query.days as string, 10) || 30, 1),
				365,
			);
			const cutoff = new Date(Date.now() - days * 86_400_000).toISOString();

			let query = db()
				.from("revenue_snapshots")
				.select("*")
				.eq("user_id", userId)
				.gte("recorded_at", cutoff)
				.order("recorded_at", { ascending: true });

			if (accountGroupId) {
				query = query.eq("account_group_id", accountGroupId);
			}

			const { data, error } = await query;
			if (error)
				return apiError(res, 500, "Failed to fetch snapshots", {
					details: error.message,
				});

			const snapshots = (data ?? []).map(labelManualSnapshot);

			// Calculate trend if >=2 records
			let trend = null;
			if (snapshots.length >= 2) {
				const first = snapshots[0];
				const last = snapshots[snapshots.length - 1];
				trend = {
					subscribersDelta: (last.subscribers ?? 0) - (first.subscribers ?? 0),
					revenueDelta: (last.revenue ?? 0) - (first.revenue ?? 0),
					periodDays: days,
					dataPoints: snapshots.length,
				};
			}

			return apiSuccess(res, { snapshots, trend });
		}

		if (req.method === "POST") {
			const {
				action,
				accountGroupId,
				subscribers,
				revenue,
				notes,
				recordedAt,
				id,
			} = req.body ?? {};

			if (!action || !["log", "delete"].includes(action)) {
				return apiError(res, 400, "action must be 'log' or 'delete'");
			}

			if (action === "log") {
				if (!accountGroupId) {
					return apiError(res, 400, "accountGroupId is required");
				}
				if (subscribers === undefined && revenue === undefined) {
					return apiError(
						res,
						400,
						"At least one of subscribers or revenue is required",
					);
				}

				const { data: accountGroup, error: groupError } = await db()
					.from("account_groups")
					.select("id")
					.eq("id", accountGroupId)
					.eq("user_id", userId)
					.maybeSingle();

				if (groupError) {
					return apiError(res, 500, "Failed to verify account group", {
						details: groupError.message,
					});
				}
				if (!accountGroup) {
					return apiError(res, 404, "Account group not found");
				}

				const parsedSubscribers = parseBoundedNumber(
					subscribers,
					"subscribers",
					10_000_000,
				);
				if (!parsedSubscribers.ok) {
					return apiError(res, 400, parsedSubscribers.message);
				}
				const parsedRevenue = parseBoundedNumber(revenue, "revenue", 100_000_000);
				if (!parsedRevenue.ok) {
					return apiError(res, 400, parsedRevenue.message);
				}
				const parsedRecordedAt = parseRecordedAt(recordedAt);
				if (!parsedRecordedAt.ok) {
					return apiError(res, 400, parsedRecordedAt.message);
				}
				const safeNotes =
					typeof notes === "string" ? notes.slice(0, 1000) : null;

				const { data, error } = await db()
					.from("revenue_snapshots")
					.upsert(
						{
							user_id: userId,
							account_group_id: accountGroupId,
							recorded_at: parsedRecordedAt.value,
							subscribers: parsedSubscribers.value,
							revenue: parsedRevenue.value,
							notes: safeNotes,
						},
						{ onConflict: "user_id,account_group_id,recorded_at" },
					)
					.select()
					.maybeSingle();

				if (error)
					return apiError(res, 500, "Failed to log snapshot", {
						details: error.message,
					});
				return apiSuccess(res, {
					snapshot: data ? labelManualSnapshot(data) : data,
				});
			}

			// action === "delete"
			if (!id) {
				return apiError(res, 400, "id is required for delete");
			}

			const { error } = await db()
				.from("revenue_snapshots")
				.delete()
				.eq("id", id)
				.eq("user_id", userId);

			if (error)
				return apiError(res, 500, "Failed to delete snapshot", {
					details: error.message,
				});
			return apiSuccess(res, { deleted: id });
		}

		return apiError(res, 405, "Method not allowed");
	},
);
