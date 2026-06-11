import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  server.tool(
    "upload_media",
    "Register a media file already uploaded to Supabase storage. Returns a media ID to attach to posts. fileUrl must be a Supabase storage URL (SSRF protection). Supports JPEG, PNG, GIF, WebP, MP4, MOV, WebM (max 50MB).",
    {
      fileName: z.string().describe("File name (e.g. 'sunset.jpg')"),
      fileUrl: z.string().describe("Public URL of the file to upload"),
      mimeType: z.string().optional().describe("MIME type (auto-detected if omitted)"),
      groupId: z.string().optional().describe("Account group ID to associate with"),
    },
    async ({ fileName, fileUrl, mimeType, groupId }) => {
      return respond(await api("/media?action=upload", "POST", { fileName, fileUrl, mimeType, groupId }));
    }
  );

  server.tool(
    "bulk_register_media",
    "Register multiple media files already in Supabase storage in one call. Returns media IDs for scheduling. " +
    "Use this for batch operations instead of calling upload_media one by one. Max 500 items per call.",
    {
      items: z.array(z.object({
        fileName: z.string().describe("File name (e.g. 'video.mp4')"),
        fileUrl: z.string().describe("Public Supabase storage URL"),
        mimeType: z.string().optional().describe("MIME type (auto-detected for .mp4)"),
        groupId: z.string().optional().describe("Account group ID"),
      })).describe("Array of media items to register"),
    },
    async ({ items }) => {
      return respond(await api("/media?action=bulk-register", "POST", { items }, 60_000));
    }
  );

  server.tool(
    "get_random_media",
    "Get a random media item from your library (useful for auto-posting with variety)",
    {
      groupId: z.string().optional().describe("Filter by account group"),
      imagesOnly: zBool.optional().describe("Only return images (no video)"),
    },
    async ({ groupId, imagesOnly }) => {
      const params = new URLSearchParams({ action: "random" });
      if (groupId) params.set("groupId", groupId);
      if (imagesOnly) params.set("imagesOnly", "true");
      return respond(await api(`/media?${params}`));
    }
  );

  server.tool(
    "share_media_folder",
    "Toggle sharing for a media folder (makes it available to workspace members)",
    {
      folderId: z.string().describe("Folder ID"),
      isShared: zBool.describe("Share (true) or unshare (false)"),
    },
    async ({ folderId, isShared }) => {
      return respond(await api("/media?action=share", "POST", { folderId, isShared }));
    }
  );

  server.tool(
    "refresh_media_urls",
    "Refresh expired CDN URLs for a post's media attachments",
    {
      postId: z.string().describe("Post ID with expired media URLs"),
    },
    async ({ postId }) => respond(await api("/media?action=refresh", "POST", { postId }))
  );

  server.tool(
    "get_spotlight_queue",
    "List videos staged for Snapchat Spotlight reposting. Videos uploaded via upload_media are automatically flagged. " +
    "Returns download URLs organized by group (model name). Use the URLs to download content for manual Snap posting.",
    {
      groupId: z.string().optional().describe("Filter to a specific group/model"),
      limit: zNum.optional().describe("Max items (default 50, max 200)"),
    },
    async ({ groupId, limit }) => {
      const params = new URLSearchParams({ action: "spotlight-queue" });
      if (groupId) params.set("groupId", groupId);
      if (limit) params.set("limit", String(limit));
      return respond(await api(`/media?${params}`));
    }
  );
};
