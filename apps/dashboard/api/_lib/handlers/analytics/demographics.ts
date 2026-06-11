/**
 * Analytics Handler: demographics
 *
 * Fetch follower demographics (age, gender, city, country)
 * from Threads or Instagram API depending on account type.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Platform } from "../../platform.js";

interface BreakdownResultItem {
	dimension_values: string[];
	value: number;
}

interface NameCountItem {
	name: string;
	count: number;
}

import { apiError, apiSuccess } from "../../apiResponse.js";
import { detectAudienceShifts } from "../../audienceShiftDetector.js";
import { decrypt } from "../../encryption.js";
import { getInstagramDemographics } from "../../instagramApi.js";
import { logger } from "../../logger.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabase } from "../../supabase.js";
import { parseBodyOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

const db = () => getSupabase();

// ============================================================================
// Zod Schema
// ============================================================================

const DemographicsSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
});

// ============================================================================
// Handler
// ============================================================================

/**
 * POST /api/analytics?action=demographics
 * Fetch demographics breakdowns from Threads Graph API.
 */
export async function handleDemographics(
	req: VercelRequest,
	res: VercelResponse,
) {
	const parsed = parseBodyOrError(res, DemographicsSchema, req.body);
	if (!parsed) return;
	const { accountId } = parsed;

	const authHeader = req.headers.authorization;
	if (!authHeader?.startsWith("Bearer ")) {
		return apiError(res, 401, "Missing or invalid authorization header");
	}

	const authToken = authHeader.replace("Bearer ", "");
	const {
		data: { user },
		error: authError,
	} = await db().auth.getUser(authToken);

	if (authError || !user) {
		return apiError(res, 401, "Invalid or expired token");
	}

	const userId = user.id;

	// Initialize demographics objects
	const demographics: {
		age?: Record<string, number> | undefined;
		gender?: Record<string, number> | undefined;
		topCities?: Array<{ name: string; count: number }> | undefined;
		topCountries?: Array<{ name: string; count: number }> | undefined;
	} = {};

	const engagedDemographics: {
		age?: Record<string, number> | undefined;
		gender?: Record<string, number> | undefined;
		topCities?: Array<{ name: string; count: number }> | undefined;
		topCountries?: Array<{ name: string; count: number }> | undefined;
	} = {};

	let platform: Platform = "threads";

	// --- Try Threads account first ---
	const { data: threadsAccount } = await db()
		.from("accounts")
		.select(
			"id, threads_user_id, threads_access_token_encrypted, followers_count",
		)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle();

	// --- Try Instagram account if not a Threads account ---
	const { data: igAccount } = !threadsAccount
		? await db()
				.from("instagram_accounts")
				.select(
					"id, instagram_user_id, instagram_access_token_encrypted, login_type, follower_count",
				)
				.eq("id", accountId)
				.eq("user_id", userId)
				.maybeSingle()
		: { data: null };

	if (!threadsAccount && !igAccount) {
		return apiError(res, 404, "Account not found");
	}

	// ========================================================================
	// Early follower count check — skip API call if < 100 followers
	// ========================================================================
	const followerCount = threadsAccount
		? (threadsAccount.followers_count ?? 0)
		: (igAccount?.follower_count ?? 0);

	if (followerCount < 100) {
		return apiSuccess(res, {
			success: false,
			error: "INSUFFICIENT_FOLLOWERS",
			message: "At least 100 followers required for demographics data.",
			currentFollowers: followerCount,
			requiredFollowers: 100,
		});
	}

	// ========================================================================
	// Instagram demographics path
	// ========================================================================
	if (igAccount) {
		platform = "instagram";

		if (
			!igAccount.instagram_access_token_encrypted ||
			!igAccount.instagram_user_id
		) {
			return apiError(
				res,
				400,
				"Instagram account does not have OAuth credentials",
			);
		}

		const igResult = await getInstagramDemographics(
			igAccount.instagram_access_token_encrypted,
			igAccount.instagram_user_id,
			igAccount.login_type ?? undefined,
		);

		if (!igResult.success || !igResult.breakdowns?.length) {
			return apiSuccess(res, {
				success: false,
				error: "NO_DATA",
				message:
					igResult.error ||
					"No demographic data available. Requires a Business/Creator account with 100+ followers.",
			});
		}

		// Map IG breakdowns to our demographics shape
		for (const b of igResult.breakdowns) {
			if (b.breakdown_type === "age") {
				demographics.age = {};
				for (const v of b.values) demographics.age[v.value] = v.count;
			} else if (b.breakdown_type === "gender") {
				demographics.gender = {};
				for (const v of b.values) demographics.gender[v.value] = v.count;
			} else if (b.breakdown_type === "city") {
				demographics.topCities = b.values
					.map((v) => ({ name: v.value, count: v.count }))
					.sort((a, b) => b.count - a.count)
					.slice(0, 10);
			} else if (b.breakdown_type === "country") {
				demographics.topCountries = b.values
					.map((v) => ({ name: v.value, count: v.count }))
					.sort((a, b) => b.count - a.count)
					.slice(0, 10);
			}
		}

		// Map engaged audience demographics (optional — requires 100+ engagements)
		if (igResult.engagedBreakdowns?.length) {
			for (const b of igResult.engagedBreakdowns) {
				if (b.breakdown_type === "age") {
					engagedDemographics.age = {};
					for (const v of b.values) engagedDemographics.age[v.value] = v.count;
				} else if (b.breakdown_type === "gender") {
					engagedDemographics.gender = {};
					for (const v of b.values)
						engagedDemographics.gender[v.value] = v.count;
				} else if (b.breakdown_type === "city") {
					engagedDemographics.topCities = b.values
						.map((v) => ({ name: v.value, count: v.count }))
						.sort((a, b) => b.count - a.count)
						.slice(0, 10);
				} else if (b.breakdown_type === "country") {
					engagedDemographics.topCountries = b.values
						.map((v) => ({ name: v.value, count: v.count }))
						.sort((a, b) => b.count - a.count)
						.slice(0, 10);
				}
			}
		}
	}

	// ========================================================================
	// Threads demographics path
	// ========================================================================
	if (threadsAccount) {
		if (
			!threadsAccount.threads_access_token_encrypted ||
			!threadsAccount.threads_user_id
		) {
			return apiError(res, 400, "Account does not have OAuth credentials");
		}

		let token: string;
		try {
			token = decrypt(threadsAccount.threads_access_token_encrypted);
		} catch (decryptError: unknown) {
			logger.error("Token decryption failed", {
				error:
					decryptError instanceof Error
						? decryptError.message
						: String(decryptError),
			});
			return apiError(res, 500, "Failed to decrypt access token", {
				details:
					"The ENCRYPTION_KEY may not match. Users may need to reconnect their Threads account.",
			});
		}

		const threadsUserId = threadsAccount.threads_user_id;
		const breakdownTypes = ["age", "gender", "city", "country"] as const;

		for (const breakdownType of breakdownTypes) {
			try {
				const demographicsUrl = `https://graph.threads.net/v1.0/${threadsUserId}/threads_insights?metric=follower_demographics&breakdown=${breakdownType}`;
				const demographicsResponse = await withRetry(
					() =>
						fetch(demographicsUrl, {
							headers: { Authorization: `Bearer ${token}` },
							signal: AbortSignal.timeout(10000),
						}),
					{ label: `threadsDemographics:${threadsUserId}:${breakdownType}` },
				);
				const demographicsData = await demographicsResponse.json();

				if (!demographicsResponse.ok || demographicsData.error) {
					const errorMsg =
						demographicsData.error?.message || "Failed to fetch demographics";
					const errorCode = demographicsData.error?.code || "";

					logger.info("Demographics API error", {
						breakdownType,
						code: errorCode,
						message: errorMsg,
					});

					if (errorCode === 801) {
						return apiSuccess(res, {
							success: false,
							error: "PREREQUISITES_NOT_MET",
							message:
								"Demographics are not available for this account. Requirements: (1) At least 100 followers AND (2) A linked Instagram account.",
							currentFollowers: followerCount,
							requiredFollowers: 100,
						});
					}

					if (
						errorMsg.includes("followers") ||
						errorMsg.includes("minimum") ||
						errorMsg.includes("100")
					) {
						return apiSuccess(res, {
							success: false,
							error: "INSUFFICIENT_FOLLOWERS",
							message: "At least 100 followers required for demographics data.",
							currentFollowers: followerCount,
							requiredFollowers: 100,
						});
					}

					continue;
				}

				if (demographicsData.data?.[0]?.total_value?.breakdowns?.[0]?.results) {
					const results =
						demographicsData.data[0].total_value.breakdowns[0].results;

					if (breakdownType === "age") {
						demographics.age = {};
						for (const item of results)
							demographics.age[item.dimension_values[0]] = item.value;
					} else if (breakdownType === "gender") {
						demographics.gender = {};
						for (const item of results)
							demographics.gender[item.dimension_values[0]] = item.value;
					} else if (breakdownType === "city") {
						demographics.topCities = results
							.map((item: BreakdownResultItem) => ({
								name: item.dimension_values[0],
								count: item.value,
							}))
							.sort((a: NameCountItem, b: NameCountItem) => b.count - a.count)
							.slice(0, 10);
					} else if (breakdownType === "country") {
						demographics.topCountries = results
							.map((item: BreakdownResultItem) => ({
								name: item.dimension_values[0],
								count: item.value,
							}))
							.sort((a: NameCountItem, b: NameCountItem) => b.count - a.count)
							.slice(0, 10);
					}
				}
			} catch (_error) {
				logger.error("Error fetching demographics", { breakdownType });
			}
		}
	}

	// Check if we have any demographics data
	const hasData =
		demographics.age ||
		demographics.gender ||
		demographics.topCities ||
		demographics.topCountries;

	// Detect audience shifts (fire-and-forget)
	if (hasData && (demographics.age || demographics.gender)) {
		detectAudienceShifts(userId, accountId, platform, {
			age: demographics.age,
			gender: demographics.gender,
		}).catch((err) =>
			logger.error("Audience shift detection failed", { error: String(err) }),
		);
	}

	const hasEngagedData =
		engagedDemographics.age ||
		engagedDemographics.gender ||
		engagedDemographics.topCities ||
		engagedDemographics.topCountries;

	return apiSuccess(res, {
		success: !!hasData,
		demographics: hasData ? demographics : null,
		...(hasEngagedData && { engagedDemographics }),
		platform,
		message: hasData
			? undefined
			: "No demographic data available for this account yet.",
	});
}
