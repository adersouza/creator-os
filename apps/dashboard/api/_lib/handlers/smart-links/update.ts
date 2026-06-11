// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Update an existing smart link.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { validatePublicRedirectUrl } from "../../outboundUrlSecurity.js";
import { getSupabaseAny } from "../../supabase.js";
import {
	db,
	getAlternateRedirectErrors,
	getCloakingWarnings,
	isReservedSmartLinkCode,
	UpdateSchema,
} from "./shared.js";

export async function handleUpdate(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = UpdateSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const alternateRedirectErrors = getAlternateRedirectErrors(parsed.data);
	if (alternateRedirectErrors.length > 0) {
		return apiError(res, 400, alternateRedirectErrors[0]!);
	}

	if (parsed.data.target_url) {
		const targetError = await validatePublicRedirectUrl(
			parsed.data.target_url,
			"smart-link-update",
		);
		if (targetError) {
			return apiError(res, 400, "Target URL is not allowed");
		}
	}

	const { id, ...updates } = parsed.data;

	// Verify ownership
	const { data: existing } = await db()
		.from("smart_links")
		.select("id")
		.eq("id", id)
		.eq("user_id", userId)
		.maybeSingle();

	if (!existing) return apiError(res, 404, "Smart link not found");

	// Validate post_id ownership if being updated
	if (updates.post_id) {
		const { data: ownedPost } = await db()
			.from("posts")
			.select("id")
			.eq("id", updates.post_id)
			.eq("user_id", userId)
			.maybeSingle();
		if (!ownedPost) {
			return apiError(res, 403, "Post not found or not owned by you");
		}
	}

	// If updating code, check uniqueness
	if (updates.code) {
		const normalizedCode = updates.code.toLowerCase();
		if (isReservedSmartLinkCode(normalizedCode)) {
			return apiError(res, 400, "Code is reserved");
		}
		const { data: codeTaken } = await db()
			.from("smart_links")
			.select("id")
			.eq("code", normalizedCode)
			.neq("id", id)
			.maybeSingle();
		if (codeTaken) return apiError(res, 409, "Code already taken");
		updates.code = normalizedCode;
	}

	// Clean empty string URLs to null
	const cleanUpdates: Record<string, unknown> = {
		...updates,
		updated_at: new Date().toISOString(),
	};
	for (const key of [
		"ig_redirect_url",
		"threads_redirect_url",
		"mobile_redirect_url",
		"ig_deep_link",
		"threads_deep_link",
	]) {
		if (cleanUpdates[key] === "") cleanUpdates[key] = null;
	}
	delete cleanUpdates.ig_redirect_url;
	delete cleanUpdates.threads_redirect_url;
	delete cleanUpdates.mobile_redirect_url;

	const { data, error } = await getSupabaseAny()
		.from("smart_links")
		.update(cleanUpdates)
		.eq("id", id)
		.eq("user_id", userId)
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[smart-links] Update error", { error: String(error) });
		return apiError(res, 500, "Failed to update smart link");
	}

	// Invalidate Redis cache
	try {
		const { invalidateCache } = await import("../../redisCache.js");
		await invalidateCache(
			`smartlink:${(data as Record<string, unknown>)?.code}`,
		);
	} catch {
		/* Redis optional */
	}

	const warnings = getCloakingWarnings(
		updates as Parameters<typeof getCloakingWarnings>[0],
	);
	return apiSuccess(res, {
		link: data,
		...(warnings.length > 0 ? { warnings } : {}),
	});
}
