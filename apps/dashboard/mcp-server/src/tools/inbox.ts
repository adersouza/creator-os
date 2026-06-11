import { z } from "zod";
import type { ToolRegistrar } from "../helpers.js";
import { api, respond, dryRunResponse, zBool, zNum } from "../helpers.js";

export const register: ToolRegistrar = (server) => {
  // -- Post Comments (per-post engagement feedback) --

  server.tool(
    "get_post_comments",
    "[ENGAGEMENT] Get comments/replies on a specific post. Use after publishing to close the feedback loop — see what people are saying, detect sentiment patterns, and inform future content. Returns local DB data (synced by crons).",
    {
      postId: z.string().describe("Post ID to get comments for"),
      platform: z.enum(["threads", "instagram"]).describe("Platform the post was published on"),
      limit: zNum.optional().describe("Max comments to return (default 50, max 100)"),
    },
    async ({ postId, platform, limit }) => {
      const params = new URLSearchParams({ postId, platform });
      if (limit) params.set("limit", String(limit));
      return respond(await api(`/posts?action=comments&${params}`));
    }
  );

  // -- Unified Inbox --

  server.tool(
    "get_inbox",
    "[INBOX] Get unified inbox merging IG comments/mentions and Threads replies/mentions with priority sorting",
    {
      filter: z.enum(["all", "comments", "replies", "mentions"]).optional().describe("Filter type (default: all)"),
      limit: zNum.optional().describe("Number of items (default: 20)"),
    },
    async ({ filter, limit }) => {
      const params = new URLSearchParams();
      params.set("action", "unified");
      if (filter) params.set("filter", filter);
      if (limit) params.set("limit", String(limit));
      return respond(await api(`/inbox?${params}`));
    }
  );

  server.tool(
    "mark_inbox_message_read",
    "[INBOX] Mark a unified inbox item as read.",
    {
      messageId: z.string().describe("Unified inbox message ID, e.g. ig_comment_... or threads_reply_..."),
    },
    async ({ messageId }) => respond(await api("/inbox?action=mark-read", "POST", { messageId }))
  );

  server.tool(
    "list_inbox_assignments",
    "[INBOX] List team assignments for inbox items in a workspace.",
    {
      workspaceId: z.string().describe("Workspace ID"),
    },
    async ({ workspaceId }) => respond(await api(`/inbox?action=assign&workspaceId=${encodeURIComponent(workspaceId)}`, "GET"))
  );

  server.tool(
    "assign_inbox_message",
    "[INBOX] Assign an inbox item to a team member.",
    {
      workspaceId: z.string().describe("Workspace ID"),
      source: z.enum(["threads_reply", "threads_mention", "ig_comment", "ig_mention", "ig_dm"]).describe("Inbox item source"),
      messageId: z.string().describe("Source message ID"),
      assignedTo: z.string().describe("User ID to assign to"),
      note: z.string().optional().describe("Optional assignment note"),
    },
    async ({ workspaceId, source, messageId, assignedTo, note }) => {
      return respond(await api("/inbox?action=assign", "POST", { workspaceId, source, messageId, assignedTo, note }));
    }
  );

  server.tool(
    "unassign_inbox_message",
    "[INBOX] Remove an inbox assignment.",
    {
      workspaceId: z.string().describe("Workspace ID"),
      source: z.enum(["threads_reply", "threads_mention", "ig_comment", "ig_mention", "ig_dm"]).describe("Inbox item source"),
      messageId: z.string().describe("Source message ID"),
    },
    async ({ workspaceId, source, messageId }) => respond(await api("/inbox?action=assign", "DELETE", { workspaceId, source, messageId }))
  );

  server.tool(
    "get_inbox_ai_suggestions",
    "[INBOX] Fetch AI reply suggestions for one or more conversation keys.",
    {
      conversationKeys: z.array(z.string()).min(1).max(100).describe("Conversation keys to fetch suggestions for"),
    },
    async ({ conversationKeys }) => {
      const keys = conversationKeys.map((key) => key.trim()).filter(Boolean).join(",");
      return respond(await api(`/inbox?action=suggestions&conversation_keys=${encodeURIComponent(keys)}`, "GET"));
    }
  );

  server.tool(
    "update_inbox_ai_suggestion",
    "[INBOX] Accept/reject or regenerate an AI reply suggestion.",
    {
      conversationKey: z.string().describe("Conversation key"),
      suggestionId: z.string().optional().describe("Suggestion ID, required when accepting/rejecting"),
      status: z.enum(["accepted", "rejected"]).optional().describe("Suggestion review status"),
      regenerate: zBool.optional().describe("Regenerate a fresh suggestion for this conversation"),
    },
    async ({ conversationKey, suggestionId, status, regenerate }) => {
      return respond(await api("/inbox?action=suggestions", "POST", {
        conversation_key: conversationKey,
        id: suggestionId,
        status,
        regenerate,
      }, 30_000));
    }
  );

  server.tool(
    "check_reply_contradiction",
    "[INBOX] Check whether a draft reply contradicts the latest replies in a conversation.",
    {
      composerText: z.string().describe("Draft reply text"),
      lastReplies: z.array(z.string()).describe("Recent replies in the conversation, oldest to newest"),
    },
    async ({ composerText, lastReplies }) => respond(await api("/inbox?action=check-contradiction", "POST", {
      composer_text: composerText,
      last_replies: lastReplies,
    }, 30_000))
  );

  server.tool(
    "reply_to_message",
    "Reply to a comment, mention, or thread reply in your inbox",
    {
      accountId: z.string().describe("Account to reply from"),
      replyToId: z.string().describe("Message ID to reply to"),
      content: z.string().describe("Reply text"),
    },
    async ({ accountId, replyToId, content }) => {
      return respond(await api("/replies?action=post", "POST", { accountId, replyToId, content }));
    }
  );

  // -- Instagram Comments --

  server.tool(
    "list_ig_comments",
    "List comments on a specific Instagram post",
    {
      accountId: z.string().describe("Instagram account ID"),
      mediaId: z.string().describe("Instagram media/post ID"),
    },
    async ({ accountId, mediaId }) => {
      return respond(await api("/instagram/comments?action=list", "POST", { accountId, mediaId }));
    }
  );

  server.tool(
    "reply_to_ig_comment",
    "Reply publicly to an Instagram comment",
    {
      accountId: z.string().describe("Instagram account ID"),
      commentId: z.string().describe("Comment ID to reply to"),
      message: z.string().describe("Reply text"),
    },
    async ({ accountId, commentId, message }) => {
      return respond(await api("/instagram/comments?action=reply", "POST", { accountId, commentId, message }));
    }
  );

  server.tool(
    "hide_ig_comment",
    "Hide or unhide an Instagram comment",
    {
      accountId: z.string().describe("Instagram account ID"),
      commentId: z.string().describe("Comment ID"),
      hide: zBool.describe("true to hide, false to unhide"),
    },
    async ({ accountId, commentId, hide }) => {
      return respond(await api("/instagram/comments?action=hide", "POST", { accountId, commentId, hide }));
    }
  );

  server.tool(
    "private_reply_ig_comment",
    "Send a private DM reply to an Instagram commenter",
    {
      accountId: z.string().describe("Instagram account ID"),
      commentId: z.string().describe("Comment ID"),
      message: z.string().describe("Private message text"),
    },
    async ({ accountId, commentId, message }) => {
      return respond(await api("/instagram/comments?action=private-reply", "POST", { accountId, commentId, message }));
    }
  );

  // -- Inbox Rules --

  server.tool(
    "list_inbox_rules",
    "List all auto-reply rules for a workspace",
    {
      workspaceId: z.string().describe("Workspace ID"),
    },
    async ({ workspaceId }) => {
      return respond(await api("/inbox-rules?action=list", "POST", { workspace_id: workspaceId }));
    }
  );

  server.tool(
    "create_inbox_rule",
    "Create an auto-reply rule for inbox messages matching a pattern",
    {
      workspaceId: z.string().describe("Workspace ID"),
      triggerType: z.string().describe("Trigger type (e.g. 'keyword', 'mention')"),
      triggerPattern: z.string().describe("Pattern/keywords to match"),
      replyText: z.string().describe("Auto-reply message"),
      accountId: z.string().optional().describe("Limit to specific account"),
    },
    async ({ workspaceId, triggerType, triggerPattern, replyText, accountId }) => {
      return respond(await api("/inbox-rules?action=create", "POST", {
        workspace_id: workspaceId,
        account_id: accountId,
        trigger_type: triggerType,
        trigger_pattern: triggerPattern,
        reply_text: replyText,
      }));
    }
  );

  server.tool(
    "toggle_inbox_rule",
    "Enable or disable an auto-reply rule",
    {
      ruleId: z.string().describe("Rule ID"),
      isActive: zBool.describe("true to enable, false to disable"),
    },
    async ({ ruleId, isActive }) => {
      return respond(await api("/inbox-rules?action=toggle", "POST", { id: ruleId, is_active: isActive }));
    }
  );

  server.tool(
    "delete_inbox_rule",
    "Delete an auto-reply rule. Use dryRun=true (default) to preview.",
    {
      ruleId: z.string().describe("Rule ID"),
      dryRun: zBool.default(true).describe("Preview deletion (default: true). Must be explicitly set to false to execute."),
    },
    async ({ ruleId, dryRun }) => {
      if (dryRun !== false) {
        return dryRunResponse("Delete inbox auto-reply rule", { ruleId });
      }
      return respond(await api("/inbox-rules?action=delete", "POST", { id: ruleId }));
    }
  );
};
