/**
 * Instagram-specific MCP tools that were missing from the original toolset.
 *
 * Covers: DMs, auto-responders, DM templates, messenger profile, stories,
 * saved media, online followers, collaboration, media deletion, comment
 * toggle, carousel insights, cross-post settings, and bulk operations.
 */

import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, success, dryRunResponse, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  // =========================================================================
  // DIRECT MESSAGES
  // =========================================================================

  server.tool(
    "get_ig_conversations",
    "[IG:DM] List Instagram DM conversations (newest first). Returns conversation IDs with participant info.",
    {
      accountId: z.string().describe("Instagram account ID"),
      limit: zNum.optional().describe("Max conversations (default: 20)"),
    },
    async ({ accountId, limit }) => {
      const params: Record<string, unknown> = { accountId };
      if (limit) params.limit = limit;
      return respond(await api("/instagram/messages?action=conversations", "POST", params));
    }
  );

  server.tool(
    "get_ig_messages",
    "[IG:DM] Get messages within a specific DM conversation.",
    {
      accountId: z.string().describe("Instagram account ID"),
      conversationId: z.string().describe("Conversation ID"),
      limit: zNum.optional().describe("Max messages (default: 20)"),
    },
    async ({ accountId, conversationId, limit }) => {
      const params: Record<string, unknown> = { accountId, conversationId };
      if (limit) params.limit = limit;
      return respond(await api("/instagram/messages?action=messages", "POST", params));
    }
  );

  server.tool(
    "send_ig_message",
    "[IG:DM] Send a text DM to an Instagram user.",
    {
      accountId: z.string().describe("Instagram account ID to send from"),
      recipientId: z.string().describe("Recipient's Instagram-scoped ID (IGSID)"),
      message: z.string().describe("Message text"),
    },
    async ({ accountId, recipientId, message }) => {
      return respond(await api("/instagram/messages?action=send", "POST", {
        accountId, recipientId, message,
      }));
    }
  );

  server.tool(
    "send_ig_media_message",
    "[IG:DM] Send a media file (image/video/audio/file) via DM.",
    {
      accountId: z.string().describe("Instagram account ID"),
      recipientId: z.string().describe("Recipient's Instagram-scoped ID"),
      mediaUrl: z.string().describe("Public URL of the media to send"),
      mediaType: z.enum(["image", "video", "audio", "file"]).describe("Type of media"),
    },
    async ({ accountId, recipientId, mediaUrl, mediaType }) => {
      return respond(await api("/instagram/messages?action=send-media", "POST", {
        accountId, recipientId, mediaUrl, mediaType,
      }));
    }
  );

  server.tool(
    "send_ig_quick_replies",
    "[IG:DM] Send a message with quick reply buttons — perfect for guided conversations.",
    {
      accountId: z.string().describe("Instagram account ID"),
      recipientId: z.string().describe("Recipient's Instagram-scoped ID"),
      message: z.string().describe("Message text"),
      quickReplies: z.array(z.object({
        title: z.string().describe("Button label (max 20 chars)"),
        payload: z.string().describe("Payload string returned when tapped"),
      })).min(1).max(13).describe("Quick reply buttons (max 13)"),
    },
    async ({ accountId, recipientId, message, quickReplies }) => {
      return respond(await api("/instagram/messages?action=quick-replies", "POST", {
        accountId, recipientId, message, quickReplies,
      }));
    }
  );

  server.tool(
    "send_ig_generic_template",
    "[IG:DM] Send a structured template message (card with image, title, buttons).",
    {
      accountId: z.string().describe("Instagram account ID"),
      recipientId: z.string().describe("Recipient's Instagram-scoped ID"),
      elements: z.array(z.object({
        title: z.string().describe("Card title"),
        subtitle: z.string().optional().describe("Card subtitle"),
        imageUrl: z.string().optional().describe("Card image URL"),
        buttons: z.array(z.object({
          type: z.enum(["web_url", "postback"]).describe("Button type"),
          title: z.string().describe("Button label"),
          url: z.string().optional().describe("URL (for web_url type)"),
          payload: z.string().optional().describe("Payload (for postback type)"),
        })).optional().describe("Action buttons"),
      })).min(1).max(10).describe("Template elements"),
    },
    async ({ accountId, recipientId, elements }) => {
      return respond(await api("/instagram/messages?action=generic-template", "POST", {
        accountId, recipientId, elements,
      }));
    }
  );

  server.tool(
    "send_ig_message_reaction",
    "[IG:DM] React to a DM message with an emoji.",
    {
      accountId: z.string().describe("Instagram account ID"),
      recipientId: z.string().describe("Recipient's Instagram-scoped ID"),
      messageId: z.string().describe("Message ID to react to"),
      reaction: z.string().describe("Emoji reaction (e.g. '❤️', '👍')"),
    },
    async ({ accountId, recipientId, messageId, reaction }) => {
      return respond(await api("/instagram/messages?action=reaction", "POST", {
        accountId, recipientId, messageId, reaction,
      }));
    }
  );

  server.tool(
    "send_ig_typing_indicator",
    "[IG:DM] Show typing indicator in a conversation.",
    {
      accountId: z.string().describe("Instagram account ID"),
      recipientId: z.string().describe("Recipient's Instagram-scoped ID"),
    },
    async ({ accountId, recipientId }) => {
      return respond(await api("/instagram/messages?action=sender-action", "POST", {
        accountId, recipientId, senderAction: "typing_on",
      }));
    }
  );

  // =========================================================================
  // AUTO-RESPONDERS
  // =========================================================================

  server.tool(
    "list_ig_auto_responders",
    "[IG:AUTO] List all Instagram DM auto-responder rules.",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api("/instagram/auto-responders?action=list", "POST", { accountId }));
    }
  );

  server.tool(
    "create_ig_auto_responder",
    "[IG:AUTO] Create an Instagram DM auto-responder rule (keyword trigger, first message, mention, story reply).",
    {
      accountId: z.string().describe("Instagram account ID"),
      triggerType: z.enum(["keyword", "first_message", "mention", "story_reply"]).describe("What triggers the auto-reply"),
      triggerKeywords: z.array(z.string()).optional().describe("Keywords to match (for 'keyword' trigger type)"),
      responseType: z.enum(["template", "ai"]).describe("Response type: template (static) or ai (AI-generated)"),
      responseText: z.string().optional().describe("Reply text (for 'template' type)"),
      delaySeconds: zNum.optional().describe("Delay before sending reply (default: 0)"),
      isActive: zBool.optional().describe("Enable immediately (default: true)"),
    },
    async ({ accountId, triggerType, triggerKeywords, responseType, responseText, delaySeconds, isActive }) => {
      return respond(await api("/instagram/auto-responders?action=create", "POST", {
        accountId,
        trigger_type: triggerType,
        trigger_keywords: triggerKeywords,
        response_type: responseType,
        response_text: responseText,
        delay_seconds: delaySeconds,
        is_active: isActive,
      }));
    }
  );

  server.tool(
    "update_ig_auto_responder",
    "[IG:AUTO] Update an existing auto-responder rule.",
    {
      responderId: z.string().describe("Auto-responder rule ID"),
      triggerKeywords: z.array(z.string()).optional().describe("Updated keywords"),
      responseText: z.string().optional().describe("Updated reply text"),
      delaySeconds: zNum.optional().describe("Updated delay"),
    },
    async ({ responderId, triggerKeywords, responseText, delaySeconds }) => {
      return respond(await api("/instagram/auto-responders?action=update", "POST", {
        id: responderId,
        trigger_keywords: triggerKeywords,
        response_text: responseText,
        delay_seconds: delaySeconds,
      }));
    }
  );

  server.tool(
    "toggle_ig_auto_responder",
    "[IG:AUTO] Enable or disable an auto-responder rule.",
    {
      responderId: z.string().describe("Auto-responder rule ID"),
      isActive: zBool.describe("true to enable, false to disable"),
    },
    async ({ responderId, isActive }) => {
      return respond(await api("/instagram/auto-responders?action=toggle", "POST", {
        id: responderId, is_active: isActive,
      }));
    }
  );

  server.tool(
    "delete_ig_auto_responder",
    "[IG:AUTO] Delete an auto-responder rule.",
    {
      responderId: z.string().describe("Auto-responder rule ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ responderId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete Instagram auto-responder rule", { responderId });
      }
      return respond(await api("/instagram/auto-responders?action=delete", "POST", { id: responderId }));
    }
  );

  // =========================================================================
  // DM TEMPLATES
  // =========================================================================

  server.tool(
    "list_ig_dm_templates",
    "[IG:DM] List all saved DM templates.",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api("/instagram/dm-templates?action=list", "POST", { accountId }));
    }
  );

  server.tool(
    "create_ig_dm_template",
    "[IG:DM] Create a reusable DM template.",
    {
      accountId: z.string().describe("Instagram account ID"),
      name: z.string().describe("Template name"),
      content: z.string().describe("Template message text"),
      category: z.string().optional().describe("Category (e.g. 'welcome', 'promo', 'support')"),
    },
    async ({ accountId, name, content, category }) => {
      return respond(await api("/instagram/dm-templates?action=create", "POST", {
        accountId, name, content, category,
      }));
    }
  );

  server.tool(
    "update_ig_dm_template",
    "[IG:DM] Update a DM template.",
    {
      templateId: z.string().describe("Template ID"),
      name: z.string().optional().describe("New name"),
      content: z.string().optional().describe("New message text"),
      category: z.string().optional().describe("New category"),
    },
    async ({ templateId, name, content, category }) => {
      return respond(await api("/instagram/dm-templates?action=update", "POST", {
        id: templateId, name, content, category,
      }));
    }
  );

  server.tool(
    "delete_ig_dm_template",
    "[IG:DM] Delete a DM template.",
    {
      templateId: z.string().describe("Template ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ templateId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete DM template", { templateId });
      }
      return respond(await api("/instagram/dm-templates?action=delete", "POST", { id: templateId }));
    }
  );

  // =========================================================================
  // MESSENGER PROFILE CONFIGURATION
  // =========================================================================

  server.tool(
    "get_ig_persistent_menu",
    "[IG:MESSENGER] Get the persistent menu config for an Instagram account.",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api("/instagram/messenger-profile?action=persistent-menu-get", "POST", { accountId }));
    }
  );

  server.tool(
    "set_ig_persistent_menu",
    "[IG:MESSENGER] Set or update the persistent menu (bottom-of-chat menu with links/actions).",
    {
      accountId: z.string().describe("Instagram account ID"),
      menuItems: z.array(z.object({
        type: z.enum(["web_url", "postback"]).describe("Item type"),
        title: z.string().describe("Menu item label"),
        url: z.string().optional().describe("URL (for web_url type)"),
        payload: z.string().optional().describe("Payload (for postback type)"),
      })).min(1).max(3).describe("Menu items (max 3)"),
    },
    async ({ accountId, menuItems }) => {
      return respond(await api("/instagram/messenger-profile?action=persistent-menu-set", "POST", {
        accountId, menuItems,
      }));
    }
  );

  server.tool(
    "delete_ig_persistent_menu",
    "[IG:MESSENGER] Remove the persistent menu.",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api("/instagram/messenger-profile?action=persistent-menu-delete", "POST", { accountId }));
    }
  );

  server.tool(
    "get_ig_ice_breakers",
    "[IG:MESSENGER] Get ice breaker prompts (conversation starters shown to new DM threads).",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api("/instagram/messenger-profile?action=ice-breakers-get", "POST", { accountId }));
    }
  );

  server.tool(
    "set_ig_ice_breakers",
    "[IG:MESSENGER] Set ice breaker prompts that appear when someone opens a new DM.",
    {
      accountId: z.string().describe("Instagram account ID"),
      iceBreakers: z.array(z.object({
        question: z.string().describe("Prompt text shown to user"),
        payload: z.string().describe("Payload returned when tapped"),
      })).min(1).max(4).describe("Ice breaker prompts (max 4)"),
    },
    async ({ accountId, iceBreakers }) => {
      return respond(await api("/instagram/messenger-profile?action=ice-breakers-set", "POST", {
        accountId, iceBreakers,
      }));
    }
  );

  server.tool(
    "delete_ig_ice_breakers",
    "[IG:MESSENGER] Remove all ice breaker prompts.",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api("/instagram/messenger-profile?action=ice-breakers-delete", "POST", { accountId }));
    }
  );

  server.tool(
    "set_ig_welcome_message",
    "[IG:MESSENGER] Create a welcome message flow (auto-greets new DM conversations).",
    {
      accountId: z.string().describe("Instagram account ID"),
      message: z.string().describe("Welcome message text"),
    },
    async ({ accountId, message }) => {
      return respond(await api("/instagram/messenger-profile?action=welcome-flows-create", "POST", {
        accountId, message,
      }));
    }
  );

  server.tool(
    "get_ig_welcome_messages",
    "[IG:MESSENGER] List all welcome message flows.",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api("/instagram/messenger-profile?action=welcome-flows-list", "POST", { accountId }));
    }
  );

  server.tool(
    "delete_ig_welcome_message",
    "[IG:MESSENGER] Delete a welcome message flow.",
    {
      accountId: z.string().describe("Instagram account ID"),
      flowId: z.string().describe("Welcome flow ID"),
    },
    async ({ accountId, flowId }) => {
      return respond(await api("/instagram/messenger-profile?action=welcome-flows-delete", "POST", {
        accountId, flowId,
      }));
    }
  );

  // =========================================================================
  // STORIES
  // =========================================================================

  server.tool(
    "get_ig_stories",
    "[IG:STORIES] Get active Instagram stories for an account (stories expire after 24h).",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api(`/instagram?action=stories&accountId=${accountId}`));
    }
  );

  server.tool(
    "get_ig_story_insights",
    "[IG:STORIES] Get insights for a specific Instagram story (impressions, reach, exits, replies, taps).",
    {
      accountId: z.string().describe("Instagram account ID"),
      mediaId: z.string().describe("Story media ID"),
    },
    async ({ accountId, mediaId }) => {
      return respond(await api(`/instagram?action=stories&accountId=${accountId}&storyMediaId=${mediaId}&insights=true`));
    }
  );

  // =========================================================================
  // SAVED MEDIA, ONLINE FOLLOWERS, COLLABORATION
  // =========================================================================

  server.tool(
    "get_ig_saved_media",
    "[IG:CONTENT] Get Instagram bookmarked/saved posts for content research and inspiration.",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api(`/instagram?action=saved-media&accountId=${accountId}`));
    }
  );

  server.tool(
    "get_ig_online_followers",
    "[IG:AUDIENCE] Get when your followers are online — use for optimal posting time analysis.",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api(`/instagram?action=online-followers&accountId=${accountId}`));
    }
  );

  server.tool(
    "list_ig_collaboration_invites",
    "[IG:COLLAB] List pending collaboration invites (requires Facebook Login). Time-sensitive — invites expire.",
    {
      accountId: z.string().describe("Instagram account ID"),
    },
    async ({ accountId }) => {
      return respond(await api("/instagram/collaboration?action=list", "POST", { accountId }));
    }
  );

  server.tool(
    "accept_ig_collaboration",
    "[IG:COLLAB] Accept a collaboration invite. The post will appear on both profiles.",
    {
      accountId: z.string().describe("Instagram account ID"),
      inviteId: z.string().describe("Collaboration invite ID"),
    },
    async ({ accountId, inviteId }) => {
      return respond(await api("/instagram/collaboration?action=accept", "POST", { accountId, inviteId }));
    }
  );

  server.tool(
    "decline_ig_collaboration",
    "[IG:COLLAB] Decline a collaboration invite.",
    {
      accountId: z.string().describe("Instagram account ID"),
      inviteId: z.string().describe("Collaboration invite ID"),
    },
    async ({ accountId, inviteId }) => {
      return respond(await api("/instagram/collaboration?action=decline", "POST", { accountId, inviteId }));
    }
  );

  // =========================================================================
  // MEDIA MANAGEMENT
  // =========================================================================

  server.tool(
    "delete_ig_media",
    "[IG:MEDIA] Delete a published Instagram post. Max 100 deletions/day per Meta API. Use dryRun=true (default) to preview.",
    {
      accountId: z.string().describe("Instagram account ID"),
      mediaId: z.string().describe("Instagram media/post ID to delete"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ accountId, mediaId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete Instagram media permanently", { accountId, mediaId });
      }
      return respond(await api("/instagram/media?action=delete", "POST", { accountId, mediaId }));
    }
  );

  server.tool(
    "list_ig_collaborative_media",
    "[IG MEDIA] List collaborative media for an Instagram account.",
    {
      accountId: z.string().describe("Instagram account ID"),
      limit: zNum.optional().describe("Max media items, default API behavior, max 100"),
    },
    async ({ accountId, limit }) => respond(await api("/instagram/media?action=collaborative-list", "POST", { accountId, limit }))
  );

  server.tool(
    "search_ig_collaborative_media",
    "[IG MEDIA] Look up one collaborative media item by media ID.",
    {
      accountId: z.string().describe("Instagram account ID"),
      mediaId: z.string().describe("Instagram media ID"),
    },
    async ({ accountId, mediaId }) => respond(await api("/instagram/media?action=collaborative-search", "POST", { accountId, mediaId }))
  );

  server.tool(
    "like_ig_media_or_comment",
    "[IG ENGAGEMENT] Like an Instagram media item or comment from a connected account.",
    {
      accountId: z.string().describe("Instagram account ID"),
      mediaId: z.string().optional().describe("Instagram media ID to like"),
      commentId: z.string().optional().describe("Instagram comment ID to like"),
    },
    async ({ accountId, mediaId, commentId }) => respond(await api("/instagram/media?action=like", "POST", { accountId, mediaId, commentId }))
  );

  server.tool(
    "unlike_ig_media_or_comment",
    "[IG ENGAGEMENT] Remove a like from an Instagram media item or comment.",
    {
      accountId: z.string().describe("Instagram account ID"),
      mediaId: z.string().optional().describe("Instagram media ID to unlike"),
      commentId: z.string().optional().describe("Instagram comment ID to unlike"),
    },
    async ({ accountId, mediaId, commentId }) => respond(await api("/instagram/media?action=unlike", "POST", { accountId, mediaId, commentId }))
  );

  server.tool(
    "toggle_ig_comments",
    "[IG:MODERATION] Enable or disable comments on a specific Instagram post.",
    {
      accountId: z.string().describe("Instagram account ID"),
      mediaId: z.string().describe("Instagram media/post ID"),
      enabled: zBool.describe("true to enable comments, false to disable"),
    },
    async ({ accountId, mediaId, enabled }) => {
      return respond(await api("/instagram/comments?action=toggle-comments", "POST", {
        accountId, mediaId, enabled,
      }));
    }
  );

  server.tool(
    "delete_ig_comment",
    "[IG:MODERATION] Delete a comment on an Instagram post.",
    {
      accountId: z.string().describe("Instagram account ID"),
      commentId: z.string().describe("Comment ID to delete"),
    },
    async ({ accountId, commentId }) => {
      return respond(await api("/instagram/comments?action=delete", "POST", { accountId, commentId }));
    }
  );

  // =========================================================================
  // BULK OPERATIONS
  // =========================================================================

  server.tool(
    "bulk_delete_posts",
    "[BULK] Delete multiple published or scheduled posts. Max 50 per call. Use dryRun=true (default) to preview.",
    {
      posts: z.array(z.object({
        postId: z.string().describe("Post ID"),
        accountId: z.string().describe("Account the post belongs to"),
      })).min(1).max(50).describe("Posts to delete (max 50)"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true)"),
    },
    async ({ posts, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse(`Delete ${posts.length} posts permanently`, { posts });
      }
      const results: { postId: string; ok: boolean; error?: string }[] = [];
      for (const p of posts) {
        const result = await api("/posts?action=delete", "POST", { postId: p.postId, accountId: p.accountId });
        results.push({
          postId: p.postId,
          ok: result.ok,
          error: result.ok ? undefined : (result as { ok: false; error: { message: string } }).error?.message,
        });
      }
      const succeeded = results.filter(r => r.ok).length;
      return success({ deleted: succeeded, failed: results.length - succeeded, results });
    }
  );

  server.tool(
    "bulk_hide_ig_comments",
    "[BULK:IG] Hide or unhide multiple Instagram comments at once. Max 50 per call.",
    {
      accountId: z.string().describe("Instagram account ID"),
      commentIds: z.array(z.string()).min(1).max(50).describe("Comment IDs to hide/unhide (max 50)"),
      hide: zBool.describe("true to hide, false to unhide"),
    },
    async ({ accountId, commentIds, hide }) => {
      const results: { commentId: string; ok: boolean; error?: string }[] = [];
      for (const commentId of commentIds) {
        const result = await api("/instagram/comments?action=hide", "POST", { accountId, commentId, hide });
        results.push({
          commentId,
          ok: result.ok,
          error: result.ok ? undefined : (result as { ok: false; error: { message: string } }).error?.message,
        });
      }
      const succeeded = results.filter(r => r.ok).length;
      return success({ action: hide ? "hidden" : "unhidden", succeeded, failed: results.length - succeeded, results });
    }
  );

  server.tool(
    "bulk_delete_ig_comments",
    "[BULK:IG] Delete multiple Instagram comments. Max 50 per call. Use dryRun=true (default) to preview.",
    {
      accountId: z.string().describe("Instagram account ID"),
      commentIds: z.array(z.string()).min(1).max(50).describe("Comment IDs to delete (max 50)"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true)"),
    },
    async ({ accountId, commentIds, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse(`Delete ${commentIds.length} Instagram comments`, { accountId, commentIds });
      }
      const results: { commentId: string; ok: boolean; error?: string }[] = [];
      for (const commentId of commentIds) {
        const result = await api("/instagram/comments?action=delete", "POST", { accountId, commentId });
        results.push({
          commentId,
          ok: result.ok,
          error: result.ok ? undefined : (result as { ok: false; error: { message: string } }).error?.message,
        });
      }
      const succeeded = results.filter(r => r.ok).length;
      return success({ deleted: succeeded, failed: results.length - succeeded, results });
    }
  );

  server.tool(
    "bulk_reply_ig_comments",
    "[BULK:IG] Reply to multiple Instagram comments in one call. Max 20 per call (respects Meta rate limits).",
    {
      accountId: z.string().describe("Instagram account ID"),
      replies: z.array(z.object({
        commentId: z.string().describe("Comment ID to reply to"),
        message: z.string().describe("Reply text"),
      })).min(1).max(20).describe("Replies to send (max 20)"),
    },
    async ({ accountId, replies }) => {
      const results: { commentId: string; ok: boolean; error?: string }[] = [];
      for (const r of replies) {
        const result = await api("/instagram/comments?action=reply", "POST", {
          accountId, commentId: r.commentId, message: r.message,
        });
        results.push({
          commentId: r.commentId,
          ok: result.ok,
          error: result.ok ? undefined : (result as { ok: false; error: { message: string } }).error?.message,
        });
      }
      const succeeded = results.filter(r => r.ok).length;
      return success({ replied: succeeded, failed: results.length - succeeded, results });
    }
  );

  server.tool(
    "bulk_toggle_evergreen",
    "[BULK] Mark or unmark multiple posts as evergreen. Max 50 per call.",
    {
      posts: z.array(z.object({
        postId: z.string().describe("Post ID"),
        isEvergreen: zBool.describe("true to mark, false to unmark"),
      })).min(1).max(50).describe("Posts to toggle (max 50)"),
    },
    async ({ posts }) => {
      const results: { postId: string; ok: boolean; error?: string }[] = [];
      for (const p of posts) {
        const result = await api("/posts/evergreen", "POST", { action: "toggle", postId: p.postId, isEvergreen: p.isEvergreen });
        results.push({
          postId: p.postId,
          ok: result.ok,
          error: result.ok ? undefined : (result as { ok: false; error: { message: string } }).error?.message,
        });
      }
      const succeeded = results.filter(r => r.ok).length;
      return success({ toggled: succeeded, failed: results.length - succeeded, results });
    }
  );

  server.tool(
    "bulk_delete_queue_items",
    "[BULK] Delete multiple auto-post queue items. Max 50 per call. Use dryRun=true (default) to preview.",
    {
      queueItemIds: z.array(z.string()).min(1).max(50).describe("Queue item IDs to delete (max 50)"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true)"),
    },
    async ({ queueItemIds, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse(`Delete ${queueItemIds.length} queue items`, { queueItemIds });
      }
      const results: { id: string; ok: boolean; error?: string }[] = [];
      for (const id of queueItemIds) {
        const result = await api("/auto-post?action=delete-queue-item", "POST", { queueItemId: id });
        results.push({
          id,
          ok: result.ok,
          error: result.ok ? undefined : (result as { ok: false; error: { message: string } }).error?.message,
        });
      }
      const succeeded = results.filter(r => r.ok).length;
      return success({ deleted: succeeded, failed: results.length - succeeded, results });
    }
  );

  server.tool(
    "bulk_reschedule_posts",
    "[BULK] Reschedule multiple posts at once — shift a week of content. Max 50 per call.",
    {
      posts: z.array(z.object({
        postId: z.string().describe("Post ID"),
        scheduledFor: z.string().describe("New ISO 8601 datetime"),
      })).min(1).max(50).describe("Posts to reschedule (max 50)"),
    },
    async ({ posts }) => {
      const results: { postId: string; ok: boolean; error?: string }[] = [];
      for (const p of posts) {
        const result = await api("/posts?action=reschedule", "POST", { postId: p.postId, scheduledFor: p.scheduledFor });
        results.push({
          postId: p.postId,
          ok: result.ok,
          error: result.ok ? undefined : (result as { ok: false; error: { message: string } }).error?.message,
        });
      }
      const succeeded = results.filter(r => r.ok).length;
      return success({ rescheduled: succeeded, failed: results.length - succeeded, results });
    }
  );

  server.tool(
    "bulk_toggle_ig_comments",
    "[BULK:IG] Enable or disable comments on multiple Instagram posts. Max 50 per call.",
    {
      accountId: z.string().describe("Instagram account ID"),
      posts: z.array(z.object({
        mediaId: z.string().describe("Instagram media/post ID"),
        enabled: zBool.describe("true to enable, false to disable"),
      })).min(1).max(50).describe("Posts to toggle comments on (max 50)"),
    },
    async ({ accountId, posts }) => {
      const results: { mediaId: string; ok: boolean; error?: string }[] = [];
      for (const p of posts) {
        const result = await api("/instagram/comments?action=toggle-comments", "POST", {
          accountId, mediaId: p.mediaId, enabled: p.enabled,
        });
        results.push({
          mediaId: p.mediaId,
          ok: result.ok,
          error: result.ok ? undefined : (result as { ok: false; error: { message: string } }).error?.message,
        });
      }
      const succeeded = results.filter(r => r.ok).length;
      return success({ toggled: succeeded, failed: results.length - succeeded, results });
    }
  );

  server.tool(
    "bulk_reply_to_messages",
    "[BULK] Reply to multiple Threads comments/mentions in one call. Max 20 per call.",
    {
      replies: z.array(z.object({
        accountId: z.string().describe("Account to reply from"),
        replyToId: z.string().describe("Message ID to reply to"),
        content: z.string().describe("Reply text"),
      })).min(1).max(20).describe("Replies to send (max 20)"),
    },
    async ({ replies }) => {
      const results: { replyToId: string; ok: boolean; error?: string }[] = [];
      for (const r of replies) {
        const result = await api("/replies?action=post", "POST", {
          accountId: r.accountId, replyToId: r.replyToId, content: r.content,
        });
        results.push({
          replyToId: r.replyToId,
          ok: result.ok,
          error: result.ok ? undefined : (result as { ok: false; error: { message: string } }).error?.message,
        });
      }
      const succeeded = results.filter(r => r.ok).length;
      return success({ replied: succeeded, failed: results.length - succeeded, results });
    }
  );

  server.tool(
    "bulk_delete_ig_media",
    "[BULK:IG] Delete multiple published Instagram posts. Max 20 per call (Meta rate limit: 100/day). Use dryRun=true (default) to preview.",
    {
      accountId: z.string().describe("Instagram account ID"),
      mediaIds: z.array(z.string()).min(1).max(20).describe("Media IDs to delete (max 20)"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true)"),
    },
    async ({ accountId, mediaIds, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse(`Delete ${mediaIds.length} Instagram posts`, { accountId, mediaIds });
      }
      const results: { mediaId: string; ok: boolean; error?: string }[] = [];
      for (const mediaId of mediaIds) {
        const result = await api("/instagram/media?action=delete", "POST", { accountId, mediaId });
        results.push({
          mediaId,
          ok: result.ok,
          error: result.ok ? undefined : (result as { ok: false; error: { message: string } }).error?.message,
        });
      }
      const succeeded = results.filter(r => r.ok).length;
      return success({ deleted: succeeded, failed: results.length - succeeded, results });
    }
  );
};
