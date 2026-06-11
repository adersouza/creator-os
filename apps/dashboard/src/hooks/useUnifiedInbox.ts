import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { z } from 'zod';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { useConnectedAccounts, type ConnectedAccount } from '@/hooks/useConnectedAccounts';
import { createHookCache } from '@/hooks/_hookCache';
import { subscribe } from '@/services/realtimeManager';
import { apiFetch } from '@/lib/apiFetch';

/**
 * Unified inbox feed — merges Threads + Instagram incoming surfaces into a
 * single Conversation[] the Inbox page can render without caring about source.
 *
 * Sources (all filtered to the signed-in operator's user_id):
 *   post_replies      — Threads replies on the operator's Threads posts
 *   mentions          — Threads @-mentions
 *   inbox_dm_cache    — Instagram DMs cached server-side
 *
 * Backend-populated. No write paths here — sendReply lives elsewhere.
 * One row per inbox item (no conversation threading yet — each reply/comment is
 * its own "conversation" until a grouping service exists).
 */

type MessageType = 'dm' | 'mention' | 'comment';
type PlatformKind = 'threads' | 'instagram';
type Sentiment = 'positive' | 'neutral' | 'negative';

interface ChatTurn {
  id: string;
  from: 'them' | 'me';
  text: string;
  time: string;
}

export interface InboxConversation {
  id: string;
  user: {
    name: string;
    handle: string;
    avatarFrom: string;
    avatarTo: string;
    verified?: boolean | undefined;
    followers: number;
  };
  toAccount: string;
  network: {
    id: string;
    label: string;
    color: string;
  };
  platform: PlatformKind;
  type: MessageType;
  snippet: string;
  ago: string;
  sentiment?: Sentiment | undefined;
  isTopEngager?: boolean | undefined;
  isRead?: boolean | undefined;
  turns: ChatTurn[];
  /** Raw timestamp (ms) for sorting — render uses `ago`. */
  _ts: number;
  /** Reply-send metadata — populated for every row so the UI can fire off
   *  `sendReply()` without cross-referencing the source table. */
  reply: {
    /** Which platform's Graph API to hit (mirrors `platform`). */
    platform: PlatformKind;
    /** Operator's account id the message lives on. null = couldn't resolve. */
    accountId: string | null;
    /** Id of the upstream thing we're replying to (post id / comment id / conversation id). */
    replyToId: string;
    /** Conversation id for DMs — backend uses this to address the right participant. */
    conversationId?: string | undefined;
    /** Target shape so the backend picks the right Meta endpoint. */
    kind: 'dm' | 'comment' | 'reply';
    /** Server-side guard against replying from stale inbox context. */
    context?: {
      conversationId?: string | undefined;
      lastSeenAt?: string | undefined;
      lastTurnId?: string | undefined;
    } | undefined;
  };
}

interface State {
  conversations: InboxConversation[];
  isLoading: boolean;
}

const unifiedInboxMessageSchema = z.object({
  id: z.string(),
  source: z.enum(['ig_dm', 'ig_comment', 'ig_mention', 'threads_reply', 'threads_mention']),
  accountId: z.string().nullable().optional(),
  groupId: z.string().nullable().optional(),
  conversationId: z.string().optional(),
  replyToId: z.string().optional(),
  replyKind: z.enum(['dm', 'comment', 'reply']).optional(),
  from: z.object({
    id: z.union([z.string(), z.number()]).optional(),
    username: z.union([z.string(), z.number()]).optional(),
    avatar: z.string().optional(),
  }).default({}),
  text: z.string().default(''),
  timestamp: z.string(),
  postId: z.string().optional(),
  postPreview: z.string().optional(),
  sentiment: z.enum(['positive', 'neutral', 'negative', 'toxic']).optional(),
  isRead: z.boolean().default(false),
  isReplied: z.boolean().default(false),
  priority: z.number().default(0),
}).passthrough();

const unifiedInboxResponseSchema = z.object({
  success: z.boolean().optional(),
  messages: z.array(unifiedInboxMessageSchema).default([]),
  total: z.number().default(0),
  page: z.number().default(1),
  limit: z.number().default(50),
  hasMore: z.boolean().default(false),
  nextCursor: z.string().nullable().optional(),
});

type UnifiedInboxMessage = z.infer<typeof unifiedInboxMessageSchema>;

const UNASSIGNED_GROUP_ID = 'unassigned';
const UNASSIGNED_GROUP_LABEL = 'Unassigned';
const UNASSIGNED_GROUP_COLOR = '#6B6B70';

// Gradient seed — two complementary hues from the handle.
function gradientFor(key: string): { from: string; to: string } {
  let h = 0;
  for (let i = 0; i < key.length; i += 1) h = (h * 33 + key.charCodeAt(i)) >>> 0;
  const hue = h % 360;
  return {
    from: `hsl(${hue} 55% 42%)`,
    to: `hsl(${(hue + 40) % 360} 60% 55%)`,
  };
}

function relTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const diff = Date.now() - t;
  const min = Math.round(diff / 60_000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}d`;
  return `${Math.round(day / 7)}w`;
}

function tsOf(iso: string | null | undefined): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? 0 : t;
}

function conversationFromServerMessage(
  message: UnifiedInboxMessage,
  lookup: AccountLookup,
): InboxConversation {
  const source = message.source;
  const platform: PlatformKind = source.startsWith('threads') ? 'threads' : 'instagram';
  const type: MessageType = source === 'ig_dm' ? 'dm' : source.endsWith('mention') ? 'mention' : 'comment';
  const accountId = message.accountId ?? null;
  const acct = resolveAccount(accountId, lookup, platform);
  const handle = String(message.from.username || message.from.id || 'unknown');
  const grad = gradientFor(handle);
  const when = message.timestamp;
  const turnId = `${message.id}-0`;
  const sentiment =
    message.sentiment === 'toxic' ? 'negative' : message.sentiment;

  return {
    id: message.id,
    user: {
      name: handle,
      handle,
      avatarFrom: grad.from,
      avatarTo: grad.to,
      followers: 0,
    },
    toAccount: acct.handle,
    network: acct.network,
    platform: acct.platform,
    type,
    snippet: message.text,
    ago: relTime(when),
    sentiment,
    isRead: message.isRead,
    turns: [
      {
        id: turnId,
        from: 'them',
        text: message.text,
        time: relTime(when),
      },
    ],
    _ts: tsOf(when),
    reply: {
      platform: acct.platform,
      accountId,
      replyToId: message.replyToId || message.postId || message.id,
      conversationId: message.conversationId,
      kind: message.replyKind || (type === 'dm' ? 'dm' : platform === 'instagram' ? 'comment' : 'reply'),
      context: {
        conversationId: message.conversationId || message.id,
        lastSeenAt: when,
        lastTurnId: turnId,
      },
    },
  };
}

type AccountLookup = Map<
  string,
  {
    handle: string;
    platform: PlatformKind;
    groupId: string | null;
    groupName: string;
    groupColor: string;
  }
>;

function buildLookup(accounts: ConnectedAccount[]): AccountLookup {
  const m: AccountLookup = new Map();
  for (const a of accounts) {
    m.set(a.id, {
      handle: a.handle,
      platform: a.platform,
      groupId: a.groupId,
      groupName: a.groupName || UNASSIGNED_GROUP_LABEL,
      groupColor: a.groupColor || UNASSIGNED_GROUP_COLOR,
    });
  }
  return m;
}

function resolveAccount(
  accountId: string | null | undefined,
  lookup: AccountLookup,
  fallbackPlatform: PlatformKind,
): {
  handle: string;
  network: { id: string; label: string; color: string };
  platform: PlatformKind;
} {
  if (accountId) {
    const hit = lookup.get(accountId);
    if (hit) {
      return {
        handle: hit.handle,
        network: {
          id: hit.groupId ?? UNASSIGNED_GROUP_ID,
          label: hit.groupName,
          color: hit.groupColor,
        },
        platform: hit.platform,
      };
    }
  }
  return {
    handle: 'unknown',
    network: {
      id: UNASSIGNED_GROUP_ID,
      label: UNASSIGNED_GROUP_LABEL,
      color: UNASSIGNED_GROUP_COLOR,
    },
    platform: fallbackPlatform,
  };
}

const cache = createHookCache<State>();
const inFlight = new Map<string, Promise<State>>();

export interface UseUnifiedInboxResult extends State {
  refetch: () => void;
}

export function useUnifiedInbox(): UseUnifiedInboxResult {
  const authUser = useAuthUser();
  const { accounts, isLoading: _accountsLoading } = useConnectedAccounts();
  const userKey = authUser ? authUser.id : null;
  const [state, setState] = useState<State>(() => {
    const cached = cache.get(userKey);
    if (cached) return { ...cached, isLoading: false };
    return { conversations: [], isLoading: true };
  });
  const [_nonce, setNonce] = useState(0);
  const forceRefetchRef = useRef(false);
  const refetch = useCallback(() => {
    forceRefetchRef.current = true;
    setNonce((n) => n + 1);
  }, []);

  const lookup = useMemo(() => buildLookup(accounts), [accounts]);
  const _lookupKey = useMemo(
    () =>
      accounts
        .map((account) => `${account.id}:${account.handle}:${account.platform}:${account.groupId ?? 'unassigned'}`)
        .sort()
        .join('|'),
    [accounts],
  );

  useEffect(() => {
    let cancelled = false;
    if (!authUser) {
      // Stay in loading state while auth hydrates. Flipping to an empty
      // conversations array here makes the Inbox flash its empty-state
      // between the skeleton and the real payload on every nav.
      return;
    }
    if (_accountsLoading) return;

    const cached = cache.get(userKey);
    if (cached) setState({ ...cached, isLoading: false });

    const shouldForceRefetch = forceRefetchRef.current;
    forceRefetchRef.current = false;

    // Skip the Supabase round-trip if we fetched under FRESH_MS ago —
    // realtime subscriptions keep the cache live in the background, so
    // clicking back to a page you were just on shouldn't re-query.
    if (!shouldForceRefetch && cache.isFresh(userKey)) return;

    const requestKey = `${userKey ?? 'anon'}:${_lookupKey}`;
    const existing = inFlight.get(requestKey);
    if (existing && !shouldForceRefetch) {
      existing.then((next) => {
        if (!cancelled) setState(next);
      }).catch(() => {
        if (!cancelled) setState((prev) => ({ ...prev, isLoading: false }));
      });
      return () => {
        cancelled = true;
      };
    }

    const request = (async (): Promise<State> => {
      try {
        const server = await apiFetch(
          '/api/inbox?action=unified&filter=all&limit=250',
          unifiedInboxResponseSchema,
        );
        const out = server.messages
          .map((message) => conversationFromServerMessage(message, lookup))
          .sort((a, b) => b._ts - a._ts);
        const next: State = { conversations: out, isLoading: false };
        cache.set(userKey, next);
        return next;
      } catch {
        // Keep the older client-side aggregation as a resilience fallback while
        // production schemas settle around the server-side inbox contract.
      }

      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return { conversations: [], isLoading: false };

      // Pull last 30 days for comment/mention surfaces. DMs are already one row
      // per conversation, so use the latest cached conversations across the
      // full fleet instead of hiding older conversations in all-accounts view.
      const since = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();

      const [threadsRepliesRes, threadsMentionsRes, igCommentsRes, dmRes] =
        await Promise.all([
          supabase
            .from('post_replies')
            .select('id, post_id, content, username, display_name, created_at, threads_reply_id, is_read, posts!inner(user_id, account_id)')
            .eq('posts.user_id', user.id)
            .gte('created_at', since)
            .order('created_at', { ascending: false })
            .limit(100),
          supabase
            .from('mentions')
            .select('id, account_id, content, mentioned_by_username, mentioned_by_avatar, mentioned_at, created_at, permalink, threads_post_id, is_read')
            .eq('user_id', user.id)
            .gte('created_at', since)
            .order('created_at', { ascending: false })
            .limit(100),
          supabase
            .from('ig_comments')
            .select('id, account_id, comment_id, media_id, text, username, created_at, like_count, is_read, posts!inner(user_id, instagram_account_id)')
            .eq('posts.user_id', user.id)
            .gte('created_at', since)
            .order('created_at', { ascending: false })
            .limit(100),
          supabase
            .from('inbox_dm_cache')
            .select('id, account_id, participant_username, conversation_name, last_message_text, last_message_at, updated_at, is_read')
            .eq('user_id', user.id)
            .order('last_message_at', { ascending: false })
            .limit(250),
        ]);

      const L = lookup;
      const out: InboxConversation[] = [];

      for (const r of threadsRepliesRes.data ?? []) {
        const row = r as Record<string, unknown>;
        const nested = (row.posts as { account_id?: string | null | undefined } | null) ?? null;
        const acct = resolveAccount(nested?.account_id ?? null, L, 'threads');
        const when = (row.created_at as string) ?? null;
        const turnId = `tr-${row.id}-0`;
        const handle = (row.username as string) ?? 'unknown';
        const grad = gradientFor(handle);
        out.push({
          id: `tr-${row.id}`,
          user: {
            name: (row.display_name as string) || handle,
            handle,
            avatarFrom: grad.from,
            avatarTo: grad.to,
            followers: 0,
          },
          toAccount: acct.handle,
          network: acct.network,
          platform: 'threads',
          type: 'comment',
          snippet: (row.content as string) ?? '',
          ago: relTime(when),
          isRead: row.is_read === true,
          turns: [
            {
              id: turnId,
              from: 'them',
              text: (row.content as string) ?? '',
              time: relTime(when),
            },
          ],
          _ts: tsOf(when),
          reply: {
            platform: 'threads',
            accountId: nested?.account_id ?? null,
            replyToId: (row.threads_reply_id as string) || String(row.id),
            kind: 'reply',
            context: {
              conversationId: `tr-${row.id}`,
              lastSeenAt: when ?? undefined,
              lastTurnId: turnId,
            },
          },
        });
      }

      for (const r of threadsMentionsRes.data ?? []) {
        const row = r as Record<string, unknown>;
        const acct = resolveAccount((row.account_id as string) ?? null, L, 'threads');
        const when = (row.mentioned_at as string) ?? (row.created_at as string) ?? null;
        const turnId = `tm-${row.id}-0`;
        const handle = (row.mentioned_by_username as string) ?? 'unknown';
        const grad = gradientFor(handle);
        out.push({
          id: `tm-${row.id}`,
          user: {
            name: handle,
            handle,
            avatarFrom: grad.from,
            avatarTo: grad.to,
            followers: 0,
          },
          toAccount: acct.handle,
          network: acct.network,
          platform: 'threads',
          type: 'mention',
          snippet: (row.content as string) ?? '',
          ago: relTime(when),
          isRead: row.is_read === true,
          turns: [
            {
              id: turnId,
              from: 'them',
              text: (row.content as string) ?? '',
              time: relTime(when),
            },
          ],
          _ts: tsOf(when),
          reply: {
            platform: 'threads',
            accountId: (row.account_id as string) ?? null,
            replyToId: (row.threads_post_id as string) || String(row.id),
            kind: 'reply',
            context: {
              conversationId: `tm-${row.id}`,
              lastSeenAt: when ?? undefined,
              lastTurnId: turnId,
            },
          },
        });
      }

      for (const r of igCommentsRes.data ?? []) {
        const row = r as Record<string, unknown>;
        const nested = (row.posts as { instagram_account_id?: string | null | undefined } | null) ?? null;
        const accountId = (row.account_id as string | null) ?? nested?.instagram_account_id ?? null;
        const acct = resolveAccount(accountId, L, 'instagram');
        const when = (row.created_at as string) ?? null;
        const turnId = `igc-${row.id}-0`;
        const handle = (row.username as string) ?? 'unknown';
        const grad = gradientFor(handle);
        const likeCount = Number(row.like_count ?? 0);
        out.push({
          id: `igc-${row.id}`,
          user: {
            name: handle,
            handle,
            avatarFrom: grad.from,
            avatarTo: grad.to,
            followers: 0,
          },
          toAccount: acct.handle,
          network: acct.network,
          platform: 'instagram',
          type: 'comment',
          snippet: (row.text as string) ?? '',
          ago: relTime(when),
          isRead: row.is_read === true,
          turns: [
            {
              id: turnId,
              from: 'them',
              text: (row.text as string) ?? '',
              time: likeCount > 0 ? `${relTime(when)} · ${likeCount} like${likeCount === 1 ? '' : 's'}` : relTime(when),
            },
          ],
          _ts: tsOf(when),
          reply: {
            platform: 'instagram',
            accountId,
            replyToId: (row.comment_id as string) || String(row.id),
            kind: 'comment',
            context: {
              conversationId: `igc-${row.id}`,
              lastSeenAt: when ?? undefined,
              lastTurnId: turnId,
            },
          },
        });
      }

      for (const r of dmRes.data ?? []) {
        const row = r as Record<string, unknown>;
        const accountId = (row.account_id as string) ?? null;
        const hit = accountId ? L.get(accountId) : null;
        if (hit?.platform === 'threads') continue;
        const acct = resolveAccount(accountId, L, 'instagram');
        const when = (row.last_message_at as string) ?? (row.updated_at as string) ?? null;
        const turnId = `dm-${row.id}-0`;
        const handle =
          (row.participant_username as string) ||
          (row.conversation_name as string) ||
          'unknown';
        const grad = gradientFor(handle);
        out.push({
          id: `dm-${row.id}`,
          user: {
            name: (row.conversation_name as string) || handle,
            handle,
            avatarFrom: grad.from,
            avatarTo: grad.to,
            followers: 0,
          },
          toAccount: acct.handle,
          network: acct.network,
          platform: acct.platform,
          type: 'dm',
          snippet: (row.last_message_text as string) ?? '',
          ago: relTime(when),
          isRead: row.is_read === true,
          turns: [
            {
              id: turnId,
              from: 'them',
              text: (row.last_message_text as string) ?? '',
              time: relTime(when),
            },
          ],
          _ts: tsOf(when),
          reply: {
            platform: acct.platform,
            accountId,
            replyToId: String(row.id),
            conversationId: String(row.id),
            kind: 'dm',
            context: {
              conversationId: `dm-${row.id}`,
              lastSeenAt: when ?? undefined,
              lastTurnId: turnId,
            },
          },
        });
      }

      out.sort((a, b) => b._ts - a._ts);

      const next: State = { conversations: out, isLoading: false };
      cache.set(userKey, next);
      return next;
    })();
    inFlight.set(requestKey, request);
    request
      .then((next) => {
        if (!cancelled) setState(next);
      })
      .catch(() => {
        if (!cancelled) setState((prev) => ({ ...prev, isLoading: false }));
      })
      .finally(() => {
        if (inFlight.get(requestKey) === request) inFlight.delete(requestKey);
      });

    return () => {
      cancelled = true;
    };
  }, [authUser, userKey, lookup, _lookupKey, _accountsLoading]);

  // Realtime — any insert/update to the source tables nudges a refetch.
  useEffect(() => {
    if (!authUser) return;
    const tables = [
      'post_replies',
      'mentions',
      'ig_comments',
      'inbox_dm_cache',
    ] as const;
    const unsubs = tables.map((table) =>
      subscribe(`inbox:${table}`, () =>
        supabase
          .channel(`inbox:${table}`)
          .on(
            'postgres_changes',
            { event: '*', schema: 'public', table },
            () => refetch(),
          )
          .subscribe(),
      ),
    );
    return () => {
      for (const u of unsubs) u();
    };
  }, [authUser, refetch]);

  // visibilitychange — when the operator tabs back to Juno33 after time
  // away from the Inbox tab, pull fresh data if the cache is stale. Realtime
  // is authoritative when the tab is focused, but a backgrounded tab may
  // miss events (browsers throttle WebSockets when hidden), so tab-return
  // is a natural revalidation boundary.
  useEffect(() => {
    if (!authUser) return;
    const onVis = () => {
      if (document.visibilityState !== 'visible') return;
      if (cache.isFresh(userKey)) return;
      refetch();
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [authUser, userKey, refetch]);

  return { ...state, refetch };
}
