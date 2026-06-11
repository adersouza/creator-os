import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "get_composer_health_pills",
    "Get unresolved health signals for accounts shown in the composer",
    {
      accountIds: z.array(z.string()).describe("Account IDs to inspect, max 50"),
    },
    async ({ accountIds }) => {
      const qs = new URLSearchParams({ account_ids: accountIds.join(",") });
      return respond(await api(`/composer?action=health-pills&${qs}`));
    }
  );

  server.tool(
    "critique_composer_caption",
    "AI-score a draft caption for likely engagement and improvement tips",
    {
      caption: z.string().describe("Draft caption to critique"),
      accountId: z.string().optional().describe("Optional account ID for account-aware critique"),
    },
    async ({ caption, accountId }) => {
      return respond(await api("/composer?action=critique", "POST", {
        caption,
        account_id: accountId,
      }, 30_000));
    }
  );

  server.tool(
    "generate_composer_variants",
    "Generate and save A/B/C caption variants for a draft",
    {
      caption: z.string().describe("Base caption"),
      accountId: z.string().optional().describe("Optional account ID"),
      persona: z.string().optional().describe("Optional voice/persona hint"),
      draftId: z.string().optional().describe("Draft ID to attach variants to"),
    },
    async ({ caption, accountId, persona, draftId }) => {
      return respond(await api("/composer?action=variants", "POST", {
        mode: "generate",
        caption,
        account_id: accountId,
        persona,
        draft_id: draftId,
      }, 30_000));
    }
  );

  server.tool(
    "list_composer_variants",
    "List saved A/B/C caption variants for a draft",
    {
      draftId: z.string().describe("Draft ID"),
    },
    async ({ draftId }) => {
      const qs = new URLSearchParams({ action: "variants", draft_id: draftId });
      return respond(await api(`/composer?${qs}`));
    }
  );

  server.tool(
    "get_composer_variant_live_results",
    "Get live result metrics for a promoted composer variant",
    {
      postId: z.string().describe("Published post ID"),
    },
    async ({ postId }) => {
      const qs = new URLSearchParams({ action: "variants", mode: "live-results", post_id: postId });
      return respond(await api(`/composer?${qs}`));
    }
  );

  server.tool(
    "promote_composer_variant",
    "Mark a composer variant as promoted",
    {
      id: z.string().describe("Variant ID"),
    },
    async ({ id }) => {
      return respond(await api("/composer?action=variants", "POST", { mode: "promote", id }));
    }
  );

  server.tool(
    "list_composer_diffs",
    "List platform-specific caption diffs for a draft",
    {
      draftId: z.string().describe("Draft ID"),
    },
    async ({ draftId }) => {
      const qs = new URLSearchParams({ action: "diffs", draft_id: draftId });
      return respond(await api(`/composer?${qs}`));
    }
  );

  server.tool(
    "create_composer_diff",
    "Create a platform-specific caption diff for a draft",
    {
      draftId: z.string().describe("Draft ID"),
      platform: z.enum(["threads", "instagram"]).describe("Target platform"),
      masterCaption: z.string().describe("Master caption"),
      variantCaption: z.string().describe("Platform-specific variant caption"),
    },
    async ({ draftId, platform, masterCaption, variantCaption }) => {
      return respond(await api("/composer?action=diffs", "POST", {
        draft_id: draftId,
        platform,
        master_caption: masterCaption,
        variant_caption: variantCaption,
      }));
    }
  );

  server.tool(
    "resolve_composer_diff",
    "Update the status of a composer caption diff",
    {
      id: z.string().describe("Diff ID"),
      status: z.enum(["resolved", "dismissed", "unresolved"]).describe("New diff status"),
    },
    async ({ id, status }) => {
      return respond(await api("/composer?action=diffs", "POST", { id, status }));
    }
  );

  server.tool(
    "get_voice_context_file",
    "Get the editable voice context file for an account group",
    {
      accountGroupId: z.string().describe("Account group ID"),
    },
    async ({ accountGroupId }) => {
      const qs = new URLSearchParams({ action: "voice-file", account_group_id: accountGroupId });
      return respond(await api(`/composer?${qs}`));
    }
  );

  server.tool(
    "update_voice_context_file",
    "Update the editable voice context file for an account group",
    {
      accountGroupId: z.string().describe("Account group ID"),
      content: z.string().describe("Voice file content"),
      bannedPatterns: z.array(z.string()).optional().describe("Patterns to avoid"),
      audience: z.string().optional().describe("Target audience description"),
      topPatterns: z.array(z.any()).optional().describe("Top voice/content patterns"),
    },
    async ({ accountGroupId, content, bannedPatterns, audience, topPatterns }) => {
      const qs = new URLSearchParams({ action: "voice-file", account_group_id: accountGroupId });
      return respond(await api(`/composer?${qs}`, "PUT", {
        account_group_id: accountGroupId,
        content,
        banned_patterns: bannedPatterns,
        audience,
        top_patterns: topPatterns,
      }));
    }
  );

  server.tool(
    "log_composer_ai_action",
    "Record an AI action taken in the composer surface",
    {
      actionType: z.string().describe("Action type label"),
      inputText: z.string().optional().describe("Input text"),
      outputText: z.string().optional().describe("Output text"),
      accountId: z.string().optional().describe("Related account ID"),
      modelUsed: z.string().optional().describe("Model used"),
      provider: z.string().optional().describe("Provider used"),
      latencyMs: zNum.optional().describe("Latency in milliseconds"),
      metadata: z.any().optional().describe("Optional JSON metadata"),
    },
    async ({ actionType, inputText, outputText, accountId, modelUsed, provider, latencyMs, metadata }) => {
      return respond(await api("/composer?action=ai-action-log", "POST", {
        action_type: actionType,
        input_text: inputText,
        output_text: outputText,
        account_id: accountId,
        model_used: modelUsed,
        provider,
        latency_ms: latencyMs,
        metadata,
      }));
    }
  );
};
