import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
import {
	CreatePageSchema,
	getUserTier,
	LINK_LIMITS,
	syncWithRetry,
} from "./shared.js";

export async function handleCreatePage(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const supabase = getSupabase();
	const parsed = CreatePageSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const {
		slug,
		title,
		bio,
		avatarUrl,
		backgroundColor,
		brandColor,
		promoText,
		enableDeeplinkEscape,
	} = parsed.data;

	// Check plan limits
	const tier = await getUserTier(userId);
	const limits = LINK_LIMITS[tier];

	const { count: pageCount } = await supabase
		.from("link_pages")
		.select("*", { count: "exact", head: true })
		.eq("user_id", userId);

	if ((pageCount || 0) >= limits.maxPages) {
		return apiError(
			res,
			403,
			`Your ${tier} plan allows up to ${limits.maxPages} link page${limits.maxPages === 1 ? "" : "s"}. Upgrade to create more.`,
		);
	}

	// Enforce plan restrictions on premium features
	const finalDeeplinkEscape = limits.deeplinkEscape
		? enableDeeplinkEscape !== false
		: false;

	// Gate age gating by tier (silently strip if not allowed)
	const finalAgeGate = limits.ageGating ? parsed.data.ageGate || false : false;
	const finalAgeGateMessage =
		limits.ageGating && parsed.data.ageGateMessage
			? parsed.data.ageGateMessage
			: null;

	// Gate tracking pixels by tier (silently strip if not allowed)
	const finalTrackingPixels =
		limits.trackingPixels && parsed.data.trackingPixels
			? {
					meta_pixel_id: parsed.data.trackingPixels.metaPixelId || null,
					tiktok_pixel_id: parsed.data.trackingPixels.tiktokPixelId || null,
					ga4_measurement_id:
						parsed.data.trackingPixels.ga4MeasurementId || null,
					x_pixel_id: parsed.data.trackingPixels.xPixelId || null,
					snapchat_pixel_id: parsed.data.trackingPixels.snapchatPixelId || null,
					gtm_container_id: parsed.data.trackingPixels.gtmContainerId || null,
				}
			: null;

	// Check slug availability
	const { data: existing } = await supabase
		.from("link_pages")
		.select("id")
		.eq("slug", slug)
		.maybeSingle();

	if (existing) {
		return apiError(res, 409, "Slug already taken");
	}

	const client = getSupabaseAny();
	const createPayload = {
		slug,
		title: title || slug,
		bio: bio || null,
		avatar_url: avatarUrl || null,
		background_color: backgroundColor || "#0a0a0b",
		brand_color: brandColor || "#ff6b9d",
		promo_text: promoText || null,
		enable_deeplink_escape: finalDeeplinkEscape,
		age_gate: finalAgeGate,
		age_gate_message: finalAgeGateMessage,
		tracking_pixels: finalTrackingPixels,
	};
	const { data: page, error } =
		typeof client.rpc === "function"
			? await client.rpc("create_link_page_with_quota", {
					p_user_id: userId,
					p_limit: limits.maxPages,
					p_payload: createPayload,
				})
			: await client
					.from("link_pages")
					.insert({
						user_id: userId,
						...createPayload,
					})
					.select()
					.maybeSingle();

	if (error) {
		if (error.message?.includes("QUOTA_EXCEEDED")) {
			return apiError(
				res,
				403,
				`Your ${tier} plan allows up to ${limits.maxPages} link page${limits.maxPages === 1 ? "" : "s"}. Upgrade to create more.`,
			);
		}
		// DB UNIQUE constraint on slug is the real guard against TOCTOU race conditions.
		// Catch the constraint violation and return a user-friendly 409 instead of 500.
		if (error.code === "23505" || error.message?.includes("duplicate")) {
			return apiError(res, 409, "Slug already taken");
		}
		logger.error("[links] Failed to create page", {
			error: String(error),
			userId,
		});
		return apiError(res, 500, "Failed to create page");
	}
	if (!page) return apiError(res, 500, "Failed to create page");

	// Sync to Cloudflare KV with retry
	const syncResult = await syncWithRetry(supabase, page.id);
	return apiSuccess(res, { page, cfSync: syncResult.synced });
}
