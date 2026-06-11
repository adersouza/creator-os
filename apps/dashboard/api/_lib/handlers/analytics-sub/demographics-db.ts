// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Demographics DB Handler — reads stored audience demographics
 * GET /api/demographics?account_id=...&platform=threads|instagram
 * Merged from api/demographics.ts
 */

import type { PostgrestError } from "@supabase/supabase-js";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { z, zEnum } from "../../zodCompat.js";
import {
	verifyAccountOwnership,
	verifyIgAccountOwnership,
} from "../helpers/verifyOwnership.js";

interface DemographicsRow {
	breakdown_type: string;
	breakdown_value: string;
	count: number;
	percentage: number | null;
	fetched_at: string;
}

const db = () => getSupabase();

const querySchema = z.object({
	account_id: z.string().optional(),
	platform: zEnum(["threads", "instagram"]).optional(),
});

export default withAuth(
	async (
		req: VercelRequest,
		res: VercelResponse,
		user: { id: string; email?: string | undefined },
	) => {
		const userId = user.id;
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const parsed = querySchema.safeParse(req.query);
		if (!parsed.success) {
			return apiError(res, 400, "platform must be 'threads' or 'instagram'");
		}
		const { account_id: accountId, platform } = parsed.data;

		if (!accountId || accountId === "ALL") {
			return apiSuccess(res, { demographics: {} });
		}
		if (!platform) {
			return apiError(res, 400, "platform must be 'threads' or 'instagram'");
		}

		// Verify ownership
		if (platform === "threads") {
			const account = await verifyAccountOwnership(res, accountId, userId);
			if (!account) return;
		} else {
			const account = await verifyIgAccountOwnership(res, accountId, userId);
			if (!account) return;
		}

		const idColumn =
			platform === "instagram" ? "instagram_account_id" : "account_id";
		const query = db()
			.from("audience_demographics")
			.select("breakdown_type, breakdown_value, count, percentage, fetched_at")
			.eq(idColumn, accountId)
			.eq("platform", platform)
			.order("fetched_at", { ascending: false })
			.limit(200);
		const { data, error } = (await query) as unknown as {
			data: DemographicsRow[] | null;
			error: PostgrestError | null;
		};

		if (error) {
			return apiError(res, 500, "Failed to fetch demographics");
		}

		const grouped: Record<
			string,
			{ value: string; count: number; percentage: number }[]
		> = {};

		if (data && data.length > 0) {
			const latestDate = data[0]!.fetched_at;
			const latestDateStr = new Date(latestDate).toISOString().split("T")[0]!;

			for (const row of data) {
				const rowDate = new Date(row.fetched_at).toISOString().split("T")[0]!;
				if (rowDate !== latestDateStr) continue;

				if (!grouped[row.breakdown_type]) {
					grouped[row.breakdown_type] = [];
				}
				grouped[row.breakdown_type]!.push({
					value: row.breakdown_value,
					count: Number(row.count),
					percentage: Number(row.percentage || 0),
				});
			}

			for (const key of Object.keys(grouped)) {
				grouped[key]!.sort((a, b) => b.count - a.count);
			}
		}

		return apiSuccess(res, { demographics: grouped });
	},
);
