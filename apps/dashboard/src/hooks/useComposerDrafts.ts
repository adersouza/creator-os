import { useCallback, useEffect, useRef, useState } from 'react';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { createHookCache } from '@/hooks/_hookCache';

/**
 * Drafts sync — mirrors Composer drafts between localStorage (instant,
 * offline-safe) and `posts.status='draft'` (roams across devices).
 *
 * Shape: drafts carry a lot of Composer-only UI state (persona, preview mode,
 * thread chain, poll options, etc.) that doesn't map to columns, so the full
 * draft lives in `posts.metadata.composerDraft`. Content + first media_urls +
 * first target account are promoted to columns so the row is still readable
 * by the rest of the app (Overview "latest draft" card, Calendar draft list).
 */

export interface ComposerDraft {
  id: string;
  updatedAt: number;
  // Caller controls the shape beyond these two — we round-trip as JSON.
  [k: string]: unknown;
}

type DraftPreview = 'threads' | 'ig-feed' | 'ig-story';

type CacheState = ComposerDraft[];

const STORAGE_PREFIX = 'juno33-composer-drafts';
const LEGACY_STORAGE_KEY = STORAGE_PREFIX;
const LEGACY_EVENT = 'juno33:composer-drafts-updated';
const cache = createHookCache<CacheState>();

function keyForUser(userKey: string | null): string | null {
  return userKey ? `${STORAGE_PREFIX}:${userKey}` : null;
}

function parseDrafts(raw: string | null): ComposerDraft[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ComposerDraft[]) : [];
  } catch {
    return [];
  }
}

function loadLocal(userKey: string | null): ComposerDraft[] {
  const storageKey = keyForUser(userKey);
  if (!storageKey || typeof localStorage === 'undefined') return [];
  try {
    const scoped = parseDrafts(localStorage.getItem(storageKey));
    if (scoped.length > 0) return scoped;

    const legacy = parseDrafts(localStorage.getItem(LEGACY_STORAGE_KEY));
    if (legacy.length === 0) return [];

    // One-way migration from the pre-user-scoped drafts key so older local
    // drafts do not disappear after the hook rollout.
    localStorage.setItem(storageKey, JSON.stringify(legacy));
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    return legacy;
  } catch {
    return [];
  }
}

function saveLocal(userKey: string | null, drafts: ComposerDraft[]) {
  const storageKey = keyForUser(userKey);
  if (!storageKey || typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(storageKey, JSON.stringify(drafts));
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    // Keep useLatestDraft (Overview widget) in sync — it listens on this event.
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(LEGACY_EVENT));
    }
  } catch {
    /* quota / disabled — silent */
  }
}

// biome-ignore lint/suspicious/noExplicitAny: metadata is JSONB
function rowToDraft(row: any): ComposerDraft | null {
  const md = row.metadata?.composerDraft;
  if (!md || typeof md !== 'object') return null;
  // Prefer the snapshot (fresh from the Composer state) but overwrite the id +
  // updatedAt with the DB row so ownership stays authoritative on the server.
  return {
    ...(md as Record<string, unknown>),
    id: row.id,
    updatedAt: row.updated_at ? Date.parse(row.updated_at) : Date.now(),
    caption: typeof md.caption === 'string' ? md.caption : row.content ?? '',
  };
}

async function resolveDraftTargetSummary(
  targetIds: string[],
  preview: DraftPreview,
  userId: string,
): Promise<{
  platform: 'threads' | 'instagram';
  accountId: string | null;
  instagramAccountId: string | null;
}> {
  const preferredPlatform = preview === 'ig-feed' || preview === 'ig-story'
    ? 'instagram'
    : 'threads';

  if (targetIds.length === 0) {
    return {
      platform: preferredPlatform,
      accountId: null,
      instagramAccountId: null,
    };
  }

  const [threadsResp, instagramResp] = await Promise.all([
    supabase
      .from('accounts')
      .select('id')
      .eq('user_id', userId)
      .in('id', targetIds),
    supabase
      .from('instagram_accounts')
      .select('id')
      .eq('user_id', userId)
      .in('id', targetIds),
  ]);

  const threadIds = new Set((threadsResp.data ?? []).map((row) => row.id));
  const instagramIds = new Set((instagramResp.data ?? []).map((row) => row.id));
  const firstThreadsId = targetIds.find((id) => threadIds.has(id)) ?? null;
  const firstInstagramId = targetIds.find((id) => instagramIds.has(id)) ?? null;

  if (preferredPlatform === 'instagram') {
    return {
      platform: 'instagram',
      accountId: null,
      instagramAccountId: firstInstagramId,
    };
  }

  return {
    platform: 'threads',
    accountId: firstThreadsId,
    instagramAccountId: null,
  };
}

// biome-ignore lint/suspicious/noExplicitAny: Draft shape varies with Composer
async function draftToInsert(draft: any, userId: string) {
  const targetIds: string[] = Array.isArray(draft.targetIds) ? draft.targetIds : [];
  const preview: DraftPreview =
    draft.preview === 'ig-feed' || draft.preview === 'ig-story' ? draft.preview : 'threads';
  // Strip uploading flags from media — we only persist finalised URLs.
  const media: Array<{ url?: string | undefined }> = Array.isArray(draft.media) ? draft.media : [];
  const mediaUrls = media
    .map((m) => m.url)
    .filter((u): u is string => typeof u === 'string' && u.length > 0);
  const targetSummary = await resolveDraftTargetSummary(targetIds, preview, userId);
  return {
    user_id: userId,
    content: typeof draft.caption === 'string' ? draft.caption : '',
    media_urls: mediaUrls,
    status: 'draft',
    platform: targetSummary.platform,
    // Preserve a first matching target at row level so cross-device summary
    // surfaces can render the correct platform/account while metadata retains
    // the full multi-target selection.
    account_id: targetSummary.accountId,
    instagram_account_id: targetSummary.instagramAccountId,
    metadata: {
      composerDraft: {
        ...draft,
        targetIds,
      },
    },
  };
}

export interface UseComposerDraftsResult {
  drafts: ComposerDraft[];
  isLoading: boolean;
  saveDraft: (draft: ComposerDraft) => Promise<ComposerDraft>;
  deleteDraft: (id: string) => Promise<void>;
  /** Called by the Composer's undo flow to atomically restore a deleted draft. */
  restoreDraft: (draft: ComposerDraft) => Promise<void>;
}

export function useComposerDrafts(): UseComposerDraftsResult {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const [drafts, setDrafts] = useState<ComposerDraft[]>(() => {
    const cached = cache.get(userKey);
    if (cached) return cached;
    // Seed from localStorage so the Composer isn't empty on first render.
    return loadLocal(userKey);
  });
  const [isLoading, setIsLoading] = useState(true);
  const migratedUsersRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    if (!authUser) {
      setIsLoading(false);
      return;
    }
    const cached = cache.get(userKey);
    if (cached) {
      setDrafts(cached);
      setIsLoading(false);
    }

    // Skip refetch if cached drafts are fresh (<30s old).
    if (cache.isFresh(userKey)) return;

    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user || cancelled) return;

      const { data, error } = await supabase
        .from('posts')
        .select('id, content, updated_at, metadata')
        .eq('user_id', user.id)
        .eq('status', 'draft')
        .order('updated_at', { ascending: false })
        .limit(50);

      if (cancelled) return;
      if (error) {
        // Keep whatever localStorage gave us — no destructive overwrite.
        setIsLoading(false);
        return;
      }

      const remote = (data ?? [])
        .map((row) => rowToDraft(row as Record<string, unknown>))
        .filter((d): d is ComposerDraft => !!d);

      // One-time migration: any localStorage-only draft (not yet on the server)
      // gets uploaded so it follows the user. Match by id.
      const migrationKey = userKey ?? user.id;
      if (!migratedUsersRef.current.has(migrationKey)) {
        migratedUsersRef.current.add(migrationKey);
        const local = loadLocal(userKey);
        const remoteIds = new Set(remote.map((r) => r.id));
        const missing = local.filter((l) => !remoteIds.has(l.id));
        for (const m of missing) {
          try {
            const insert = await draftToInsert(m, user.id);
            // We preserve the original local id so future saves upsert cleanly.
            await supabase.from('posts').insert({ id: m.id, ...insert });
          } catch {
            /* best-effort migration — ignore conflicts */
          }
        }
      }

      // Merge: server is source of truth, but if a local draft hasn't been
      // persisted yet we still keep it in the list until it either syncs or
      // gets explicitly deleted.
      const local = loadLocal(userKey);
      const merged = [
        ...remote,
        ...local.filter((l) => !remote.some((r) => r.id === l.id)),
      ].sort((a, b) => b.updatedAt - a.updatedAt);

      saveLocal(userKey, merged);
      cache.set(userKey, merged);
      if (!cancelled) {
        setDrafts(merged);
        setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [userKey, authUser]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveDraft = useCallback(
    async (draft: ComposerDraft) => {
      const stamped: ComposerDraft = { ...draft, updatedAt: Date.now() };
      // Optimistic local update first — Composer UX stays instant.
      setDrafts((prev) => {
        const next = [stamped, ...prev.filter((d) => d.id !== stamped.id)];
        saveLocal(userKey, next);
        cache.set(userKey, next);
        return next;
      });

      if (!authUser) return stamped;
      try {
        const { data: { user } } = await supabase.auth.getUser();
        if (!user) return stamped;
        const payload = await draftToInsert(stamped, user.id);
        await supabase.from('posts').upsert({ id: stamped.id, ...payload });
      } catch {
        /* offline / network — keep the local copy */
      }
      return stamped;
    },
    [authUser, userKey],
  );

  const deleteDraft = useCallback(
    async (id: string) => {
      setDrafts((prev) => {
        const next = prev.filter((d) => d.id !== id);
        saveLocal(userKey, next);
        cache.set(userKey, next);
        return next;
      });
      if (!authUser) return;
      try {
        const { data: { user } } = await supabase.auth.getUser();
        if (!user) return;
        await supabase
          .from('posts')
          .delete()
          .eq('id', id)
          .eq('user_id', user.id)
          .eq('status', 'draft');
      } catch {
        /* offline — local delete stands */
      }
    },
    [authUser, userKey],
  );

  const restoreDraft = useCallback(
    async (draft: ComposerDraft) => {
      await saveDraft(draft);
    },
    [saveDraft],
  );

  return { drafts, isLoading, saveDraft, deleteDraft, restoreDraft };
}
