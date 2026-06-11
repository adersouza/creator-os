/**
 * Links API Route — thin router that delegates to handler modules.
 * NOTE: This endpoint reads action from req.body (POST) or req.query (GET),
 * unlike most other routes that use req.query.action exclusively.
 */

import { apiError } from "./_lib/apiResponse.js";
import { logAudit } from "./_lib/auditLog.js";
import { logger } from "./_lib/logger.js";
import { withAuth } from "./_lib/middleware.js";
import { enforceRouteRateLimit } from "./_lib/routeRateLimit.js";

const MUTATION_ACTIONS = new Set([
  "ai-enhance",
  "capture-email",
  "track-event",
  "visitor-signal",
  "create-page",
  "update-page",
  "add-link",
  "update-link",
  "reorder",
  "delete-link",
  "delete-page",
]);
const READ_ACTIONS = new Set(["domains", "get-page", "list-pages", "analytics"]);

export default withAuth(async (req, res, user) => {
  const userId = user.id;

  const action = (
    req.method === "GET" ? req.query.action : req.body?.action
  ) as string;

  try {
    if (MUTATION_ACTIONS.has(action) || READ_ACTIONS.has(action)) {
      const isMutation = MUTATION_ACTIONS.has(action);
      const allowed = await enforceRouteRateLimit(res, {
        key: `links-${isMutation ? "create" : "read"}:user:${userId}:hour`,
        limit: isMutation ? 30 : 120,
        windowSeconds: 3600,
        failMode: isMutation ? "closed" : "open",
        message: isMutation
          ? "Too many smart-link create requests. Try again later."
          : "Too many smart-link read requests. Try again later.",
      });
      if (!allowed) return;
    }

    switch (action) {
      case "domains":
        return (await import("./_lib/handlers/links-sub/domains.js")).default(
          req,
          res,
        );
      case "track":
        return (await import("./_lib/handlers/link-page-sub/track.js")).default(
          req,
          res,
        );
      case "ai-enhance": {
        const { handleEnhance } =
          await import("./_lib/handlers/smart-links/enhance.js");
        return handleEnhance(req, res, userId);
      }
      case "capture-email": {
        const { handleCaptureEmail } =
          await import("./_lib/handlers/links/captureEmail.js");
        return handleCaptureEmail(req, res, userId);
      }
      case "track-event": {
        const { handleTrackEvent } =
          await import("./_lib/handlers/links/trackEvent.js");
        return handleTrackEvent(req, res, userId);
      }
      case "visitor-signal": {
        const { handleVisitorSignal } =
          await import("./_lib/handlers/links/visitorSignal.js");
        return handleVisitorSignal(req, res, userId);
      }
      case "create-page": {
        const { handleCreatePage } =
          await import("./_lib/handlers/links/createPage.js");
        return handleCreatePage(req, res, userId);
      }
      case "update-page": {
        const { handleUpdatePage } =
          await import("./_lib/handlers/links/updatePage.js");
        return handleUpdatePage(req, res, userId);
      }
      case "get-page": {
        const { handleGetPage } =
          await import("./_lib/handlers/links/getPage.js");
        return handleGetPage(req, res, userId);
      }
      case "list-pages": {
        const { handleListPages } =
          await import("./_lib/handlers/links/listPages.js");
        return handleListPages(req, res, userId);
      }
      case "add-link": {
        const { handleAddLink } =
          await import("./_lib/handlers/links/addLink.js");
        return handleAddLink(req, res, userId);
      }
      case "update-link": {
        const { handleUpdateLink } =
          await import("./_lib/handlers/links/updateLink.js");
        return handleUpdateLink(req, res, userId);
      }
      case "reorder": {
        const { handleReorderLinks } =
          await import("./_lib/handlers/links/reorderLinks.js");
        return handleReorderLinks(req, res, userId);
      }
      case "delete-link": {
        logAudit(userId, "link.delete", { req });
        const { handleDeleteLink } =
          await import("./_lib/handlers/links/deleteLink.js");
        return handleDeleteLink(req, res, userId);
      }
      case "delete-page": {
        logAudit(userId, "link-page.delete", { req });
        const { handleDeletePage } =
          await import("./_lib/handlers/links/deletePage.js");
        return handleDeletePage(req, res, userId);
      }
      case "analytics": {
        const { handleGetAnalytics } =
          await import("./_lib/handlers/links/getAnalytics.js");
        return handleGetAnalytics(req, res, userId);
      }
      default:
        return apiError(res, 400, `Unknown action: ${action}`);
    }
  } catch (error: unknown) {
    logger.error("Links API error", { error: String(error) });
    return apiError(res, 500, "Internal server error");
  }
});
