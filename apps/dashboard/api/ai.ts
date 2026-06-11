/**
 * AI API Route — Thin Router
 *
 * /api/ai?action=<action>
 *
 * Dispatches to handler modules in _lib/handlers/ai/.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
  authenticatedRouteError,
  getAuthUserOrError,
} from "./_lib/apiResponse.js";
import { enforceRouteRateLimit } from "./_lib/routeRateLimit.js";
import { getUserTier } from "./_lib/tierGate.js";

export const config = { maxDuration: 60 };

const GENERATION_LIMIT_BY_TIER: Record<string, number> = {
  free: 20,
  pro: 100,
  agency: 300,
  empire: 500,
};
const DEFAULT_GENERATION_LIMIT = 20;

const GENERATION_ACTIONS = new Set([
  "generate",
  "generate-caption",
  "copilot",
  "investigate",
  "generate-image",
  "growth-simulator",
  "sandbox",
  "insight-to-caption",
  "style-bible",
  "vision-score",
  "generate-single",
  "generate-narrative",
]);

const READ_ACTIONS = new Set([
  "nl-query",
  "feedback",
  "keys",
  "low-hanging-fruit",
  "dismiss-recommendation",
]);

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const action = (req.query.action as string) || "";
  if (GENERATION_ACTIONS.has(action) || READ_ACTIONS.has(action)) {
    const user = await getAuthUserOrError(req, res);
    if (!user) return;

    const isGeneration = GENERATION_ACTIONS.has(action);
    let generationLimit = 200;
    if (isGeneration) {
      try {
        generationLimit =
          GENERATION_LIMIT_BY_TIER[(await getUserTier(user.id))] ??
          DEFAULT_GENERATION_LIMIT;
      } catch {
        generationLimit = DEFAULT_GENERATION_LIMIT;
      }
    }
    const allowed = await enforceRouteRateLimit(res, {
      key: `ai-${isGeneration ? "gen" : "read"}:user:${user.id}:hour`,
      limit: generationLimit,
      windowSeconds: 3600,
      failMode: isGeneration ? "closed" : "open",
      message: isGeneration
        ? "Too many AI generation requests. Try again later."
        : "Too many AI read requests. Try again later.",
    });
    if (!allowed) return;
  }

  switch (action) {
    case "generate":
      return (await import("./_lib/handlers/ai/generate.js")).default(req, res);
    case "generate-caption":
      return (await import("./_lib/handlers/ai/generate-caption.js")).default(
        req,
        res,
      );
    case "copilot":
      return (await import("./_lib/handlers/ai/copilot.js")).default(req, res);
    case "investigate":
      return (await import("./_lib/handlers/ai/investigate.js")).default(
        req,
        res,
      );
    case "nl-query":
      return (await import("./_lib/handlers/ai/nl-query.js")).default(req, res);
    case "feedback":
      return (await import("./_lib/handlers/ai/feedback.js")).default(req, res);
    case "keys":
      return (await import("./_lib/handlers/ai/keys.js")).default(req, res);
    case "generate-image":
      return (await import("./_lib/handlers/ai/generate-image.js")).default(
        req,
        res,
      );
    case "growth-simulator":
      return (await import("./_lib/handlers/ai/growth-simulator.js")).default(
        req,
        res,
      );
    case "sandbox":
      return (await import("./_lib/handlers/ai/sandbox.js")).default(req, res);
    case "insight-to-caption":
      return (await import("./_lib/handlers/ai/insight-to-caption.js")).default(
        req,
        res,
      );
    case "low-hanging-fruit":
      return (await import("./_lib/handlers/ai/low-hanging-fruit.js")).default(
        req,
        res,
      );
    case "style-bible":
      return (await import("./_lib/handlers/ai/style-bible.js")).default(
        req,
        res,
      );
    case "dismiss-recommendation":
      return (
        await import("./_lib/handlers/ai/dismiss-recommendation.js")
      ).default(req, res);
    case "vision-score":
      return (await import("./_lib/handlers/ai/vision-score.js")).default(
        req,
        res,
      );
    case "generate-single":
      return (await import("./_lib/handlers/ai/generate-single.js")).default(
        req,
        res,
      );
    case "generate-narrative":
      return (await import("./_lib/handlers/ai/generate-narrative.js")).default(
        req,
        res,
      );
    default:
      return authenticatedRouteError(req, res, 400, `Unknown action: ${action}`);
  }
}
