/**
 * Agent Content Strategy
 *
 * GET   /api/agent/content-strategy?accountGroupId=X  — get strategy for one group
 * GET   /api/agent/content-strategy                   — get all groups + strategies for user
 * PATCH /api/agent/content-strategy                   — upsert strategy (body: { accountGroupId, strategy })
 *
 * Strategy schema:
 * {
 *   pillars: string[]          // 3-5 content themes
 *   weekly_target: number      // posts per week for this group
 *   tone_notes: string         // overrides / additions to voice_profile
 *   topics_to_avoid: string[]  // brand safety
 *   cta_rotation: string[]     // CTAs to cycle through
 *   peak_windows: { day: string; hour: number }[]  // preferred posting times
 * }
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { withAuthDb } from "../../middleware.js";
import { z } from "../../zodCompat.js";

const StrategyObjectSchema = z.object({
	pillars: z.array(z.string().max(200)).min(1).max(10).optional(),
	weekly_target: z.number().int().min(0).max(100).optional(),
	tone_notes: z.string().max(2000).optional(),
	topics_to_avoid: z.array(z.string().max(200)).max(20).optional(),
	cta_rotation: z.array(z.string().max(500)).max(20).optional(),
	peak_windows: z
		.array(
			z.object({
				day: z.string().max(20),
				hour: z.number().int().min(0).max(23),
			}),
		)
		.max(21)
		.optional(),
});

export const ContentStrategySchema = z.object({
	accountGroupId: z.string().min(1).max(200),
	strategy: StrategyObjectSchema,
});

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context: DbContext) => {
		const { user, userDb } = context;
		// ── GET ──────────────────────────────────────────────────────────────────
		if (req.method === "GET") {
			const rawAccountGroupId = req.query.accountGroupId;
			const accountGroupId = Array.isArray(rawAccountGroupId)
				? rawAccountGroupId[0]
				: rawAccountGroupId;

			// Single group
			if (accountGroupId) {
				const { data, error } = await userDb
					.from("account_groups")
					.select("id, name, account_ids, voice_profile, content_strategy")
					.eq("id", accountGroupId)
					.eq("user_id", user.id)
					.maybeSingle();

				if (error)
					return apiError(res, 500, "Failed to fetch content strategy");
				if (!data) return apiError(res, 404, "Account group not found");

				return apiSuccess(res, {
					accountGroupId: data.id,
					name: data.name,
					accountIds: data.account_ids ?? [],
					voiceProfile: data.voice_profile ?? null,
					strategy: data.content_strategy ?? null,
				});
			}

			// All groups for user
			const { data, error } = await userDb
				.from("account_groups")
				.select("id, name, account_ids, voice_profile, content_strategy")
				.eq("user_id", user.id)
				.order("name", { ascending: true });

			if (error)
				return apiError(res, 500, "Failed to fetch content strategies");

			const groups = (data ?? []).map(
				(g: {
					id: string;
					name: string;
					account_ids: string[] | null;
					voice_profile: unknown;
					content_strategy: unknown;
				}) => ({
					accountGroupId: g.id,
					name: g.name,
					accountIds: g.account_ids ?? [],
					voiceProfile: g.voice_profile ?? null,
					strategy: g.content_strategy ?? null,
				}),
			);

			return apiSuccess(res, { groups, total: groups.length });
		}

		// ── PATCH ─────────────────────────────────────────────────────────────────
		if (req.method === "PATCH") {
			const parsed = ContentStrategySchema.safeParse(req.body);
			if (!parsed.success) {
				return apiError(
					res,
					400,
					`Invalid input: ${parsed.error.issues[0]?.message}`,
				);
			}

			const { accountGroupId, strategy } = parsed.data;

			// Validate ownership and fetch existing strategy for merge
			const { data: existing, error: fetchErr } = await userDb
				.from("account_groups")
				.select("id, content_strategy")
				.eq("id", accountGroupId)
				.eq("user_id", user.id)
				.maybeSingle();

			if (fetchErr) return apiError(res, 500, "Failed to verify ownership");
			if (!existing) return apiError(res, 404, "Account group not found");

			// Merge with existing strategy to avoid wiping fields not included in this call
			const existingStrategy =
				(existing.content_strategy as Record<string, unknown>) || {};
			const merged = { ...existingStrategy, ...strategy };

			const { error } = await userDb
				.from("account_groups")
				.update({
					content_strategy: merged,
					updated_at: new Date().toISOString(),
				})
				.eq("id", accountGroupId)
				.eq("user_id", user.id);

			if (error) return apiError(res, 500, "Failed to save content strategy");

			return apiSuccess(res, { accountGroupId, strategy: merged });
		}

		return apiError(res, 405, "Method not allowed");
	},
);
