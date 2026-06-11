import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { validatePublicRedirectUrl } from "../../outboundUrlSecurity.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
import {
	AddLinkSchema,
	getUserTier,
	isSafeDeepLinkUrl,
	isSafeUrl,
	LINK_LIMITS,
	syncWithRetry,
} from "./shared.js";

export async function handleAddLink(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const supabase = getSupabase();
	const parsed = AddLinkSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { pageId, title, url, icon, isPrimary, platform, deepLinkUrl } =
		parsed.data;

	// Block dangerous URL schemes
	if (!isSafeUrl(url)) {
		return apiError(res, 400, "Only http:// and https:// URLs are allowed");
	}
	if (await validatePublicRedirectUrl(url, "link-item-create")) {
		return apiError(res, 400, "URL is not allowed");
	}
	if (deepLinkUrl && !isSafeDeepLinkUrl(deepLinkUrl)) {
		return apiError(res, 400, "Deep link URL scheme not allowed");
	}

	// Verify page ownership
	const { data: page } = await supabase
		.from("link_pages")
		.select("id")
		.eq("id", pageId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!page) return apiError(res, 404, "Page not found");

	// Check plan limits
	const tier = await getUserTier(userId);
	const limits = LINK_LIMITS[tier];

	// Get next position + check count
	const { count } = await supabase
		.from("link_items")
		.select("*", { count: "exact", head: true })
		.eq("page_id", pageId);

	if ((count || 0) >= limits.maxLinksPerPage) {
		return apiError(
			res,
			403,
			`Your ${tier} plan allows up to ${limits.maxLinksPerPage} links per page. Upgrade to add more.`,
		);
	}

	// Generate a random 8-char alphanumeric redirect ID
	const { randomBytes } = await import("node:crypto");
	const redirectId = randomBytes(4).toString("hex");

	// Gate per-link styling and deep link config by tier
	const styleData =
		limits.perLinkStyling && parsed.data.style
			? {
					bg_color: parsed.data.style.bgColor || null,
					text_color: parsed.data.style.textColor || null,
					border_radius: parsed.data.style.borderRadius ?? null,
					animation: parsed.data.style.animation || null,
					image_url: parsed.data.style.imageUrl || null,
					image_mode: parsed.data.style.imageMode || null,
				}
			: null;

	if (limits.deeplinkEscape && parsed.data.deepLinkConfig) {
		const ios = parsed.data.deepLinkConfig.iosDeepLink;
		const android = parsed.data.deepLinkConfig.androidDeepLink;
		if (ios && !isSafeDeepLinkUrl(ios)) {
			return apiError(res, 400, "iOS deep link scheme not allowed");
		}
		if (android && !isSafeDeepLinkUrl(android)) {
			return apiError(res, 400, "Android deep link scheme not allowed");
		}
	}
	const deepLinkConfigData =
		limits.deeplinkEscape && parsed.data.deepLinkConfig
			? {
					ios_deep_link: parsed.data.deepLinkConfig.iosDeepLink || null,
					android_deep_link: parsed.data.deepLinkConfig.androidDeepLink || null,
					fallback_url: parsed.data.deepLinkConfig.fallbackUrl || null,
					enable_deep_link: parsed.data.deepLinkConfig.enableDeepLink ?? null,
				}
			: null;

	const client = getSupabaseAny();
	const createPayload = {
		title,
		url,
		icon: icon || null,
		is_primary: isPrimary || false,
		platform: platform || null,
		deep_link_url: deepLinkUrl || null,
		redirect_id: redirectId,
		style: styleData,
		deep_link_config: deepLinkConfigData,
	};
	const { data: link, error } =
		typeof client.rpc === "function"
			? await client.rpc("create_link_item_with_quota", {
					p_user_id: userId,
					p_page_id: pageId,
					p_limit: limits.maxLinksPerPage,
					p_payload: createPayload,
				})
			: await client
					.from("link_items")
					.insert({
						page_id: pageId,
						position: count || 0,
						...createPayload,
					})
					.select()
					.maybeSingle();

	if (error) {
		if (error.message?.includes("QUOTA_EXCEEDED")) {
			return apiError(
				res,
				403,
				`Your ${tier} plan allows up to ${limits.maxLinksPerPage} links per page. Upgrade to add more.`,
			);
		}
		if (error.message?.includes("NOT_FOUND")) {
			return apiError(res, 404, "Page not found");
		}
		logger.error("[links] Failed to add link", { error, pageId });
		return apiError(res, 500, "Failed to add link");
	}

	// Sync page to Cloudflare KV after adding link (with retry)
	await syncWithRetry(supabase, pageId);
	return apiSuccess(res, { link });
}
