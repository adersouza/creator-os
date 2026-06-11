import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
import {
	getUserTier,
	LINK_LIMITS,
	syncWithRetry,
	UpdatePageSchema,
} from "./shared.js";

export async function handleUpdatePage(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const supabase = getSupabase();
	const parsed = UpdatePageSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { pageId, ...updates } = parsed.data;

	// Check plan limits for premium features
	const tier = await getUserTier(userId);
	const limits = LINK_LIMITS[tier];

	if (
		!limits.customBranding &&
		(updates.backgroundColor || updates.brandColor || updates.avatarUrl)
	) {
		return apiError(res, 403, `Custom branding requires a Pro or Empire plan.`);
	}
	if (!limits.deeplinkEscape && updates.enableDeeplinkEscape) {
		return apiError(res, 403, `Deeplink escape requires a Pro or Empire plan.`);
	}

	const updateData: Record<string, unknown> = {
		updated_at: new Date().toISOString(),
	};
	if (updates.title !== undefined) updateData.title = updates.title;
	if (updates.bio !== undefined) updateData.bio = updates.bio;
	if (updates.avatarUrl !== undefined)
		updateData.avatar_url = updates.avatarUrl;
	if (updates.backgroundColor !== undefined)
		updateData.background_color = updates.backgroundColor;
	if (updates.brandColor !== undefined)
		updateData.brand_color = updates.brandColor;
	if (updates.promoText !== undefined)
		updateData.promo_text = updates.promoText;
	if (updates.showOnlineBadge !== undefined)
		updateData.show_online_badge = updates.showOnlineBadge;
	if (updates.isPublished !== undefined)
		updateData.is_published = updates.isPublished;
	if (updates.enableDeeplinkEscape !== undefined)
		updateData.enable_deeplink_escape = updates.enableDeeplinkEscape;

	// Gate age gating by tier (silently strip if not allowed)
	if (limits.ageGating) {
		if (updates.ageGate !== undefined) updateData.age_gate = updates.ageGate;
		if (updates.ageGateMessage !== undefined)
			updateData.age_gate_message = updates.ageGateMessage;
	}

	// Gate tracking pixels by tier (silently strip if not allowed)
	if (limits.trackingPixels && updates.trackingPixels !== undefined) {
		updateData.tracking_pixels = {
			meta_pixel_id: updates.trackingPixels.metaPixelId || null,
			tiktok_pixel_id: updates.trackingPixels.tiktokPixelId || null,
			ga4_measurement_id: updates.trackingPixels.ga4MeasurementId || null,
			x_pixel_id: updates.trackingPixels.xPixelId || null,
			snapchat_pixel_id: updates.trackingPixels.snapchatPixelId || null,
			gtm_container_id: updates.trackingPixels.gtmContainerId || null,
		};
	}

	// Gate Shield Protection by tier
	if (updates.shieldMode !== undefined) {
		if (limits.shieldModes.includes(updates.shieldMode)) {
			updateData.shield_mode = updates.shieldMode;
		} else {
			return apiError(
				res,
				403,
				`Shield mode "${updates.shieldMode}" requires a higher plan.`,
			);
		}
	}
	if (updates.shieldConfig !== undefined) {
		// Shield config only meaningful with shield enabled
		updateData.shield_config = updates.shieldConfig || null;
	}

	// Gate Geo Filter by tier
	if (updates.geoRules !== undefined) {
		if (!limits.geoFilter) {
			return apiError(res, 403, "Geo filtering requires a Pro or higher plan.");
		}
		updateData.geo_rules = updates.geoRules || null;
	}

	const { data: page, error } = await getSupabaseAny()
		.from("link_pages")
		.update(updateData)
		.eq("id", pageId)
		.eq("user_id", userId)
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[links] Failed to update page", {
			error: String(error),
			pageId,
			userId,
		});
		return apiError(res, 500, "Failed to update page");
	}
	if (!page) return apiError(res, 404, "Page not found");

	// Sync to Cloudflare KV with retry
	const syncResult = await syncWithRetry(supabase, pageId);
	return apiSuccess(res, { page, cfSync: syncResult.synced });
}
