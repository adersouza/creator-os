import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { validatePublicRedirectUrl } from "../../outboundUrlSecurity.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
import {
	getUserTier,
	isSafeDeepLinkUrl,
	isSafeUrl,
	LINK_LIMITS,
	syncWithRetry,
	UpdateLinkSchema,
} from "./shared.js";

export async function handleUpdateLink(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const supabase = getSupabase();
	const parsed = UpdateLinkSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { linkId, ...updates } = parsed.data;

	// Verify ownership
	const { data: link } = await supabase
		.from("link_items")
		.select("page_id")
		.eq("id", linkId)
		.maybeSingle();

	if (!link) return apiError(res, 404, "Link not found");
	if (!link.page_id) return apiError(res, 500, "Link missing page reference");

	const { data: page } = await supabase
		.from("link_pages")
		.select("id")
		.eq("id", link.page_id)
		.eq("user_id", userId)
		.maybeSingle();

	if (!page) return apiError(res, 403, "Not authorized");

	// Block dangerous URL schemes on update
	if (updates.url && !isSafeUrl(updates.url)) {
		return apiError(res, 400, "Only http:// and https:// URLs are allowed");
	}
	if (
		updates.url &&
		(await validatePublicRedirectUrl(updates.url, "link-item-update"))
	) {
		return apiError(res, 400, "URL is not allowed");
	}

	// Check plan limits for tier-gated features
	const tier = await getUserTier(userId);
	const limits = LINK_LIMITS[tier];

	const updateData: Record<string, unknown> = {};
	if (updates.title !== undefined) updateData.title = updates.title;
	if (updates.url !== undefined) updateData.url = updates.url;
	if (updates.icon !== undefined) updateData.icon = updates.icon;
	if (updates.isVisible !== undefined)
		updateData.is_visible = updates.isVisible;
	if (updates.isPrimary !== undefined)
		updateData.is_primary = updates.isPrimary;
	if (updates.platform !== undefined) updateData.platform = updates.platform;
	if (updates.deepLinkUrl !== undefined) {
		if (updates.deepLinkUrl && !isSafeDeepLinkUrl(updates.deepLinkUrl)) {
			return apiError(res, 400, "Deep link URL scheme not allowed");
		}
		updateData.deep_link_url = updates.deepLinkUrl;
	}

	// Gate per-link styling by tier (silently strip if not allowed)
	if (limits.perLinkStyling && updates.style !== undefined) {
		updateData.style = {
			bg_color: updates.style.bgColor || null,
			text_color: updates.style.textColor || null,
			border_radius: updates.style.borderRadius ?? null,
			animation: updates.style.animation || null,
			image_url: updates.style.imageUrl || null,
			image_mode: updates.style.imageMode || null,
		};
	}

	// Gate deep link config by tier (silently strip if not allowed)
	if (limits.deeplinkEscape && updates.deepLinkConfig !== undefined) {
		const ios = updates.deepLinkConfig.iosDeepLink;
		const android = updates.deepLinkConfig.androidDeepLink;
		if (ios && !isSafeDeepLinkUrl(ios)) {
			return apiError(res, 400, "iOS deep link scheme not allowed");
		}
		if (android && !isSafeDeepLinkUrl(android)) {
			return apiError(res, 400, "Android deep link scheme not allowed");
		}
		updateData.deep_link_config = {
			ios_deep_link: ios || null,
			android_deep_link: android || null,
			fallback_url: updates.deepLinkConfig.fallbackUrl || null,
			enable_deep_link: updates.deepLinkConfig.enableDeepLink ?? null,
		};
	}

	const { data: updated, error } = await getSupabaseAny()
		.from("link_items")
		.update(updateData)
		.eq("id", linkId)
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[links] Failed to update link", {
			error: String(error),
			linkId,
			userId,
		});
		return apiError(res, 500, "Failed to update link");
	}
	if (!updated) return apiError(res, 404, "Link not found");

	// Sync page to Cloudflare KV after updating link (with retry)
	await syncWithRetry(supabase, link.page_id);
	return apiSuccess(res, { link: updated });
}
