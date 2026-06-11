/**
 * Growth Journal Handler
 * GET /api/growth-journal?accountId=...&platform=...
 * POST /api/growth-journal (body: { accountId, recommendationText, ... })
 * DELETE /api/growth-journal?id=...
 * Merged from api/growth-journal.ts
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Database } from "../../../../types/supabase.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { requireMinTier } from "../../tierGate.js";
import { parseQueryOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

type ApiUser = DbContext["user"];
type UserDb = DbContext["userDb"];
type RecommendationDismissalInsert =
	Database["public"]["Tables"]["recommendation_dismissals"]["Insert"] & {
		post_id?: string | undefined;
	};

const GetJournalQuerySchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	platform: z.string().optional(),
	category: z.string().optional(),
	search: z.string().optional(),
});

const DeleteJournalQuerySchema = z.object({
	id: z.string().min(1, "id is required"),
});

export const GrowthJournalCreateSchema = z.object({
	accountId: z.string().min(1).max(200),
	platform: z.string().max(50).optional(),
	category: z.string().max(100).optional(),
	recommendationText: z.string().min(1).max(2000),
	icon: z.string().max(50).optional(),
	postId: z.string().max(200).optional(),
});

interface DismissalRow {
	id?: string | undefined;
	rec_id: string;
	actioned_at?: string | undefined;
	created_at?: string | undefined;
	recommendation_text?: string | undefined;
	title?: string | undefined;
	category?: string | undefined;
	baseline_value?: number | null | undefined;
	current_value?: number | null | undefined;
	icon?: string | undefined;
	post_id?: string | null | undefined;
	[key: string]: unknown;
}

interface BaselineRow {
	rec_id: string;
	baseline_value?: number | null | undefined;
	threshold?: number | null | undefined;
	category?: string | undefined;
	icon?: string | undefined;
	[key: string]: unknown;
}

interface JournalEntry {
	id: string | undefined;
	recId: string;
	actionedAt: string | undefined;
	recommendationText: string;
	category: string;
	beforeValue: number | null;
	afterValue: number | null;
	improvementPct: number;
	outcome: "improved" | "flat" | "declined";
	icon: string;
	postId: string | null | undefined;
}

async function handler(
	req: VercelRequest,
	res: VercelResponse,
	context: DbContext,
) {
	const { user, userDb } = context;
	const allowed = await requireMinTier(user.id, "pro", res);
	if (!allowed) return;

	if (req.method === "POST") {
		return handlePost(req, res, user, userDb);
	}

	if (req.method === "DELETE") {
		return handleDelete(req, res, user, userDb);
	}

	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const parsed = parseQueryOrError(res, GetJournalQuerySchema, req.query);
	if (!parsed) return;
	const { accountId, category, search } = parsed;
	const platform = parsed.platform || "threads";

	try {
		let dismissalQuery = userDb
			.from("recommendation_dismissals")
			.select("*")
			.eq("user_id", user.id)
			.eq("account_id", accountId)
			.eq("action", "actioned")
			.order("actioned_at", { ascending: false });

		if (category) {
			dismissalQuery = dismissalQuery.eq("category", category);
		}

		if (search) {
			const sanitizedSearch = search.replace(/[%_\\]/g, "");
			if (sanitizedSearch) {
				dismissalQuery = dismissalQuery.ilike(
					"recommendation_text",
					`%${sanitizedSearch}%`,
				);
			}
		}

		const { data: dismissals, error: dismissalError } = await dismissalQuery;

		if (dismissalError) {
			logger.error("[growth-journal] Failed to fetch dismissals", {
				error: String(dismissalError),
				userId: user.id,
			});
			return apiSuccess(res, {
				entries: [],
				stats: { total: 0, successful: 0, successRate: 0, avgImprovement: 0 },
			});
		}

		const { data: baselines } = await userDb
			.from("recommendation_baselines")
			.select("*")
			.eq("account_id", accountId)
			.eq("platform", platform);

		const baselineMap = new Map<string, BaselineRow>();
		if (baselines) {
			for (const b of baselines as BaselineRow[]) {
				baselineMap.set(b.rec_id, b);
			}
		}

		const entries = ((dismissals as unknown as DismissalRow[]) || []).map(
			(d) => {
				const baseline = baselineMap.get(d.rec_id);
				const beforeValue =
					baseline?.baseline_value ?? d.baseline_value ?? null;
				const afterValue = baseline?.threshold ?? d.current_value ?? null;
				let outcome: "improved" | "flat" | "declined" = "flat";
				let improvementPct = 0;

				if (beforeValue != null && afterValue != null && beforeValue > 0) {
					improvementPct = Math.round(
						((afterValue - beforeValue) / beforeValue) * 100,
					);
					if (improvementPct > 10) outcome = "improved";
					else if (improvementPct < -10) outcome = "declined";
				}

				return {
					id: d.id || d.rec_id,
					recId: d.rec_id,
					actionedAt: d.actioned_at || d.created_at,
					recommendationText:
						d.recommendation_text || d.title || "Optimization applied",
					category: d.category || baseline?.category || "content",
					beforeValue,
					afterValue,
					improvementPct,
					outcome,
					icon: d.icon || baseline?.icon || "🎯",
					postId: d.post_id || null,
				};
			},
		);

		const total = entries.length;
		const successful = entries.filter(
			(e: JournalEntry) => e.outcome === "improved",
		).length;
		const successRate = total > 0 ? Math.round((successful / total) * 100) : 0;
		const improvements = entries
			.filter((e: JournalEntry) => e.improvementPct > 0)
			.map((e: JournalEntry) => e.improvementPct);
		const avgImprovement =
			improvements.length > 0
				? Math.round(
						improvements.reduce((a: number, b: number) => a + b, 0) /
							improvements.length,
					)
				: 0;

		return apiSuccess(res, {
			entries,
			stats: { total, successful, successRate, avgImprovement },
		});
	} catch (err) {
		logger.error("[growth-journal] Unhandled error", { error: String(err) });
		return apiError(res, 500, "Internal server error");
	}
}

async function handlePost(
	req: VercelRequest,
	res: VercelResponse,
	user: ApiUser,
	userDb: UserDb,
) {
	const parsed = GrowthJournalCreateSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { accountId, platform, category, recommendationText, icon, postId } =
		parsed.data;

	try {
		const accountTable =
			(platform || "threads") === "instagram"
				? "instagram_accounts"
				: "accounts";
		const { data: ownedAccount } = await userDb
			.from(accountTable)
			.select("id")
			.eq("id", accountId)
			.eq("user_id", user.id)
			.maybeSingle();

		if (!ownedAccount) {
			return apiError(res, 404, "Account not found");
		}

		if (postId) {
			const { data: ownedPost } = await userDb
				.from("posts")
				.select("id")
				.eq("id", postId)
				.eq("user_id", user.id)
				.maybeSingle();

			if (!ownedPost) {
				return apiError(res, 404, "Post not found");
			}
		}

		const insertData: RecommendationDismissalInsert = {
			user_id: user.id,
			account_id: accountId,
			platform: platform || "threads",
			rec_id: `milestone-${Date.now()}`,
			action: "actioned",
			category: category || "milestone",
			recommendation_text: recommendationText,
			icon: icon || "🏆",
			actioned_at: new Date().toISOString(),
		};

		if (postId) {
			insertData.post_id = postId;
		}

		const { error } = await userDb
			.from("recommendation_dismissals")
			.insert(
				insertData as Database["public"]["Tables"]["recommendation_dismissals"]["Insert"],
			);

		if (error) {
			logger.error("[growth-journal] POST insert failed", {
				error: String(error),
			});
			return apiError(res, 500, "Failed to create journal entry");
		}

		return apiSuccess(res, { created: true });
	} catch (err) {
		logger.error("[growth-journal] POST error", { error: String(err) });
		return apiError(res, 500, "Internal server error");
	}
}

async function handleDelete(
	req: VercelRequest,
	res: VercelResponse,
	user: ApiUser,
	userDb: UserDb,
) {
	const parsed = parseQueryOrError(res, DeleteJournalQuerySchema, req.query);
	if (!parsed) return;
	const { id } = parsed;

	try {
		const { data, error } = await userDb
			.from("recommendation_dismissals")
			.delete()
			.eq("id", id)
			.eq("user_id", user.id)
			.select("id")
			.maybeSingle();

		if (error) {
			logger.error("[growth-journal] DELETE failed", {
				error: String(error),
				userId: user.id,
			});
			return apiError(res, 500, "Failed to delete journal entry");
		}
		if (!data) return apiError(res, 404, "Journal entry not found");

		return apiSuccess(res, { deleted: true });
	} catch (err) {
		logger.error("[growth-journal] DELETE error", { error: String(err) });
		return apiError(res, 500, "Internal server error");
	}
}

export default withAuthDb(handler);
