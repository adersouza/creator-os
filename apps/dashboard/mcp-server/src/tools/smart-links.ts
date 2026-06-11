import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "list_smart_links",
    "[SMART LINKS] List all smart links with click counts. Pro+ tier required.",
    {},
    async () => respond(await api("/smart-links", "POST", { action: "list" }))
  );

  server.tool(
    "create_smart_link",
    "[SMART LINKS] Create a tracked smart link with optional custom code, UTM params, and deep links. Pro+ tier required.",
    {
      targetUrl: z.string().describe("Destination URL"),
      code: z.string().optional().describe("Custom short code (2-20 chars, alphanumeric/dashes). Auto-generated if omitted."),
      title: z.string().optional().describe("Link title for dashboard display"),
      utmSource: z.string().optional().describe("UTM source param"),
      utmMedium: z.string().optional().describe("UTM medium param"),
      utmCampaign: z.string().optional().describe("UTM campaign param"),
      igDeepLink: z.string().optional().describe("Instagram deep link URL (opens IG app directly)"),
      threadsDeepLink: z.string().optional().describe("Threads deep link URL"),
      enableDeepLinks: zBool.optional().describe("Enable platform-specific deep links"),
      postId: z.string().optional().describe("Link to a specific post for attribution tracking"),
      estConversionRate: zNum.optional().describe("Estimated conversion rate 0-1 (for revenue projections)"),
      estConversionValue: zNum.optional().describe("Estimated value per conversion in dollars"),
    },
    async ({ targetUrl, code, title, utmSource, utmMedium, utmCampaign, igDeepLink, threadsDeepLink, enableDeepLinks, postId, estConversionRate, estConversionValue }) => {
      return respond(await api("/smart-links", "POST", {
        action: "create",
        target_url: targetUrl, code, title,
        utm_source: utmSource, utm_medium: utmMedium, utm_campaign: utmCampaign,
        ig_deep_link: igDeepLink, threads_deep_link: threadsDeepLink,
        enable_deep_links: enableDeepLinks,
        post_id: postId,
        est_conversion_rate: estConversionRate,
        est_conversion_value: estConversionValue,
      }));
    }
  );

  server.tool(
    "update_smart_link",
    "[SMART LINKS] Update an existing smart link's target URL, title, UTM params, deep links, or active state.",
    {
      id: z.string().describe("Smart link ID"),
      targetUrl: z.string().optional().describe("New destination URL"),
      title: z.string().optional().describe("New title"),
      isActive: zBool.optional().describe("Enable or disable the link"),
      utmSource: z.string().optional().describe("UTM source param"),
      utmMedium: z.string().optional().describe("UTM medium param"),
      utmCampaign: z.string().optional().describe("UTM campaign param"),
      igDeepLink: z.string().optional().describe("Instagram deep link URL"),
      threadsDeepLink: z.string().optional().describe("Threads deep link URL"),
      enableDeepLinks: zBool.optional().describe("Enable platform-specific deep links"),
      estConversionRate: zNum.optional().describe("Estimated conversion rate 0-1"),
      estConversionValue: zNum.optional().describe("Estimated value per conversion"),
    },
    async ({ id, targetUrl, title, isActive, utmSource, utmMedium, utmCampaign, igDeepLink, threadsDeepLink, enableDeepLinks, estConversionRate, estConversionValue }) => {
      return respond(await api("/smart-links", "POST", {
        action: "update", id,
        target_url: targetUrl, title, is_active: isActive,
        utm_source: utmSource, utm_medium: utmMedium, utm_campaign: utmCampaign,
        ig_deep_link: igDeepLink, threads_deep_link: threadsDeepLink,
        enable_deep_links: enableDeepLinks,
        est_conversion_rate: estConversionRate,
        est_conversion_value: estConversionValue,
      }));
    }
  );

  server.tool(
    "delete_smart_link",
    "[SMART LINKS] Delete a smart link. Use dryRun=true (default) to preview.",
    {
      id: z.string().describe("Smart link ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ id, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete smart link permanently", { id });
      }
      return respond(await api("/smart-links", "POST", { action: "delete", id }));
    }
  );

  server.tool(
    "get_smart_link_analytics",
    "[SMART LINKS] Get detailed analytics for a smart link — clicks, devices, referrers, daily breakdown, geographic data.",
    {
      linkId: z.string().describe("Smart link ID"),
      range: z.enum(["7d", "30d", "90d"]).optional().describe("Time range (default: 7d)"),
    },
    async ({ linkId, range }) => {
      return respond(await api("/smart-links", "POST", {
        action: "analytics", linkId, range,
      }));
    }
  );

  server.tool(
    "enhance_smart_link",
    "[SMART LINKS] Ask the app AI to improve a smart link title, UTM strategy, or tracking setup.",
    {
      targetUrl: z.string().describe("Destination URL to enhance"),
      title: z.string().optional().describe("Current link title"),
      campaignGoal: z.string().optional().describe("Business goal for the link/campaign"),
      platform: z.enum(["threads", "instagram", "both"]).optional().describe("Where this link will be used"),
    },
    async ({ targetUrl, title, campaignGoal, platform }) => {
      return respond(await api("/smart-links", "POST", {
        action: "enhance", targetUrl, title, campaignGoal, platform,
      }, 30_000));
    }
  );

  server.tool(
    "get_smart_link_revenue_summary",
    "[SMART LINKS] Get estimated revenue/conversion summary across tracked smart links.",
    {
      range: z.enum(["7d", "30d", "90d"]).optional().describe("Time range (default: 30d)"),
    },
    async ({ range }) => respond(await api("/smart-links", "POST", { action: "revenue-summary", range }))
  );

  server.tool(
    "get_smart_link_conversions",
    "[SMART LINKS] Get conversion rows for one smart link or all links.",
    {
      linkId: z.string().optional().describe("Smart link ID to filter by"),
      range: z.enum(["7d", "30d", "90d"]).optional().describe("Time range"),
      limit: zNum.optional().describe("Max rows to return"),
    },
    async ({ linkId, range, limit }) => respond(await api("/smart-links", "POST", {
      action: "link-conversions", linkId, range, limit,
    }))
  );

  server.tool(
    "get_post_smart_links",
    "[SMART LINKS] List smart links attributed to a specific post.",
    {
      postId: z.string().describe("Post ID"),
    },
    async ({ postId }) => respond(await api("/smart-links", "POST", { action: "post-links", postId }))
  );

  server.tool(
    "get_revenue_trend",
    "[SMART LINKS] Get 60-day revenue trend with current vs previous period comparison and estimated conversions.",
    {},
    async () => respond(await api("/smart-links", "POST", { action: "revenue-trend" }))
  );

  server.tool(
    "get_post_attribution",
    "[SMART LINKS] Attribute post performance to tracked link clicks/conversions.",
    {
      postId: z.string().optional().describe("Post ID to inspect"),
      range: z.enum(["7d", "30d", "90d"]).optional().describe("Time range"),
    },
    async ({ postId, range }) => respond(await api("/smart-links", "POST", {
      action: "post-attribution", postId, range,
    }))
  );
};
