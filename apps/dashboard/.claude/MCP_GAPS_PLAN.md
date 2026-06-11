# MCP Gaps Implementation Plan
# Next session: implement these in order

## Context
Current MCP coverage: ~92-95% of practical needs.
These 4 items close the remaining meaningful gaps for near-full autonomous operation.

---

## ITEM 1 — `update_draft` (HIGH PRIORITY — do first)
**Time estimate: 1-2 hours**

### What it unlocks
Agent can iterate on content: `ai_generate` → `save_draft` → `ai_feedback` → `update_draft` → `ai_vision_score` → `schedule_post`
Without this the agent has to delete + re-save to fix anything, losing the draft ID.

### API changes — `api/posts.ts`
Add a new action to the existing switch at line ~1791:

```
case "update-draft":
  return handleUpdateDraft(req, res, userId);
```

New handler:
```typescript
async function handleUpdateDraft(req, res, userId) {
  const { postId, content, mediaIds, pollOptions, scheduledFor } = req.body ?? {};
  if (!postId) return apiError(res, 400, "postId is required");

  // Verify ownership + status (only drafts/scheduled can be updated)
  const { data: post } = await getSupabase()
    .from("posts")
    .select("id, status, user_id")
    .eq("id", postId)
    .eq("user_id", userId)
    .maybeSingle();

  if (!post) return apiError(res, 404, "Post not found");
  if (!["draft", "scheduled"].includes(post.status)) {
    return apiError(res, 400, "Only draft or scheduled posts can be updated");
  }

  const updates: Record<string, unknown> = { updated_at: new Date().toISOString() };
  if (content !== undefined) updates.content = content;
  if (mediaIds !== undefined) updates.media_ids = mediaIds;
  if (pollOptions !== undefined) updates.poll_options = pollOptions;
  if (scheduledFor !== undefined) {
    updates.scheduled_for = scheduledFor;
    updates.status = scheduledFor ? "scheduled" : "draft";
  }

  const { error } = await getSupabase()
    .from("posts")
    .update(updates)
    .eq("id", postId)
    .eq("user_id", userId);

  if (error) return apiError(res, 500, "Failed to update draft");
  return apiSuccess(res, { postId, updated: Object.keys(updates) });
}
```

### MCP changes — `mcp-server/src/tools/posts.ts`
Add after `save_draft` tool:

```typescript
server.tool(
  "update_draft",
  "Update an existing draft or scheduled post — content, media, poll options, or reschedule time. Use after ai_feedback or ai_vision_score to refine before scheduling. Only works on status: draft or scheduled.",
  {
    postId: z.string().describe("Draft or scheduled post ID to update"),
    content: z.string().optional().describe("New post text (replaces existing)"),
    mediaIds: z.array(z.string()).optional().describe("New media IDs (replaces existing)"),
    pollOptions: z.array(z.string()).optional().describe("New poll options (Threads only)"),
    scheduledFor: z.string().optional().describe("New scheduled time (ISO 8601), or omit to keep current"),
  },
  async ({ postId, content, mediaIds, pollOptions, scheduledFor }) => {
    return respond(await api("/posts?action=update-draft", "POST", {
      postId, content, mediaIds, pollOptions, scheduledFor,
    }));
  }
);
```

### Verification
- Create draft via `save_draft`, note the postId
- Call `update_draft` with new content
- Call `get_posts` and confirm content changed
- Try calling on a published post — should get 400

---

## ITEM 2 — Account Group CRUD (MEDIUM PRIORITY)
**Time estimate: 3-4 hours**

### What it unlocks
Agent can: create test groups for strategy experiments, reassign low-performing accounts, segment by posting frequency, and dynamically manage the group structure without DB access.

### API changes — new file `api/agent/groups.ts`
```
GET    /api/agent/groups               — list all groups with account counts
POST   /api/agent/groups?action=create — create group
PATCH  /api/agent/groups?action=update — update name/voice_profile
DELETE /api/agent/groups?action=delete — delete (unassigns all accounts first)
POST   /api/agent/groups?action=assign — assign account(s) to a group
```

Key logic notes:
- `withAuth` middleware
- Create: insert into `account_groups` (id=nanoid, user_id, name, content_strategy={})
- Delete: first SET group_id=NULL on both `accounts` and `instagram_accounts` for this group, then delete
- Assign: UPDATE `accounts` SET group_id=X WHERE id IN (accountIds) AND user_id=userId
         UPDATE `instagram_accounts` SET group_id=X WHERE id IN (accountIds) AND user_id=userId
- account_groups.id is TEXT (not UUID) — use nanoid or similar
- Both accounts and instagram_accounts have group_id TEXT FK to account_groups(id)

### MCP changes — new file `mcp-server/src/tools/groups.ts`
4 tools:

```typescript
"create_account_group"  — { name, voiceProfile? }
"update_account_group"  — { groupId, name?, voiceProfile? }
"delete_account_group"  — { groupId, dryRun? }  // dryRun default true
"assign_accounts_to_group" — { accountIds: string[], platform: "threads"|"instagram", groupId: string|null }
  // groupId null = unassign (set to ungrouped)
```

Register in `mcp-server/src/index.ts`:
```typescript
import { register as groups } from "./tools/groups.js";
// add to modules array
```

### Verification
- Create a new group "Test"
- Assign 2 accounts to it
- Set content strategy on it via existing `set_content_strategy`
- Delete the group — verify accounts become ungrouped
- Check `list_accounts` — group_id should be null for those accounts

---

## ITEM 3 — `textAttachment` on Threads posts (LOW PRIORITY)
**Time estimate: 30 min**

### What it unlocks
Long-form text posts on Threads (up to 10k chars, optional link). Meta launched Sep 2025.
Only worth using if content strategy includes long-form essays/threads. Current persona (casual/boppy) doesn't need it, but good to expose.

### API — already handled
`api/posts.ts` already reads `textAttachment` from body and passes it to `threadsApi.ts`.
No backend changes needed.

### MCP changes — `mcp-server/src/tools/posts.ts`
Add to `publish_post`, `schedule_post`, and `bulk_schedule` schemas:

```typescript
textAttachment: z.object({
  text: z.string().describe("Long-form text body (up to 10k chars)"),
  link: z.string().optional().describe("Optional URL to attach"),
}).optional().describe("Threads only: long-form text attachment (replaces caption for text posts)"),
```

Add to the api() call bodies:
```typescript
textAttachment: p.textAttachment,
```

### Verification
- Schedule a post with textAttachment: { text: "long form content here..." }
- Confirm it saves without error (live test requires real Threads account)

---

## ITEM 4 — `get_mentioned_media` for Instagram (LOW-MEDIUM PRIORITY)
**Time estimate: 1-2 hours**

### What it unlocks
Agent can discover UGC (user-generated content) where accounts are tagged. Useful for:
- Finding content to repost or engage with
- Brand monitoring without keyword alerts
- Discovery signals for what audience creates around the persona

### Meta API endpoints
```
GET /{ig-user-id}/tags?fields=id,caption,media_type,media_url,permalink,timestamp,username
GET /{ig-user-id}/mentioned_media?fields=id,caption,media_url,permalink,timestamp&media_id={media_id}
```
Both are in the existing `instagramApi.ts` — functions `getTaggedPosts` and `getMentionedMedia` already exist (grep for them).

### API changes — `api/instagram/insights.ts`
Add two new actions to the switch:
```
case "tagged-posts":
  return handleTaggedPosts(req, res, userId);
case "mentioned-media":
  return handleMentionedMedia(req, res, userId);
```

Each handler: look up account token, call the existing instagramApi.ts function, return results.

### MCP changes — `mcp-server/src/tools/analytics.ts` or new `discovery.ts` entry
```typescript
server.tool(
  "get_mentioned_media",
  "Get Instagram posts where this account has been @mentioned or tagged. Useful for UGC discovery and brand monitoring.",
  {
    accountId: z.string().describe("Instagram account ID"),
    type: z.enum(["tagged", "mentioned"]).optional().describe("tagged = posts you appear in, mentioned = posts that @mention you (default: tagged)"),
  },
  async ({ accountId, type }) => {
    const action = type === "mentioned" ? "mentioned-media" : "tagged-posts";
    return respond(await api("/instagram/insights", "POST", { accountId }, undefined));
    // Note: use ?action= query param pattern like other instagram/insights actions
  }
);
```

### Verification
- Call with a real IG account ID
- Should return array of posts (may be empty if no tags)
- Confirm error handling if account has no tagging permission

---

## Implementation Order for Next Session

```
1. Account group CRUD    — new API + new MCP file (~4h)  HIGHEST VALUE
2. update_draft          — backend + MCP (~2h)     HIGH VALUE
3. textAttachment        — MCP only, ~30min         LOW
4. get_mentioned_media   — backend + MCP (~2h)      LOW-MEDIUM
```

Total estimated time: 8-10 hours across 2 sessions.

---

## Files to touch (summary)

| File | Change |
|------|--------|
| `api/posts.ts` | Add `case "update-draft"` + handler |
| `api/agent/groups.ts` | NEW FILE — group CRUD endpoint |
| `api/instagram/insights.ts` | Add tagged-posts + mentioned-media actions |
| `mcp-server/src/tools/posts.ts` | Add `update_draft` tool + `textAttachment` to 3 tools |
| `mcp-server/src/tools/groups.ts` | NEW FILE — 4 group management tools |
| `mcp-server/src/index.ts` | Register groups module |
| `mcp-server/src/tools/analytics.ts` | Add `get_mentioned_media` tool |

---

## Pre-flight checks for next session

Before starting, run:
```bash
npx tsc --noEmit   # confirm 0 new errors (known pre-existing: health-monitor, inspiration, listening/monitor)
npm run build      # confirm frontend still builds
cd mcp-server && npm run build  # confirm MCP still builds
```

After each item, run the same checks + manual MCP tool test before moving to next item.
