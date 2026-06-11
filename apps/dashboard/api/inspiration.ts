/**
 * Inspiration Engine API Route — thin router that delegates to handler modules.
 *
 * POST /api/inspiration?action=get-ideas|save|dismiss|queue|bulk-queue|regenerate|refresh|get-config|update-config|get-counts|get-competitors|save-external
 */

import { apiError, badRequest, serverError } from "./_lib/apiResponse.js";
import { trackUsage } from "./_lib/auditLog.js";
import { logger } from "./_lib/logger.js";
import { withAuth } from "./_lib/middleware.js";
import { checkRateLimit } from "./_lib/rateLimiter.js";

export default withAuth(async (req, res, user) => {
	const action = req.query.action as string;
	const userId = user.id;

	// #692: Rate limit inspiration API
	const rl = await checkRateLimit({
		key: `inspiration:${userId}`,
		limit: 30,
		windowSeconds: 60,
		failMode: "closed",
	});
	if (!rl.allowed)
		return apiError(res, 429, "Rate limit exceeded. Try again shortly.");

	try {
		switch (action) {
			case "get-ideas": {
				trackUsage(userId, "inspiration.get-ideas");
				const { handleGetIdeas } = await import(
					"./_lib/handlers/inspiration/getIdeas.js"
				);
				return handleGetIdeas(req, res, userId);
			}
			case "save": {
				const { handleSave } = await import(
					"./_lib/handlers/inspiration/save.js"
				);
				return handleSave(req, res, userId);
			}
			case "dismiss": {
				const { handleDismiss } = await import(
					"./_lib/handlers/inspiration/dismiss.js"
				);
				return handleDismiss(req, res, userId);
			}
			case "queue": {
				const { handleQueue } = await import(
					"./_lib/handlers/inspiration/queue.js"
				);
				return handleQueue(req, res, userId);
			}
			case "bulk-queue": {
				const { handleBulkQueue } = await import(
					"./_lib/handlers/inspiration/bulkQueue.js"
				);
				return handleBulkQueue(req, res, userId);
			}
			case "regenerate": {
				trackUsage(userId, "inspiration.regenerate");
				const { handleRegenerate } = await import(
					"./_lib/handlers/inspiration/regenerate.js"
				);
				return handleRegenerate(req, res, userId);
			}
			case "refresh": {
				trackUsage(userId, "inspiration.refresh");
				const { handleRefresh } = await import(
					"./_lib/handlers/inspiration/refresh.js"
				);
				return handleRefresh(req, res, userId);
			}
			case "get-config": {
				const { handleGetConfig } = await import(
					"./_lib/handlers/inspiration/getConfig.js"
				);
				return handleGetConfig(req, res, userId);
			}
			case "update-config": {
				const { handleUpdateConfig } = await import(
					"./_lib/handlers/inspiration/updateConfig.js"
				);
				return handleUpdateConfig(req, res, userId);
			}
			case "get-counts": {
				const { handleGetCounts } = await import(
					"./_lib/handlers/inspiration/getCounts.js"
				);
				return handleGetCounts(req, res, userId);
			}
			case "get-competitors": {
				const { handleGetCompetitors } = await import(
					"./_lib/handlers/inspiration/getCompetitors.js"
				);
				return handleGetCompetitors(req, res, userId);
			}
			case "save-external": {
				const { handleSaveExternal } = await import(
					"./_lib/handlers/inspiration/saveExternal.js"
				);
				return handleSaveExternal(req, res, userId);
			}
			default:
				return badRequest(res, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Inspiration API error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
});
