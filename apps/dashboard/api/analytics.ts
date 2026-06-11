/**
 * Analytics API Route — Thin Router
 *
 * POST /api/analytics?action=<action>
 *
 * Dispatches to handler modules in _lib/handlers/analytics/.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, methodNotAllowed } from "./_lib/apiResponse.js";
import { validateEnv } from "./_lib/envValidation.js";
import { logger } from "./_lib/logger.js";
import { withAuth } from "./_lib/middleware.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./_lib/privilegedDb.js";
import { z } from "./_lib/zodCompat.js";

// ============================================================================
// Query schema
// ============================================================================

const querySchema = z.object({
	action: z.string().min(1),
});

type AnalyticsActionHandler = (
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) => Promise<VercelResponse | undefined>;

const analyticsSubHandler = (moduleName: string): AnalyticsActionHandler => {
	return async (req, res) =>
		(await import(`./_lib/handlers/analytics-sub/${moduleName}.js`)).default(
			req,
			res,
		);
};

const ANALYTICS_ACTIONS: Record<string, AnalyticsActionHandler> = {
	refresh: async (req, res) =>
		(await import("./_lib/handlers/analytics/refresh.js")).handleRefresh(
			req,
			res,
		),
	"ig-refresh": async (req, res) =>
		(await import("./_lib/handlers/analytics/refresh.js")).handleIgRefresh(
			req,
			res,
		),
	"sync-batch": async (req, res) =>
		(await import("./_lib/handlers/analytics/syncBatch.js")).handleSyncBatch(
			req,
			res,
		),
	"queue-sync": async (req, res) =>
		(await import("./_lib/handlers/analytics/queueSync.js")).handleQueueSync(
			req,
			res,
		),
	"bulk-sync": async (req, res, userId) =>
		(await import("./_lib/handlers/analytics/bulkSync.js")).handleBulkSync(
			req,
			res,
			userId,
		),
	aggregated: (req, res, userId) => handleAggregatedAnalytics(req, res, userId),
	"post-floor-aggregates": (req, res, userId) =>
		handlePostFloorAggregates(req, res, userId),
	"job-status": async (req, res) =>
		(await import("./_lib/handlers/analytics/queueSync.js")).handleJobStatus(
			req,
			res,
		),
	backfill: async (req, res) =>
		(await import("./_lib/handlers/analytics/backfill.js")).handleBackfill(
			req,
			res,
		),
	rebackfill: async (req, res) =>
		(await import("./_lib/handlers/analytics/backfill.js")).handleRebackfill(
			req,
			res,
		),
	demographics: async (req, res) =>
		(await import("./_lib/handlers/analytics/demographics.js")).handleDemographics(
			req,
			res,
		),
	"fix-baselines": async (req, res) =>
		(await import("./_lib/handlers/analytics/fixBaselines.js")).handleFixBaselines(
			req,
			res,
		),
	"group-analytics": analyticsSubHandler("group-analytics"),
	"competitor-patterns": analyticsSubHandler("competitor-patterns"),
	"cross-insights": analyticsSubHandler("cross-insights"),
	"daily-activity": analyticsSubHandler("daily-activity"),
	"feature-usage": analyticsSubHandler("feature-usage"),
	forecasts: analyticsSubHandler("forecasts"),
	"model-comparison": analyticsSubHandler("model-comparison"),
	"post-metrics-history": analyticsSubHandler("post-metrics-history"),
	"reach-anomaly": analyticsSubHandler("reach-anomaly"),
	"reach-anomalies": analyticsSubHandler("reach-anomalies"),
	revenue: analyticsSubHandler("revenue"),
	"self-compare": analyticsSubHandler("self-compare"),
	"top-elements": analyticsSubHandler("top-elements"),
	"while-away": analyticsSubHandler("while-away"),
	network: async (req, res) =>
		(await import("./_lib/handlers/insights/network.js")).default(req, res),
	"health-snapshots": analyticsSubHandler("health-snapshots"),
	"account-health": analyticsSubHandler("account-health"),
	"funnel-correlation": analyticsSubHandler("funnel-correlation"),
	"competitor-trends": analyticsSubHandler("competitor-trends"),
	"demographics-db": analyticsSubHandler("demographics-db"),
	benchmarks: analyticsSubHandler("benchmarks"),
	annotations: analyticsSubHandler("annotations"),
	"hashtag-performance": analyticsSubHandler("hashtag-performance"),
	"top-engagers": analyticsSubHandler("top-engagers"),
	"team-performance": analyticsSubHandler("team-performance"),
	"engager-retention": analyticsSubHandler("engager-retention"),
	"audience-overlap": analyticsSubHandler("audience-overlap"),
	"follower-attribution": analyticsSubHandler("follower-attribution"),
	"content-type-trend": analyticsSubHandler("content-type-trend"),
	"competitor-benchmark": analyticsSubHandler("competitor-benchmark"),
	"competitor-pattern-benchmark": analyticsSubHandler(
		"competitor-pattern-benchmark",
	),
	"autoposter-performance-attribution": analyticsSubHandler(
		"autoposter-performance-attribution",
	),
	"autoposter-performance-validation": analyticsSubHandler(
		"autoposter-performance-validation",
	),
	"autoposter-quality-gate-effectiveness": analyticsSubHandler(
		"autoposter-quality-gate-effectiveness",
	),
	"overnight-brief": analyticsSubHandler("overnight-brief"),
	"sends-per-reach-leaders": analyticsSubHandler("sends-per-reach-leaders"),
	"skip-rate-alerts": analyticsSubHandler("skip-rate-alerts"),
	"quote-reply-ratio": analyticsSubHandler("quote-reply-ratio"),
	"link-click-leaders": analyticsSubHandler("link-click-leaders"),
	"watch-time-leaders": analyticsSubHandler("watch-time-leaders"),
	"topic-tag-lift": analyticsSubHandler("topic-tag-lift"),
	"save-rate-leaders": analyticsSubHandler("save-rate-leaders"),
	"non-follower-reach-breakdown": analyticsSubHandler(
		"non-follower-reach-breakdown",
	),
	"audience-online-now": analyticsSubHandler("audience-online-now"),
	"story-profile-activity": analyticsSubHandler("story-profile-activity"),
	"anomaly-feed": analyticsSubHandler("anomaly-feed"),
	"reply-depth-leaders": analyticsSubHandler("reply-depth-leaders"),
	"pending-replies-queue": analyticsSubHandler("pending-replies-queue"),
	"competitor-surprises": analyticsSubHandler("competitor-surprises"),
	"cross-account-patterns": analyticsSubHandler("cross-account-patterns"),
	"fleet-health-accounts": analyticsSubHandler("fleet-health-accounts"),
	"views-by-source": analyticsSubHandler("views-by-source"),
	"severity-score": analyticsSubHandler("severity-score"),
	"cohort-benchmarks": analyticsSubHandler("cohort-benchmarks"),
	"quality-by-pillar": analyticsSubHandler("quality-by-pillar"),
	"bio-link-funnel": analyticsSubHandler("bio-link-funnel"),
	"hook-class-lift": analyticsSubHandler("hook-class-lift"),
	"stories-funnel": analyticsSubHandler("stories-funnel"),
	"strikes-count": analyticsSubHandler("strikes-count"),
	"originality-risk": analyticsSubHandler("originality-risk"),
	"audience-twin-map": analyticsSubHandler("audience-twin-map"),
};

// ============================================================================
// Main handler (router)
// ============================================================================

export default withAuth(async (req, res, _user) => {
	// Analytics is intentionally a dense evidence surface. A large workspace can
	// mount 30+ tiles, several with parallel platform/account fetches, so the
	// generic 60/min cap rate-limits the first page load. Keep this route bounded
	// but sized for the page it serves.
	const { checkRateLimit } = await import("./_lib/rateLimiter.js");
	const rl = await checkRateLimit({
		key: `analytics:${_user.id}`,
		limit: 180,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) {
		res.setHeader("Retry-After", String(rl.retryAfterSeconds || 60));
		return apiError(res, 429, "Rate limit exceeded");
	}

	// Check environment variables first
	const missingEnv = validateEnv("core") as string[];
	if (missingEnv.length > 0) {
		logger.error("Missing environment variables", { missing: missingEnv });
		return apiError(res, 500, "Server configuration error", {
			details: `Missing: ${missingEnv.join(", ")}`,
		});
	}

	if (req.method !== "POST" && req.method !== "GET") {
		return methodNotAllowed(res);
	}

	const parsed = querySchema.safeParse(req.query);
	if (!parsed.success) {
		return apiError(res, 400, `Unknown action: ${req.query.action ?? ""}`);
	}
	const { action } = parsed.data;

	try {
		const handler = ANALYTICS_ACTIONS[action];
		if (!handler) return apiError(res, 400, `Unknown action: ${action}`);
		return handler(req, res, _user.id);
	} catch (error: unknown) {
		logger.error("Analytics API error", { error: String(error) });
		try {
			const { captureServerException } = await import("./_lib/sentryServer.js");
			await captureServerException(error, {
				route: "analytics",
				action: req.query.action,
			});
		} catch (sentryErr) {
			logger.warn("[analytics] Sentry capture failed", {
				originalError: String(error),
				sentryError:
					sentryErr instanceof Error ? sentryErr.message : String(sentryErr),
			});
		}
		return apiError(res, 500, "Internal server error");
	}
});

async function handleAggregatedAnalytics(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (req.method !== "POST") return methodNotAllowed(res);

	const body = req.body || {};
	const days =
		typeof body.days === "number" && Number.isFinite(body.days)
			? Math.max(1, Math.min(365, Math.trunc(body.days)))
			: 90;
	const platform = body.platform === "instagram" ? "instagram" : "threads";
	const accountIds = Array.isArray(body.accountIds)
		? body.accountIds.filter((id: unknown): id is string => typeof id === "string")
		: null;

	const { data, error } = await getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.analyticsReadAggregation,
	).rpc("get_aggregated_analytics", {
		p_user_id: userId,
		p_days: days,
		p_platform: platform,
		p_account_ids: accountIds && accountIds.length > 0 ? accountIds : null,
	});

	if (error) {
		logger.error("Aggregated analytics RPC failed", {
			userId,
			platform,
			error: error.message,
		});
		return apiError(res, 500, "Failed to fetch aggregated analytics");
	}

	return res.status(200).json({ success: true, rows: data || [] });
}

async function handlePostFloorAggregates(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (req.method !== "POST") return methodNotAllowed(res);

	const body = req.body || {};
	const accountIds = Array.isArray(body.accountIds)
		? body.accountIds.filter((id: unknown): id is string => typeof id === "string")
		: [];
	const since = typeof body.since === "string" ? body.since : null;
	const platform = body.platform === "instagram" ? "instagram" : null;
	if (!since) return apiError(res, 400, "since is required");

	const { data, error } = await getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.analyticsReadAggregation,
	).rpc("get_post_floor_aggregates", {
		p_user_id: userId,
		p_account_ids: accountIds,
		p_since: since,
		p_platform: platform,
	});

	if (error) {
		logger.error("Post floor aggregate RPC failed", {
			userId,
			platform,
			error: error.message,
		});
		return apiError(res, 500, "Failed to fetch post floor aggregates");
	}

	const row = Array.isArray(data) ? data[0] : data;
	return res.status(200).json({ success: true, row: row || null });
}
