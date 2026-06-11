/**
 * Handlers: POST /api/competitors?action=ig-search | ig-business-discovery
 *
 * Search for an Instagram profile using business discovery.
 */

import { apiError, apiSuccess } from "../../../apiResponse.js";
import { CompetitorIgSearchSchema } from "../../../validation.js";
import { withAuthAndBody } from "../../helpers/withAuthAndBody.js";
import { getIgAccount } from "../shared.js";

interface IgProfile {
	username: string;
	name?: string | undefined;
	biography?: string | undefined;
	followers_count?: number | undefined;
	media_count?: number | undefined;
	profile_picture_url?: string | undefined;
	website?: string | undefined;
}

export const handleIgSearch = withAuthAndBody(
	CompetitorIgSearchSchema,
	async (user, parsed, _req, res) => {
		const { accountId, targetUsername } = parsed;

		const account = await getIgAccount(user.id, accountId);
		if (!account) return apiError(res, 404, "Instagram account not found");

		// Business Discovery requires Facebook Login (uses business_discovery field on graph API)
		if (account.login_type === "instagram") {
			return apiError(
				res,
				400,
				"This feature requires connecting your Instagram account via Facebook Login. Go to Settings to connect.",
			);
		}

		const { getBusinessDiscovery } = await import("../../../instagramApi.js");
		const result = await getBusinessDiscovery(
			account.instagram_access_token_encrypted as string,
			account.instagram_user_id as string,
			targetUsername.replace(/^@/, "").trim(),
			6,
		);

		if (!result.success) {
			return apiError(res, 404, result.error || "Profile not found");
		}

		const profile = result.profile as unknown as IgProfile;
		return apiSuccess(res, {
			profile: {
				username: profile.username,
				name: profile.name,
				biography: profile.biography,
				profilePictureUrl: profile.profile_picture_url,
				followersCount: profile.followers_count,
				mediaCount: profile.media_count,
				website: profile.website,
			},
		});
	},
);

/** Legacy handler kept for backward compatibility */
export const handleIgBusinessDiscovery = withAuthAndBody(
	CompetitorIgSearchSchema,
	async (user, parsed, _req, res) => {
		const { accountId, targetUsername } = parsed;

		// Look up IG account
		interface IgAccountRecord {
			instagram_access_token_encrypted: string | null;
			instagram_user_id: string | null;
			login_type: string | null;
		}
		const { data: account, error: accountError } = (await (
			await import("../shared.js")
		)
			.db()
			.from("instagram_accounts")
			.select("instagram_access_token_encrypted, instagram_user_id, login_type")
			.eq("id", accountId)
			.eq("user_id", user.id)
			.maybeSingle()) as { data: IgAccountRecord | null; error: unknown };

		if (accountError || !account) {
			return apiError(res, 404, "Instagram account not found");
		}

		if (!account.instagram_access_token_encrypted) {
			return apiError(res, 400, "Account token not available");
		}

		// Business Discovery requires Facebook Login
		if (account.login_type === "instagram") {
			return apiError(
				res,
				400,
				"This feature requires connecting your Instagram account via Facebook Login. Go to Settings to connect.",
			);
		}

		const { getBusinessDiscovery } = await import("../../../instagramApi.js");

		const result = await getBusinessDiscovery(
			account.instagram_access_token_encrypted as string,
			account.instagram_user_id as string,
			targetUsername,
		);

		if (!result.success) {
			return apiError(res, 500, result.error || "Business discovery failed");
		}

		return apiSuccess(res, { profile: result.profile });
	},
);
