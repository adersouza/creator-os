import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import {
	type PreflightAccountStatus,
	runPublishPreflight,
} from "../../publishPreflight.js";
import { PublishPostSchema, parseBodyOrError } from "../../validation.js";
import {
	evaluateManualMediaReuse,
	withManualMediaReuseIssue,
} from "./manualMediaReuse.js";
import { db, resolveMediaUrls } from "./shared.js";

async function fetchPreflightAccount(
	userId: string,
	platform: "threads" | "instagram",
	accountId: string | null | undefined,
): Promise<PreflightAccountStatus> {
	if (!accountId) return { found: false };

	if (platform === "instagram") {
		const { data } = (await db()
			.from("instagram_accounts")
			.select(
				"id, instagram_user_id, instagram_access_token_encrypted, login_type, is_active, needs_reauth, status, token_expires_at, follower_count",
			)
			.eq("id", accountId)
			.eq("user_id", userId)
			.maybeSingle()) as {
			data:
				| {
						id: string;
						instagram_user_id?: string | null;
						instagram_access_token_encrypted?: string | null;
						login_type?: string | null;
						is_active?: boolean | null;
							needs_reauth?: boolean | null;
							status?: string | null;
							token_expires_at?: string | null;
							follower_count?: number | null;
					  }
					| null;
		};

		return {
			found: !!data,
			isActive: data?.is_active,
			needsReauth: data?.needs_reauth,
			status: data?.status,
			tokenExpiresAt: data?.token_expires_at,
				hasAccessToken: !!data?.instagram_access_token_encrypted,
				hasPlatformUserId: !!data?.instagram_user_id,
				loginType: data?.login_type,
				followerCount: data?.follower_count,
			};
	}

	const { data } = (await db()
		.from("accounts")
		.select(
			"id, threads_user_id, threads_access_token_encrypted, is_active, needs_reauth, status, token_expires_at",
		)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		data:
			| {
					id: string;
					threads_user_id?: string | null;
					threads_access_token_encrypted?: string | null;
					is_active?: boolean | null;
					needs_reauth?: boolean | null;
					status?: string | null;
					token_expires_at?: string | null;
			  }
			| null;
	};

	return {
		found: !!data,
		isActive: data?.is_active,
		needsReauth: data?.needs_reauth,
		status: data?.status,
		tokenExpiresAt: data?.token_expires_at,
		hasAccessToken: !!data?.threads_access_token_encrypted,
		hasPlatformUserId: !!data?.threads_user_id,
	};
}

export async function handlePreflight(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = parseBodyOrError(res, PublishPostSchema, req.body);
	if (!parsed) return;

	const platform = parsed.platform || "threads";
	let media = parsed.media;
	if (!media?.length && parsed.mediaIds?.length) {
		const { items } = await resolveMediaUrls(parsed.mediaIds, userId);
		media = items;
	}

	const targetAccountId =
		platform === "instagram" ? parsed.instagramAccountId : parsed.accountId;
	const account = await fetchPreflightAccount(userId, platform, targetAccountId);
	const baseResult = await runPublishPreflight(
		{
			...parsed,
			platform,
			mode:
				platform === "instagram" && parsed.publishMode === "notify"
					? "native-handoff"
					: "api",
			media,
		},
		{ account, checkMediaUrls: true },
	);
	const reuse = await evaluateManualMediaReuse({
		userId,
		platform,
		accountId: targetAccountId,
		content: parsed.content,
		media,
	});
	const result = withManualMediaReuseIssue(baseResult, reuse.issue);

	if (!result.ok) {
		return apiError(res, 422, "Publish preflight failed", {
			code: "PUBLISH_PREFLIGHT_FAILED",
			extra: { preflight: result },
		});
	}

	return apiSuccess(res, { ...result });
}
