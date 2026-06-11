/**
 * Instagram Audio API Route
 * GET/POST /api/instagram/audio?action=search|metadata|replacements|media-audio-type
 *
 * Search/metadata/replacement discovery use Meta's /ig_audio endpoint and
 * require Facebook Login. media-audio-type reads the IG Media field
 * `media_audio_type`.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess, handleIgAuthError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

const AudioSearchSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	audioType: z.enum(["music", "original_sound"]).default("music"),
	query: z.string().trim().max(100).optional(),
	limit: z.coerce.number().int().min(1).max(50).optional(),
});

const AudioMetadataSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	igAudioId: z.string().min(1, "igAudioId is required"),
});

const AudioReplacementSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	igMediaId: z.string().min(1, "igMediaId is required"),
	audioReplacementMode: z.enum(["auto", "search", "default"]).default("search"),
	query: z.string().trim().max(100).optional(),
	limit: z.coerce.number().int().min(1).max(50).optional(),
});

const MediaAudioTypeSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	igMediaId: z.string().min(1, "igMediaId is required"),
});

type InstagramAudioAccount = {
	instagram_user_id: string;
	instagram_access_token_encrypted: string | null;
	login_type: string | null;
};

function requestData(req: VercelRequest): Record<string, unknown> {
	const queryData = Object.fromEntries(
		Object.entries(req.query).map(([key, value]) => [
			key,
			Array.isArray(value) ? value[0] : value,
		]),
	);
	const body =
		typeof req.body === "string"
			? JSON.parse(req.body || "{}")
			: req.body && typeof req.body === "object"
				? req.body
				: {};
	return { ...queryData, ...body };
}

async function getAudioAccount(accountId: string, userId: string) {
	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_user_id, instagram_access_token_encrypted, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		data: InstagramAudioAccount | null;
		error: { message: string } | null;
	};

	return { account, accountError };
}

async function requireAccount(
	res: VercelResponse,
	accountId: string,
	userId: string,
): Promise<InstagramAudioAccount | null> {
	const { account, accountError } = await getAudioAccount(accountId, userId);
	if (accountError || !account) {
		apiError(res, 404, "Instagram account not found");
		return null;
	}
	if (!account.instagram_access_token_encrypted) {
		apiError(res, 400, "Account token not available");
		return null;
	}
	return account;
}

async function handleSearch(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = AudioSearchSchema.safeParse(requestData(req));
	if (!parsed.success) {
		return apiError(
			res,
			400,
			parsed.error.issues[0]?.message || "Invalid input",
		);
	}
	const { accountId, audioType, query, limit } = parsed.data;
	const account = await requireAccount(res, accountId, userId);
	if (!account) return;

	const { searchInstagramAudio } = await import("../../instagramApi.js");
	const result = await searchInstagramAudio(
		account.instagram_access_token_encrypted ?? "",
		{ userId: account.instagram_user_id, audioType, query, limit },
		account.login_type || "facebook",
	);
	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Instagram audio search failed",
		);
	}
	return apiSuccess(res, { audio: result.audio || [], paging: result.paging });
}

async function handleMetadata(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = AudioMetadataSchema.safeParse(requestData(req));
	if (!parsed.success) {
		return apiError(
			res,
			400,
			parsed.error.issues[0]?.message || "Invalid input",
		);
	}
	const { accountId, igAudioId } = parsed.data;
	const account = await requireAccount(res, accountId, userId);
	if (!account) return;

	const { getInstagramAudioMetadata } = await import("../../instagramApi.js");
	const result = await getInstagramAudioMetadata(
		account.instagram_access_token_encrypted ?? "",
		igAudioId,
		account.login_type || "facebook",
	);
	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Instagram audio metadata failed",
		);
	}
	return apiSuccess(res, { audio: result.audio });
}

async function handleReplacements(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = AudioReplacementSchema.safeParse(requestData(req));
	if (!parsed.success) {
		return apiError(
			res,
			400,
			parsed.error.issues[0]?.message || "Invalid input",
		);
	}
	const { accountId, igMediaId, audioReplacementMode, query, limit } =
		parsed.data;
	const account = await requireAccount(res, accountId, userId);
	if (!account) return;

	const { discoverInstagramAudioReplacements } = await import(
		"../../instagramApi.js"
	);
	const result = await discoverInstagramAudioReplacements(
		account.instagram_access_token_encrypted ?? "",
		{
			userId: account.instagram_user_id,
			igMediaId,
			audioReplacementMode,
			query,
			limit,
		},
		account.login_type || "facebook",
	);
	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Instagram audio replacement discovery failed",
		);
	}
	return apiSuccess(res, { audio: result.audio || [], paging: result.paging });
}

async function handleMediaAudioType(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = MediaAudioTypeSchema.safeParse(requestData(req));
	if (!parsed.success) {
		return apiError(
			res,
			400,
			parsed.error.issues[0]?.message || "Invalid input",
		);
	}
	const { accountId, igMediaId } = parsed.data;
	const account = await requireAccount(res, accountId, userId);
	if (!account) return;

	const { getInstagramMediaAudioType } = await import("../../instagramApi.js");
	const result = await getInstagramMediaAudioType(
		account.instagram_access_token_encrypted ?? "",
		igMediaId,
		account.login_type || "facebook",
	);
	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Instagram media audio type failed",
		);
	}
	return apiSuccess(res, { mediaAudioType: result.mediaAudioType ?? null });
}

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET" && req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const action = req.query.action as string;

	try {
		switch (action) {
			case "search":
				return handleSearch(req, res, user.id);
			case "metadata":
				return handleMetadata(req, res, user.id);
			case "replacements":
				return handleReplacements(req, res, user.id);
			case "media-audio-type":
				return handleMediaAudioType(req, res, user.id);
			default:
				return apiError(
					res,
					400,
					"Invalid action. Use: search, metadata, replacements, media-audio-type",
				);
		}
	} catch (error: unknown) {
		logger.error("Instagram audio API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
