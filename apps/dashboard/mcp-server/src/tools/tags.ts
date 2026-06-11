import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "list_tags",
    "List the user's post tag palette",
    {},
    async () => respond(await api("/tags?action=list"))
  );

  server.tool(
    "create_tag",
    "Create or update a tag in the user's palette",
    {
      tagName: z.string().describe("Tag name"),
      tagColor: z.string().optional().describe("Tag color hex code"),
      dryRun: zBool.default(true).describe("Preview create/update (default: true). Must be explicitly set to false to execute."),
    },
    async ({ tagName, tagColor, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Create or update tag", { tagName, tagColor });
      return respond(await api("/tags?action=create", "POST", { tagName, tagColor }));
    }
  );

  server.tool(
    "delete_tag",
    "Delete a tag from the user's palette",
    {
      id: z.string().describe("Tag palette row ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ id, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Delete tag", { id });
      return respond(await api("/tags?action=delete", "POST", { id }));
    }
  );

  server.tool(
    "assign_tag_to_posts",
    "Assign a tag to one or more posts",
    {
      postIds: z.array(z.string()).describe("Post IDs"),
      tagName: z.string().describe("Tag name"),
      tagColor: z.string().optional().describe("Tag color hex code"),
      dryRun: zBool.default(true).describe("Preview assignment (default: true). Must be explicitly set to false to execute."),
    },
    async ({ postIds, tagName, tagColor, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Assign tag to posts", { postIds, tagName, tagColor });
      return respond(await api("/tags?action=assign", "POST", { postIds, tagName, tagColor }));
    }
  );

  server.tool(
    "unassign_tag_from_posts",
    "Remove a tag from one or more posts",
    {
      postIds: z.array(z.string()).describe("Post IDs"),
      tagName: z.string().describe("Tag name"),
      dryRun: zBool.default(true).describe("Preview unassignment (default: true). Must be explicitly set to false to execute."),
    },
    async ({ postIds, tagName, dryRun }) => {
      if (dryRun !== false) return dryRunResponse("Remove tag from posts", { postIds, tagName });
      return respond(await api("/tags?action=unassign", "POST", { postIds, tagName }));
    }
  );

  server.tool(
    "list_post_tags",
    "List tags assigned to one post",
    {
      postId: z.string().describe("Post ID"),
    },
    async ({ postId }) => {
      const params = new URLSearchParams({ action: "by-post", postId });
      return respond(await api(`/tags?${params}`));
    }
  );

  server.tool(
    "get_tag_campaign_analytics",
    "Aggregate campaign metrics for posts with a tag",
    {
      tagName: z.string().describe("Tag name"),
      periodDays: zNum.optional().describe("Lookback period in days (default: 30, max: 365)"),
    },
    async ({ tagName, periodDays }) => {
      const params = new URLSearchParams({ action: "campaign", tagName });
      if (periodDays) params.set("periodDays", String(periodDays));
      return respond(await api(`/tags?${params}`));
    }
  );
};
