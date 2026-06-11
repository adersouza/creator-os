import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  // -- Link in Bio Pages --

  server.tool(
    "list_link_pages",
    "List all Link in Bio pages",
    {},
    async () => respond(await api("/links", "POST", { action: "list-pages" }))
  );

  server.tool(
    "create_link_page",
    "Create a new Link in Bio page with a custom slug",
    {
      slug: z.string().describe("URL slug (e.g. 'mypage' → juno33.com/go/mypage)"),
      title: z.string().optional().describe("Page title"),
      bio: z.string().optional().describe("Bio text"),
      backgroundColor: z.string().optional().describe("Background hex color"),
      brandColor: z.string().optional().describe("Brand accent hex color"),
    },
    async ({ slug, title, bio, backgroundColor, brandColor }) => {
      return respond(await api("/links", "POST", { action: "create-page",
        slug, title, bio, backgroundColor, brandColor,
      }));
    }
  );

  server.tool(
    "update_link_page",
    "Update a Link in Bio page's title, bio, or colors",
    {
      pageId: z.string().describe("Page ID"),
      title: z.string().optional().describe("New title"),
      bio: z.string().optional().describe("New bio"),
      backgroundColor: z.string().optional().describe("New background hex color"),
      brandColor: z.string().optional().describe("New brand hex color"),
    },
    async ({ pageId, title, bio, backgroundColor, brandColor }) => {
      return respond(await api("/links", "POST", { action: "update-page",
        pageId, title, bio, backgroundColor, brandColor,
      }));
    }
  );

  server.tool(
    "delete_link_page",
    "Delete a Link in Bio page. Use dryRun=true (default) to preview.",
    {
      pageId: z.string().describe("Page ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ pageId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete Link in Bio page and all its links", { pageId });
      }
      return respond(await api("/links", "POST", { action: "delete-page", pageId }));
    }
  );

  server.tool(
    "get_link_page_analytics",
    "Get analytics for a Link in Bio page (views, clicks, sources, devices)",
    {
      pageId: z.string().describe("Page ID"),
      days: zNum.optional().describe("Period in days (default: 30)"),
    },
    async ({ pageId, days }) => {
      const qs = new URLSearchParams({ pageId });
      if (days) qs.set("days", String(days));
      return respond(await api(`/links?${qs}`, "POST", { action: "analytics" }));
    }
  );

  // -- Individual Links --

  server.tool(
    "add_bio_link",
    "Add a link to a Link in Bio page",
    {
      pageId: z.string().describe("Page ID"),
      title: z.string().describe("Link title"),
      url: z.string().describe("Link URL"),
      icon: z.string().optional().describe("Icon name"),
      isPrimary: zBool.optional().describe("Primary link styling"),
      platform: z.string().optional().describe("Platform name (e.g. 'twitter', 'youtube')"),
    },
    async ({ pageId, title, url, icon, isPrimary, platform }) => {
      return respond(await api("/links", "POST", { action: "add-link",
        pageId, title, url, icon, isPrimary, platform,
      }));
    }
  );

  server.tool(
    "update_bio_link",
    "Update an existing link on a Link in Bio page",
    {
      linkId: z.string().describe("Link ID"),
      pageId: z.string().describe("Page ID"),
      title: z.string().optional().describe("New title"),
      url: z.string().optional().describe("New URL"),
      icon: z.string().optional().describe("New icon"),
      isPrimary: zBool.optional().describe("Primary link styling"),
    },
    async ({ linkId, pageId, title, url, icon, isPrimary }) => {
      return respond(await api("/links", "POST", { action: "update-link",
        linkId, pageId, title, url, icon, isPrimary,
      }));
    }
  );

  server.tool(
    "reorder_bio_links",
    "Reorder links on a Link in Bio page",
    {
      pageId: z.string().describe("Page ID"),
      linkIds: z.array(z.string()).describe("Link IDs in desired order"),
    },
    async ({ pageId, linkIds }) => {
      return respond(await api("/links", "POST", { action: "reorder", pageId, linkIds }));
    }
  );

  server.tool(
    "delete_bio_link",
    "Remove a link from a Link in Bio page. Use dryRun=true (default) to preview.",
    {
      linkId: z.string().describe("Link ID"),
      pageId: z.string().describe("Page ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ linkId, pageId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete link from bio page", { linkId, pageId });
      }
      return respond(await api("/links", "POST", { action: "delete-link", linkId, pageId }));
    }
  );

  // -- URL Shortener --

  server.tool(
    "shorten_url",
    "Create a shortened/tracked URL (juno33.com/go/xxx redirect)",
    {
      url: z.string().describe("URL to shorten"),
    },
    async ({ url }) => {
      const result = await api("/smart-links", "POST", { action: "create", target_url: url });
      if (!result.ok) return respond(result);
      const link = (result.data as any)?.link;
      const shortUrl = link?.code ? `https://juno33.com/api/go/${link.code}` : null;
      return respond({ ok: true, data: { ...link, short_url: shortUrl } });
    }
  );
};
