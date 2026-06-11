/**
 * Smart Links CRUD + Analytics — thin router.
 * POST /api/smart-links?action=list|create|update|delete|analytics|revenue-trend|post-attribution
 *
 * Authenticated. Pro+ tier required.
 */

import { apiError } from "./_lib/apiResponse.js";
import { logger } from "./_lib/logger.js";
import { withAuth } from "./_lib/middleware.js";
import { checkRateLimit } from "./_lib/rateLimiter.js";
import { requireMinTier } from "./_lib/tierGate.js";

export default withAuth(async (req, res, user) => {
  const userId = user.id;

  // Tier gate: Pro+ required
  const tierOk = await requireMinTier(userId, "pro", res);
  if (!tierOk) return;

  // #518: Rate limit smart link CRUD (60 requests/minute)
  const rl = await checkRateLimit({
    key: `smart-links:${userId}`,
    limit: 60,
    windowSeconds: 60,
    failMode: "closed",
  });
  if (!rl.allowed) {
    return apiError(res, 429, "Too many requests. Please slow down.");
  }

  const action =
    req.method === "GET"
      ? (req.query.action as string) || "list"
      : (req.body?.action as string);

  try {
    switch (action) {
      case "list": {
        const { handleList } =
          await import("./_lib/handlers/smart-links/list.js");
        return handleList(req, res, userId);
      }
      case "create": {
        const { handleCreate } =
          await import("./_lib/handlers/smart-links/create.js");
        return handleCreate(req, res, userId);
      }
      case "update": {
        const { handleUpdate } =
          await import("./_lib/handlers/smart-links/update.js");
        return handleUpdate(req, res, userId);
      }
      case "delete": {
        const { handleDelete } =
          await import("./_lib/handlers/smart-links/delete.js");
        return handleDelete(req, res, userId);
      }
      case "enhance": {
        const { handleEnhance } =
          await import("./_lib/handlers/smart-links/enhance.js");
        return handleEnhance(req, res, userId);
      }
      case "analytics": {
        const { handleAnalytics } =
          await import("./_lib/handlers/smart-links/analytics.js");
        return handleAnalytics(req, res, userId);
      }
      case "revenue-summary": {
        const { handleRevenueSummary } =
          await import("./_lib/handlers/smart-links/revenueSummary.js");
        return handleRevenueSummary(req, res, userId);
      }
      case "link-conversions": {
        const { handleLinkConversions } =
          await import("./_lib/handlers/smart-links/linkConversions.js");
        return handleLinkConversions(req, res, userId);
      }
      case "post-links": {
        const { handlePostLinks } =
          await import("./_lib/handlers/smart-links/postLinks.js");
        return handlePostLinks(req, res, userId);
      }
      case "revenue-trend": {
        const { handleRevenueTrend } =
          await import("./_lib/handlers/smart-links/revenueTrend.js");
        return handleRevenueTrend(req, res, userId);
      }
      case "post-attribution": {
        const { handlePostAttribution } =
          await import("./_lib/handlers/smart-links/postAttribution.js");
        return handlePostAttribution(req, res, userId);
      }
      default:
        return apiError(res, 400, `Unknown action: ${action}`);
    }
  } catch (error) {
    logger.error("[smart-links] API error", { error: String(error) });
    return apiError(res, 500, "Internal server error");
  }
});
