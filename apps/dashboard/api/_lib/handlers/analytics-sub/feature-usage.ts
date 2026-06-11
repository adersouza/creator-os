import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

const ALLOWED_FEATURE_EVENTS = new Set([
	"composer_open",
	"composer_publish",
	"composer_schedule",
	"dashboard_view",
	"analytics_view",
	"links_view",
	"inbox_view",
	"settings_view",
	"export_created",
]);

function isAllowedFeatureEvent(feature: string): boolean {
	if (ALLOWED_FEATURE_EVENTS.has(feature)) return true;
	return /^(dashboard_time_seconds|tab_refresh_count):\d{1,5}$/.test(feature);
}

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

	const { feature } = req.body || {};
	if (!feature || typeof feature !== "string" || feature.length > 100) {
		return apiError(res, 400, "Invalid feature name");
	}
	if (!isAllowedFeatureEvent(feature)) {
		return apiError(res, 400, "Unknown feature event", {
			code: "FEATURE_EVENT_NOT_ALLOWED",
		});
	}

	const supabase = getSupabase();
	const userId = user.id;

	// Rate limit: max 100 events/user/hour
	const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
	const { count, error: countError } = await supabase
		.from("feature_usage")
		.select("id", { count: "exact", head: true })
		.eq("user_id", userId)
		.gte("used_at", oneHourAgo);

	if (countError) {
		return apiError(res, 503, "Rate limit unavailable", {
			code: "RATE_LIMIT_UNAVAILABLE",
		});
	}

	if (count !== null && count >= 100) {
		return apiError(res, 429, "Rate limit exceeded", { code: "RATE_LIMITED" });
	}

	const { error } = await supabase.from("feature_usage").insert({
		user_id: userId,
		feature_name: feature,
	});

	if (error) {
		return apiError(res, 500, "Failed to track feature usage");
	}

	return apiSuccess(res, { tracked: true });
});
