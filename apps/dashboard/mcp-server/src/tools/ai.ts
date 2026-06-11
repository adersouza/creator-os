import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, zNum, AI_TIMEOUT } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "ai_generate",
    "Generate AI content (captions, ideas, replies) using the account's voice profile. Returns quality-scored output with optional variants.",
    {
      prompt: z.string().describe("What to generate (e.g. 'Write a thread about productivity tips')"),
      accountId: z.string().optional().describe("Account ID for voice profile context"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Target platform for character limits"),
      variants: zNum.optional().describe("Number of variants (1-3, default 1)"),
    },
    async ({ prompt, accountId, platform, variants }) => {
      return respond(await api("/ai/generate", "POST", {
        prompt, accountId, platform, variants, feature: "mcp",
      }, AI_TIMEOUT));
    }
  );

  server.tool(
    "ai_copilot",
    "Conversational AI assistant with access to your real analytics data. Ask about performance, strategy, or content.",
    {
      message: z.string().describe("Your question (e.g. 'What content performed best last week?')"),
      accountId: z.string().describe("Account ID for context"),
      platform: z.enum(["threads", "instagram"]).describe("Platform"),
    },
    async ({ message, accountId, platform }) => {
      return respond(await api("/ai/copilot", "POST", { message, accountId, platform }, AI_TIMEOUT));
    }
  );

  server.tool(
    "ai_generate_image",
    "Generate an AI image using DALL-E 3 or Flux. Returns a media ID attachable to posts.",
    {
      prompt: z.string().describe("Image description/prompt"),
      provider: z.enum(["dalle", "flux"]).optional().describe("Provider (default: dalle)"),
      style: z.string().optional().describe("Style (e.g. 'vivid', 'natural')"),
      size: z.string().optional().describe("Size (e.g. '1024x1024', '1024x1792')"),
    },
    async ({ prompt, provider, style, size }) => {
      return respond(await api("/ai/generate-image", "POST", { prompt, provider, style, size }, AI_TIMEOUT));
    }
  );

  server.tool(
    "ai_generate_single",
    "Generate a single post with specific constraints. Use for on-demand content: pair with a trending topic, specific media description, or regenerate a specific content type. Runs through quality gates (regex + LLM judge). Lighter than full batch generation.",
    {
      groupId: z.string().describe("Account group ID for voice profile + strategy"),
      contentType: z.string().optional().describe("Content type: hot_take, question, tribe_check, innuendo, relatable, controversial, list_format, gfe_bait, snap_conversion, fomo_mystery, age_targeting"),
      mediaDescription: z.string().optional().describe("Description of the media that will be attached — AI writes caption to match"),
      trendingTopic: z.string().optional().describe("Trending topic to weave into the post"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Target platform (default: threads)"),
    },
    async ({ groupId, contentType, mediaDescription, trendingTopic, platform }) => {
      return respond(await api("/ai/generate-single", "POST", {
        groupId, contentType, mediaDescription, trendingTopic, platform,
      }, AI_TIMEOUT));
    }
  );

  server.tool(
    "ai_vision_score",
    "Score an image for quality across 5 categories (composition, lighting, color, clarity, engagement potential). Returns 1-100 per category.",
    {
      imageUrl: z.string().describe("Public URL of the image"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform context"),
    },
    async ({ imageUrl, platform }) => {
      return respond(await api("/ai/vision-score", "POST", { imageUrl, platform }, AI_TIMEOUT));
    }
  );

  server.tool(
    "ai_post_autopsy",
    "Analyze why a post performed well or poorly. Returns contributing factors and actionable recommendations.",
    {
      postId: z.string().describe("Post ID to analyze"),
    },
    async ({ postId }) => respond(await api("/posts/autopsy", "POST", { postId }, AI_TIMEOUT))
  );

  server.tool(
    "ai_growth_simulator",
    "Project follower growth based on 90-day history. Returns milestone forecasts, scenario modeling, and strategy suggestions — data-driven pillar recommendations based on real post engagement. Check response.suggestions and inject top items into request_human_approval context to close the analytics→strategy→approval loop.",
    {
      accountId: z.string().describe("Account ID"),
      platform: z.enum(["threads", "instagram"]).describe("Platform"),
    },
    async ({ accountId, platform }) => {
      return respond(await api("/ai/growth-simulator", "POST", { accountId, platform }, AI_TIMEOUT));
    }
  );

  server.tool(
    "ai_feedback",
    "Submit feedback (like/dislike) on AI-generated content to improve future results",
    {
      feature: z.string().describe("AI feature name (e.g. 'generate', 'copilot')"),
      outputText: z.string().describe("The AI output being rated"),
      rating: zNum.describe("1 for like, -1 for dislike"),
      comment: z.string().optional().describe("Optional feedback comment"),
      inputContext: z.string().optional().describe("Original prompt/context"),
    },
    async ({ feature, outputText, rating, comment, inputContext }) => {
      return respond(await api("/ai/feedback", "POST", { feature, outputText, rating, comment, inputContext }));
    }
  );

  server.tool(
    "upsert_ai_config",
    "Set the AI provider, API key, and model for content generation. The API key will be encrypted at rest (AES-256-GCM). Required for AI queue fill and ai_generate tools.",
    {
      provider: z.string().optional().describe("AI provider: 'gemini' (default), 'openai', 'anthropic', 'openrouter', 'xai' (Grok — minimal content filtering)"),
      apiKey: z.string().describe("API key for the AI provider (will be encrypted at rest)"),
      model: z.string().optional().describe("Model name (e.g. 'gemini-2.0-flash', 'gpt-4o')"),
      baseUrl: z.string().optional().describe("Custom base URL for OpenAI-compatible providers"),
    },
    async ({ provider, apiKey, model, baseUrl }) => {
      return respond(await api("/ai/keys", "POST", { provider, apiKey, model, baseUrl }));
    }
  );
};
