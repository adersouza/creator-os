import type { VercelRequest, VercelResponse } from "@vercel/node";
import { checkAIRateLimit } from "../../aiRateLimit.js";
import { getUserAIConfig } from "../../aiConfig.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { requireMinTier } from "../../tierGate.js";
import { z } from "../../zodCompat.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";

const Schema = z.object({
  category: z.string().min(1).max(40),
  persona: z.string().max(120).optional().nullable(),
  account_id: z.string().max(120).optional().nullable(),
});

function fallback(category: string) {
  return [
    { text: `A sharper ${category} for the audience that already cares.` },
    { text: `Save this ${category} for the next post that needs momentum.` },
    { text: `Use this ${category} when the angle needs to feel immediate.` },
  ];
}

function fallbackResponse(category: string, reason: string) {
  return { variants: fallback(category), fallback: true, reason };
}

export default withAuth(
  async (req: VercelRequest, res: VercelResponse, user) => {
    if (req.method !== "POST") return apiError(res, 405, "Method not allowed");
    const parsed = Schema.safeParse(req.body);
    if (!parsed.success) {
      return apiError(
        res,
        400,
        `Invalid input: ${parsed.error.issues[0]?.message}`,
      );
    }
    if (!(await requireMinTier(user.id, "pro", res))) return;
    const rateLimit = await checkAIRateLimit(user.id, "generate-caption");
    if (!rateLimit.allowed) {
      return apiError(res, 429, "AI rate limit exceeded. Try again shortly.");
    }
    const { category, persona } = parsed.data;
    const aiConfig = await getUserAIConfig(user.id);
    if (!aiConfig) return apiSuccess(res, fallbackResponse(category, "missing_ai_config"));
    const prompt = [
      "Generate exactly 3 reusable social caption snippets.",
      `Category: ${category}`,
      `Persona: ${persona || "default"}`,
      'Return strict JSON only: {"variants":[{"text":"..."}]}',
      "Each text should be concise, concrete, and ready to save as a template.",
    ].join("\n");
    try {
      const raw = await generateWithProvider(prompt, {
        provider: aiConfig.provider,
        apiKey: aiConfig.apiKey,
        baseUrl: aiConfig.baseUrl,
        model: aiConfig.model,
        ideaCount: 6,
        useStructuredOutput: true,
        structuredOutputSchema: {
          type: "OBJECT",
          properties: {
            variants: {
              type: "ARRAY",
              items: {
                type: "OBJECT",
                properties: { text: { type: "STRING" } },
                required: ["text"],
              },
            },
          },
          required: ["variants"],
        },
      });
      const parsedRaw = raw ? JSON.parse(raw) : null;
      const variants = Array.isArray(parsedRaw?.variants)
        ? parsedRaw.variants.slice(0, 3)
        : fallback(category);
      return apiSuccess(res, {
        variants,
        fallback: !Array.isArray(parsedRaw?.variants),
        ...(Array.isArray(parsedRaw?.variants) ? {} : { reason: "invalid_provider_response" }),
      });
    } catch {
      return apiSuccess(res, fallbackResponse(category, "provider_error"));
    }
  },
);
