import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "search_discover",
    "Search for content, users, or hashtags across Threads and Instagram",
    {
      query: z.string().describe("Search query"),
      platform: z.enum(["threads", "instagram"]).optional().describe("Platform filter"),
    },
    async ({ query, platform }) => {
      return respond(await api("/discover?action=search", "POST", { query, platform }));
    }
  );

  server.tool(
    "get_trends",
    "Search trending content by keyword across Threads/Instagram (uses Threads search API)",
    {
      query: z.string().describe("Search keyword or hashtag"),
      platform: z.enum(["threads", "instagram", "all"]).optional().describe("Platform filter (default: threads)"),
      limit: zNum.optional().describe("Number of results (default: 25, max: 100)"),
    },
    async ({ query, platform, limit }) => {
      return respond(await api("/trends?action=search", "POST", {
        query,
        platform: platform || "threads",
        limit: limit || 25,
      }));
    }
  );

  server.tool(
    "get_inspiration",
    "Fetch content inspiration with AI analysis, personalized to your account",
    {
      query: z.string().optional().describe("Topic or keyword"),
      accountId: z.string().optional().describe("Account ID for personalized results"),
    },
    async ({ query, accountId }) => {
      return respond(await api("/inspiration?action=get-ideas", "POST", { query, accountId }));
    }
  );

  server.tool(
    "ig_hashtag_search",
    "Search for an Instagram hashtag and get its ID for media lookup",
    {
      accountId: z.string().describe("Instagram account ID (for auth)"),
      hashtagName: z.string().describe("Hashtag to search (without #)"),
    },
    async ({ accountId, hashtagName }) => {
      return respond(await api("/instagram/hashtags?action=search", "POST", { accountId, hashtagName }));
    }
  );

  server.tool(
    "ig_hashtag_top_media",
    "Get top-performing media for an Instagram hashtag",
    {
      accountId: z.string().describe("Instagram account ID"),
      hashtagId: z.string().describe("Hashtag ID (from ig_hashtag_search)"),
      limit: zNum.optional().describe("Number of results (max 50, default: 25)"),
    },
    async ({ accountId, hashtagId, limit }) => {
      return respond(await api("/instagram/hashtags?action=top-media", "POST", { accountId, hashtagId, limit }));
    }
  );

  server.tool(
    "ig_hashtag_recent_media",
    "Get most recent media for an Instagram hashtag",
    {
      accountId: z.string().describe("Instagram account ID"),
      hashtagId: z.string().describe("Hashtag ID (from ig_hashtag_search)"),
      limit: zNum.optional().describe("Number of results (max 50, default: 25)"),
    },
    async ({ accountId, hashtagId, limit }) => {
      return respond(await api("/instagram/hashtags?action=recent-media", "POST", { accountId, hashtagId, limit }));
    }
  );

  server.tool(
    "threads_lookup_profile",
    "Look up a Threads user profile by username (bio, follower count, profile metadata)",
    {
      accountId: z.string().describe("Your Threads account ID (for auth)"),
      username: z.string().describe("Username to look up"),
    },
    async ({ accountId, username }) => {
      return respond(await api("/threads/profile", "POST", { accountId, username, action: "lookup" }));
    }
  );

  server.tool(
    "threads_get_user_posts",
    "Get recent posts from a specific Threads user",
    {
      accountId: z.string().describe("Your Threads account ID (for auth)"),
      username: z.string().describe("Username to fetch posts from"),
      limit: zNum.optional().describe("Number of posts (default: 25)"),
    },
    async ({ accountId, username, limit }) => {
      return respond(await api("/threads/profile", "POST", { accountId, username, limit, action: "posts" }));
    }
  );
};
