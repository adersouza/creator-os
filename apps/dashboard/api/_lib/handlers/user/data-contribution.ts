/**
 * GET/POST /api/user?action=data-contribution
 *
 * Toggles the user's anonymized cohort-sharing preference and, when enabling,
 * stamps the chosen niche onto every account owned by the caller (Threads +
 * Instagram). The niche is the self-declared axis for the follower-band × niche
 * cohort lattice; it is the authoritative source, with AI-inferred niche as a
 * fallback handled downstream in the aggregation job.
 *
 * Body: { opted_in: boolean; niche?: CanonicalNiche | null }
 *  - opted_in=true requires niche (validated against CANONICAL_NICHES).
 *  - opted_in=false accepts niche omitted or explicit null; niche columns are
 *    left untouched so the user can flip back on without re-picking.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { isCanonicalNiche } from "../../cohorts/niches.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";

type UserDb = DbContext["userDb"];

export default withAuthDb(async (req, res, context) => {
	const { user, userDb } = context;
	if (req.method === "GET") {
		try {
			const [prefResp, threadsResp, igResp] = await Promise.all([
				userDb
					.from("user_preferences")
					.select("data_contribution_opted_in")
					.eq("user_id", user.id)
					.maybeSingle(),
				userDb
					.from("accounts")
					.select("user_niche")
					.eq("user_id", user.id)
					.not("user_niche", "is", null)
					.limit(1)
					.maybeSingle(),
				userDb
					.from("instagram_accounts")
					.select("user_niche")
					.eq("user_id", user.id)
					.not("user_niche", "is", null)
					.limit(1)
					.maybeSingle(),
			]);

			if (prefResp.error) {
				logger.warn("[data-contribution] Preference lookup failed", {
					userId: user.id.slice(0, 8),
					error: prefResp.error.message,
				});
			}
			if (threadsResp.error) {
				logger.warn("[data-contribution] Threads niche lookup failed", {
					userId: user.id.slice(0, 8),
					error: threadsResp.error.message,
				});
			}
			if (igResp.error) {
				logger.warn("[data-contribution] Instagram niche lookup failed", {
					userId: user.id.slice(0, 8),
					error: igResp.error.message,
				});
			}

			const threadsNiche = (threadsResp.data as { user_niche?: unknown | undefined } | null)
				?.user_niche;
			const igNiche = (igResp.data as { user_niche?: unknown | undefined } | null)?.user_niche;
			const rawNiche = threadsNiche ?? igNiche ?? null;

			return apiSuccess(res, {
				opted_in: prefResp.data?.data_contribution_opted_in === true,
				niche: isCanonicalNiche(rawNiche) ? rawNiche : null,
			});
		} catch (error) {
			logger.error("[data-contribution] GET failed", { error: String(error) });
			return apiSuccess(res, { opted_in: false, niche: null });
		}
	}

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const { opted_in, niche } = req.body ?? {};

	if (typeof opted_in !== "boolean") {
		return apiError(res, 400, "opted_in must be a boolean");
	}

	if (opted_in && !isCanonicalNiche(niche)) {
		return apiError(
			res,
			400,
			"niche is required when opting in and must be one of the canonical niches",
		);
	}

	try {
		const { error: prefError } = await userDb.from("user_preferences").upsert(
			{
				user_id: user.id,
				data_contribution_opted_in: opted_in,
				updated_at: new Date().toISOString(),
			},
			{ onConflict: "user_id" },
		);

		if (prefError) {
			logger.error("[data-contribution] Preference upsert failed", {
				userId: user.id,
				error: String(prefError),
			});
			return apiError(res, 500, "Failed to update preference");
		}

		if (opted_in && isCanonicalNiche(niche)) {
			const [threadsResult, igResult] = await Promise.all([
				updateAccountNiche(userDb, "accounts", user.id, niche),
				updateAccountNiche(userDb, "instagram_accounts", user.id, niche),
			]);

			if (threadsResult.error || igResult.error) {
				logger.warn("[data-contribution] Niche fan-out partial failure", {
					userId: user.id.slice(0, 8),
					threadsError: threadsResult.error
						? String(threadsResult.error)
						: null,
					igError: igResult.error ? String(igResult.error) : null,
				});
			}
		}

		logger.info("[data-contribution] Preference updated", {
			userId: user.id.slice(0, 8),
			opted_in,
			niche: opted_in ? niche : null,
		});

		return apiSuccess(res, {
			opted_in,
			niche: opted_in ? niche : null,
		});
	} catch (error) {
		logger.error("[data-contribution] Unhandled error", {
			error: String(error),
		});
		return apiError(res, 500, "Internal server error");
	}
});

function updateAccountNiche(
	userDb: UserDb,
	table: "accounts" | "instagram_accounts",
	userId: string,
	niche: string,
) {
	return userDb
		.from(table)
		.update({ user_niche: niche })
		.eq("user_id", userId);
}
