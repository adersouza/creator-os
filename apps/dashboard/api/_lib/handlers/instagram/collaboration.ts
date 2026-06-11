/**
 * Instagram Collaboration API Route
 * POST /api/instagram/collaboration?action=list|accept|decline
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, handleIgAuthError } from "../../apiResponse.js";

interface IGAccountRow {
	instagram_access_token_encrypted: string;
	instagram_user_id: string;
	login_type: string;
}

import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";
import { z } from "../../zodCompat.js";

async function getIGAccount(userId: string, accountId: string) {
	const { data: account, error } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		data: IGAccountRow | null;
		error: { message: string } | null;
	};

	if (error || !account) {
		return {
			account: null as IGAccountRow | null,
			error: "Instagram account not found",
		};
	}

	if (!account.instagram_access_token_encrypted) {
		return {
			account: null as IGAccountRow | null,
			error: "Account token not available",
		};
	}

	return { account, error: null };
}

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const ListSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
});

const AcceptDeclineSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	mediaId: z.string().min(1, "mediaId is required"),
});

async function handleList(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = ListSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId } = parsed.data;

	const { account, error: accError } = await getIGAccount(userId, accountId);
	if (accError || !account) {
		return apiError(res, 404, accError || "Account not found");
	}

	const loginType = account.login_type || "facebook";

	// Collaboration invites are only available with Facebook Login
	if (loginType === "instagram") {
		return apiError(
			res,
			400,
			"This feature requires connecting your Instagram account via Facebook Login. Go to Settings to connect.",
		);
	}

	logger.info("[IG Collaboration] Fetching invites", { accountId, loginType });

	// #522: Cache collaboration invite status in Redis (5-min TTL) to avoid redundant API calls
	const cacheKey = `ig-collab-invites:${accountId}`;
	try {
		const { cached } = await import("../../redisCache.js");
		const cachedResult = await cached(
			cacheKey,
			300, // 5 minutes TTL
			async () => {
				const { getCollaborationInvites } = await import(
					"../../instagramApi.js"
				);
				const result = await getCollaborationInvites(
					account.instagram_access_token_encrypted,
					account.instagram_user_id,
					loginType,
				);
				return result;
			},
		);

		if (!cachedResult.success) {
			return await handleIgAuthError(
				res,
				accountId,
				userId,
				cachedResult.error || "Unknown error",
			);
		}

		// Cache invites in DB for local-first display
		if ((cachedResult.invites?.length ?? 0) > 0) {
			try {
				// biome-ignore lint/suspicious/noExplicitAny: Vercel TS 5.9 — API response shape wider than IGCollaborationInvite
				const rows = (cachedResult.invites || []).map((inv: any) => ({
					id: inv.id,
					user_id: userId,
					account_id: accountId,
					caption: inv.caption || null,
					media_type: inv.media_type || null,
					media_url: inv.media_url || null,
					permalink: inv.permalink || null,
					owner_id: inv.owner?.id || null,
					owner_username: inv.owner?.username || null,
					status: "pending",
					discovered_at: new Date().toISOString(),
				}));
				// biome-ignore lint/suspicious/noExplicitAny: ig_collab_invites not in generated types yet
				await (getSupabase() as any)
					.from("ig_collab_invites")
					.upsert(rows, { onConflict: "id" });
			} catch (err) {
				logger.debug("[IG Collaboration] DB upsert failed (non-blocking)", {
					error: String(err),
				});
			}
		}

		return apiSuccess(res, { invites: cachedResult.invites });
	} catch {
		// Redis unavailable — fall through to direct API call
		const { getCollaborationInvites } = await import("../../instagramApi.js");
		const result = await getCollaborationInvites(
			account.instagram_access_token_encrypted,
			account.instagram_user_id,
			loginType,
		);

		if (!result.success) {
			return await handleIgAuthError(
				res,
				accountId,
				userId,
				result.error || "Unknown error",
			);
		}

		return apiSuccess(res, { invites: result.invites });
	}
}

async function handleAccept(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = AcceptDeclineSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, mediaId } = parsed.data;

	const { account, error: accError } = await getIGAccount(userId, accountId);
	if (accError || !account) {
		return apiError(res, 404, accError || "Account not found");
	}

	const loginType = account.login_type || "facebook";

	if (loginType === "instagram") {
		return apiError(
			res,
			400,
			"This feature requires connecting your Instagram account via Facebook Login. Go to Settings to connect.",
		);
	}

	logger.info("[IG Collaboration] Accepting collaboration", {
		mediaId,
		loginType,
	});

	const { acceptCollaboration } = await import("../../instagramApi.js");

	const result = await acceptCollaboration(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		mediaId,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	// Update DB cache status
	try {
		// biome-ignore lint/suspicious/noExplicitAny: ig_collab_invites not in generated types yet
		await (getSupabase() as any)
			.from("ig_collab_invites")
			.update({ status: "accepted", resolved_at: new Date().toISOString() })
			.eq("id", mediaId)
			.eq("user_id", userId)
			.eq("account_id", accountId);
	} catch (err) {
		logger.debug("[IG Collaboration] DB status update failed (non-blocking)", {
			error: String(err),
		});
	}

	return apiSuccess(res);
}

async function handleDecline(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = AcceptDeclineSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, mediaId } = parsed.data;

	const { account, error: accError } = await getIGAccount(userId, accountId);
	if (accError || !account) {
		return apiError(res, 404, accError || "Account not found");
	}

	const loginType = account.login_type || "facebook";

	if (loginType === "instagram") {
		return apiError(
			res,
			400,
			"This feature requires connecting your Instagram account via Facebook Login. Go to Settings to connect.",
		);
	}

	logger.info("[IG Collaboration] Declining collaboration", {
		mediaId,
		loginType,
	});

	const { declineCollaboration } = await import("../../instagramApi.js");

	const result = await declineCollaboration(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		mediaId,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	// Update DB cache status
	try {
		// biome-ignore lint/suspicious/noExplicitAny: ig_collab_invites not in generated types yet
		await (getSupabase() as any)
			.from("ig_collab_invites")
			.update({ status: "declined", resolved_at: new Date().toISOString() })
			.eq("id", mediaId)
			.eq("user_id", userId)
			.eq("account_id", accountId);
	} catch (err) {
		logger.debug("[IG Collaboration] DB status update failed (non-blocking)", {
			error: String(err),
		});
	}

	return apiSuccess(res);
}

export default withAuth(async (req, res, user) => {
	const userId = user.id;

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	// Tier gate: pro tier required for collaboration management
	if (!(await requireMinTier(userId, "pro", res))) return;

	const action = req.query.action as string;

	try {
		switch (action) {
			case "list":
				return handleList(req, res, userId);
			case "accept":
				return handleAccept(req, res, userId);
			case "decline":
				return handleDecline(req, res, userId);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Instagram collaboration API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
