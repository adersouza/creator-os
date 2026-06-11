// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useEffect, useState } from 'react';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { createHookCache } from '@/hooks/_hookCache';
import { useDashboardRefreshRevision } from '@/lib/dashboardRefreshSignal';

export type AccountHealth = 'good' | 'idle' | 'warn' | 'critical' | 'offline';
export type AccountPlatform = 'threads' | 'instagram';

export interface FleetAccount {
  id: string;
  handle: string;               // includes leading `@`
  displayName: string;
  avatarUrl: string | null;
  platform: AccountPlatform;
  groupId: string | null;
  groupName: string;
  groupColor: string;
  followers: number;
  posts24h: number;
  lastPostHoursAgo: number | null;
  lastPublishedAt: string | null;
  health: AccountHealth;
  healthScore: number;          // 0–100 rough score for sorting / legacy row UI
  tokenExpiresAt: string | null;
  tokenDaysLeft: number | null;
  tokenActive: boolean;
  needsReauth: boolean;
  isActive: boolean;
  trend7d: number[];            // 7 daily engagement-rate points (flat zeros if insufficient)
  isShadowbanned: boolean;
  tags: string[];
}

export interface FleetGroupMeta {
  id: string;
  name: string;
  color: string;
}

export interface FleetAccountTotals {
  active: number;
  flagged: number;
  drifting: number;
  inactive: number;
  total: number;
}

interface State {
  accounts: FleetAccount[];
  groups: FleetGroupMeta[];
  totals: FleetAccountTotals;
  isLoading: boolean;
}

const UNASSIGNED_COLOR = '#6B6B70';
const DORMANT_HOURS = 72;
const DAY_MS = 24 * 60 * 60 * 1000;
const TREND_DAYS = 7;
const POSTS_LOOKBACK_DAYS = 7;

/**
 * Fleet health classifier — MIRRORS the rule set in `useFleetHealth.ts`, but
 * extended with richer buckets (good / idle / warn / critical / offline) that
 * the Accounts table can render with distinct tints per CLAUDE.md spec.
 *
 * critical — `needs_reauth=true` OR token already expired (single source of truth with useFleetHealth crit)
 * offline  — `is_active=false` (paused / disconnected)
 * warn     — dormant: no sync in DORMANT_HOURS
 * idle     — connected and syncing, but no posts in the last 24h
 * good     — everything else (healthy + recently posting)
 */
function classify(params: {
  needsReauth: boolean;
  tokenExpiresAt: string | null;
  lastSyncedAt: string | null;
  isActive: boolean;
  posts24h: number;
  now: Date;
}): AccountHealth {
  const { needsReauth, tokenExpiresAt, lastSyncedAt, isActive, posts24h, now } = params;
  const tokenDead =
    needsReauth ||
    (tokenExpiresAt ? new Date(tokenExpiresAt).getTime() < now.getTime() : false);
  if (tokenDead) return 'critical';
  if (!isActive) return 'offline';
  const dormantCutoff = now.getTime() - DORMANT_HOURS * 60 * 60 * 1000;
  const dormant = lastSyncedAt ? new Date(lastSyncedAt).getTime() < dormantCutoff : false;
  if (dormant) return 'warn';
  if (posts24h === 0) return 'idle';
  return 'good';
}

function healthToScore(health: AccountHealth): number {
  switch (health) {
    case 'good':
      return 92;
    case 'idle':
      return 78;
    case 'warn':
      return 58;
    case 'critical':
      return 28;
    default:
      return 44;
  }
}

/**
 * Enriched list of the operator's connected accounts (Threads + Instagram)
 * with per-account computed health, 24h post counts, token status, and a
 * 7-day engagement-rate sparkline. Also returns aggregate totals suitable
 * for the Accounts page stat cards.
 */
const cache = createHookCache<State>();
const inFlight = new Map<string, Promise<State>>();

export function resetFleetAccountsCache() {
  cache.clearAll();
  inFlight.clear();
}

export function useFleetAccounts(): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const refreshRevision = useDashboardRefreshRevision();
  // Seed from module cache so navigating back to /accounts after a previous
  // visit renders the last-known list immediately instead of flashing empty-state.
  // We still run the background fetch and overwrite when it resolves.
  const [state, setState] = useState<State>(() => {
    const cached = cache.get(userKey);
    if (cached) return { ...cached, isLoading: false };
    return {
      accounts: [],
      groups: [],
      totals: { active: 0, flagged: 0, drifting: 0, inactive: 0, total: 0 },
      isLoading: true,
    };
  });

  useEffect(() => {
    void refreshRevision;
    let cancelled = false;
    if (!authUser) {
      // Auth hydration hasn't landed yet — stay in loading state instead of
      // flipping to empty. Otherwise "No accounts connected" flashes on every
      // navigation. The next render (when authUser resolves) runs the fetch.
      return;
    }

    // SWR: seed from cache as soon as userKey resolves. The useState initialiser
    // runs before useAuthUser hydrates, so the initial snapshot can miss a
    // warm cache. Re-check here before firing the background fetch.
    const cached = cache.get(userKey);
    if (cached) {
      setState({ ...cached, isLoading: false });
    }

    // SWR freshness gate — if the cached payload is under FRESH_MS old,
    // don't refire the Supabase query on this mount. Realtime subs keep
    // the cache live in the background.
    if (cache.isFresh(userKey)) return;

    const existing = userKey ? inFlight.get(userKey) : undefined;
    if (existing) {
      existing
        .then((next) => {
          if (!cancelled) setState(next);
        })
        .catch(() => {
          if (!cancelled) setState((prev) => ({ ...prev, isLoading: false }));
        });
      return () => {
        cancelled = true;
      };
    }

    const request = (async (): Promise<State> => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) {
        return {
          accounts: [],
          groups: [],
          totals: { active: 0, flagged: 0, drifting: 0, inactive: 0, total: 0 },
          isLoading: false,
        };
      }

      const now = new Date();
      const lookbackCutoff = new Date(now.getTime() - POSTS_LOOKBACK_DAYS * DAY_MS).toISOString();

      const [threadsRes, igRes, groupsRes, postsRes] = await Promise.all([
        supabase
          .from('accounts')
          .select(
            'id, username, display_name, avatar_url, group_id, followers_count, is_active, is_retired, is_shadowbanned, needs_reauth, token_expires_at, last_synced_at, tags',
          )
          .eq('user_id', user.id)
          .eq('is_retired', false),
        supabase
          .from('instagram_accounts')
          // instagram_accounts has no is_shadowbanned column (it's threads-only)
          // — selecting it makes the whole query 400 and blanks the Accounts page.
          .select(
            'id, username, display_name, avatar_url, group_id, follower_count, is_active, needs_reauth, token_expires_at, last_synced_at',
          )
          .eq('user_id', user.id),
        supabase
          .from('account_groups')
          .select('id, name, color')
          .eq('user_id', user.id),
        supabase
          .from('posts')
          .select(
            'id, account_id, instagram_account_id, platform, published_at, engagement_rate',
          )
          .eq('user_id', user.id)
          .eq('status', 'published')
          .gte('published_at', lookbackCutoff)
          .order('published_at', { ascending: false })
          .limit(5000),
      ]);

      if (threadsRes.error) throw threadsRes.error;
      if (igRes.error) throw igRes.error;
      if (groupsRes.error) throw groupsRes.error;
      if (postsRes.error) throw postsRes.error;

      // Group lookup
      const groupsById = new Map<string, { name: string; color: string }>();
      const groupsList: FleetGroupMeta[] = (groupsRes.data ?? []).map((g) => {
        const color = g.color || UNASSIGNED_COLOR;
        groupsById.set(g.id, { name: g.name, color });
        return { id: g.id, name: g.name, color };
      });

      // Build per-account post aggregates
      type PostRow = {
        id: string;
        account_id: string | null;
        instagram_account_id: string | null;
        platform: string | null;
        published_at: string | null;
        engagement_rate: number | null;
      };
      const postsByAccount = new Map<string, PostRow[]>();
      for (const raw of (postsRes.data ?? []) as PostRow[]) {
        const key =
          raw.platform === 'threads'
            ? raw.account_id
            : raw.platform === 'instagram'
            ? raw.instagram_account_id
            : raw.account_id ?? raw.instagram_account_id;
        if (!key) continue;
        const list = postsByAccount.get(key) ?? [];
        list.push(raw);
        postsByAccount.set(key, list);
      }

      const cutoff24h = now.getTime() - DAY_MS;
      const trendDayStart = (offsetDays: number) => {
        const d = new Date(now.getTime() - offsetDays * DAY_MS);
        d.setHours(0, 0, 0, 0);
        return d.getTime();
      };

      function buildTrend(rows: PostRow[]): number[] {
        if (rows.length === 0) return new Array(TREND_DAYS).fill(0);
        // bucket by local-day, last TREND_DAYS days inclusive (today = idx 6)
        const buckets: { sum: number; count: number }[] = Array.from(
          { length: TREND_DAYS },
          () => ({ sum: 0, count: 0 }),
        );
        const today0 = trendDayStart(0);
        for (const row of rows) {
          if (!row.published_at) continue;
          const ts = new Date(row.published_at).getTime();
          const dayIdx = TREND_DAYS - 1 - Math.floor((today0 - ts) / DAY_MS);
          if (dayIdx < 0 || dayIdx >= TREND_DAYS) continue;
          const rate = typeof row.engagement_rate === 'number' ? row.engagement_rate : 0;
          buckets[dayIdx]!.sum += rate;
          buckets[dayIdx]!.count += 1;
        }
        // If no bucket has any posts → zeros (don't fabricate per spec).
        const hasAny = buckets.some((b) => b.count > 0);
        if (!hasAny) return new Array(TREND_DAYS).fill(0);
        return buckets.map((b) => (b.count > 0 ? b.sum / b.count : 0));
      }

      function resolveGroup(groupId: string | null, _platform: AccountPlatform) {
        const g = groupId ? groupsById.get(groupId) ?? null : null;
        return {
          groupId,
          groupName: g?.name ?? 'Unassigned',
          groupColor: g?.color ?? UNASSIGNED_COLOR,
        };
      }

      function daysUntil(iso: string | null): number | null {
        if (!iso) return null;
        const diff = new Date(iso).getTime() - now.getTime();
        return Math.floor(diff / DAY_MS);
      }

      function hoursSince(iso: string | null): number | null {
        if (!iso) return null;
        const diff = now.getTime() - new Date(iso).getTime();
        if (diff < 0) return 0;
        return Math.floor(diff / (60 * 60 * 1000));
      }

      type ThreadsRow = {
        id: string;
        username: string | null;
        display_name: string | null;
        avatar_url: string | null;
        group_id: string | null;
        followers_count: number | null;
        is_active: boolean | null;
        is_retired: boolean;
        is_shadowbanned: boolean;
        needs_reauth: boolean;
        token_expires_at: string | null;
        last_synced_at: string | null;
        tags: string[] | null;
      };
      type IgRow = {
        id: string;
        username: string | null;
        display_name: string | null;
        avatar_url: string | null;
        group_id: string | null;
        follower_count: number | null;
        is_active: boolean | null;
        needs_reauth: boolean;
        token_expires_at: string | null;
        last_synced_at: string | null;
      };

      const threadsRows = (threadsRes.data ?? []) as ThreadsRow[];
      const igRows = (igRes.data ?? []) as IgRow[];

      const enriched: FleetAccount[] = [];

      for (const row of threadsRows) {
        const rows = postsByAccount.get(row.id) ?? [];
        const posts24h = rows.reduce(
          (acc, r) =>
            r.published_at && new Date(r.published_at).getTime() >= cutoff24h ? acc + 1 : acc,
          0,
        );
        const lastPublishedAt = rows.reduce<string | null>((latest, r) => {
          if (!r.published_at) return latest;
          if (!latest) return r.published_at;
          return r.published_at > latest ? r.published_at : latest;
        }, null);
        const isActive = row.is_active !== false;
        const health = classify({
          needsReauth: row.needs_reauth === true,
          tokenExpiresAt: row.token_expires_at,
          lastSyncedAt: row.last_synced_at,
          isActive,
          posts24h,
          now,
        });
        const group = resolveGroup(row.group_id, 'threads');
        const fallbackName = 'Unnamed account';
        const handle = row.username ? `@${row.username}` : fallbackName;
        const displayName = row.display_name || row.username || fallbackName;
        const tokenDaysLeft = daysUntil(row.token_expires_at);
        enriched.push({
          id: row.id,
          handle,
          displayName,
          avatarUrl: row.avatar_url,
          platform: 'threads',
          ...group,
          followers: row.followers_count ?? 0,
          posts24h,
          lastPostHoursAgo: hoursSince(lastPublishedAt),
          lastPublishedAt,
          health,
          healthScore: healthToScore(health),
          tokenExpiresAt: row.token_expires_at,
          tokenDaysLeft,
          tokenActive:
            !row.needs_reauth &&
            (!row.token_expires_at || new Date(row.token_expires_at).getTime() > now.getTime()),
          needsReauth: row.needs_reauth === true,
          isActive,
          trend7d: buildTrend(rows),
          isShadowbanned: row.is_shadowbanned === true,
          tags: Array.isArray(row.tags) ? row.tags : [],
        });
      }

      for (const row of igRows) {
        const rows = postsByAccount.get(row.id) ?? [];
        const posts24h = rows.reduce(
          (acc, r) =>
            r.published_at && new Date(r.published_at).getTime() >= cutoff24h ? acc + 1 : acc,
          0,
        );
        const lastPublishedAt = rows.reduce<string | null>((latest, r) => {
          if (!r.published_at) return latest;
          if (!latest) return r.published_at;
          return r.published_at > latest ? r.published_at : latest;
        }, null);
        const isActive = row.is_active !== false;
        const health = classify({
          needsReauth: row.needs_reauth === true,
          tokenExpiresAt: row.token_expires_at,
          lastSyncedAt: row.last_synced_at,
          isActive,
          posts24h,
          now,
        });
        const group = resolveGroup(row.group_id, 'instagram');
        const fallbackName = 'Unnamed account';
        const handle = row.username ? `@${row.username}` : fallbackName;
        const displayName = row.display_name || row.username || fallbackName;
        const tokenDaysLeft = daysUntil(row.token_expires_at);
        enriched.push({
          id: row.id,
          handle,
          displayName,
          avatarUrl: row.avatar_url,
          platform: 'instagram',
          ...group,
          followers: row.follower_count ?? 0,
          posts24h,
          lastPostHoursAgo: hoursSince(lastPublishedAt),
          lastPublishedAt,
          health,
          healthScore: healthToScore(health),
          tokenExpiresAt: row.token_expires_at,
          tokenDaysLeft,
          tokenActive:
            !row.needs_reauth &&
            (!row.token_expires_at || new Date(row.token_expires_at).getTime() > now.getTime()),
          needsReauth: row.needs_reauth === true,
          isActive,
          trend7d: buildTrend(rows),
          // IG doesn't expose a shadowban flag on the account row.
          isShadowbanned: false,
          tags: [],
        });
      }

      const totals: FleetAccountTotals = {
        active: enriched.filter((a) => a.health === 'good').length,
        flagged: enriched.filter((a) => a.health === 'critical').length,
        drifting: enriched.filter((a) => a.health === 'warn' || a.health === 'idle').length,
        inactive: enriched.filter((a) => a.health === 'offline').length,
        total: enriched.length,
      };

      const next: State = { accounts: enriched, groups: groupsList, totals, isLoading: false };
      cache.set(userKey, next);
      return next;
    })();
    if (userKey) {
      inFlight.set(userKey, request);
    }
    request
      .then((next) => {
        if (!cancelled) setState(next);
      })
      .catch(() => {
        if (!cancelled) setState((prev) => ({ ...prev, isLoading: false }));
      })
      .finally(() => {
        if (userKey && inFlight.get(userKey) === request) inFlight.delete(userKey);
      });

    return () => {
      cancelled = true;
    };
  }, [userKey, authUser, refreshRevision]); // eslint-disable-line react-hooks/exhaustive-deps -- userKey encodes identity

  return state;
}
