import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';

export interface LatestDraft {
  id: string;
  content: string;
  targetHandle: string | null;
  targetGroupName: string | null;
  targetGroupColor: string | null;
  platform: 'threads' | 'instagram';
  targetAccountId: string | null;
  updatedAt: string | null;
}

interface State {
  draft: LatestDraft | null;
  draftCount: number;
  isLoading: boolean;
  hasError: boolean;
}

const UNASSIGNED_COLOR = '#6B6B70';
const LOCAL_DRAFTS_STORAGE_PREFIX = 'juno33-composer-drafts';
const _LEGACY_LOCAL_DRAFTS_KEY = LOCAL_DRAFTS_STORAGE_PREFIX;
const DRAFTS_UPDATED_EVENT = 'juno33:composer-drafts-updated';

interface LocalComposerDraft {
  id: string;
  updatedAt: number;
  caption?: string | undefined;
  targetIds?: string[] | undefined;
  preview?: 'threads' | 'ig-feed' | 'ig-story' | undefined;
}

function keyForUser(userKey: string | null): string | null {
  return userKey ? `${LOCAL_DRAFTS_STORAGE_PREFIX}:${userKey}` : null;
}

function parseDrafts(raw: string | null): LocalComposerDraft[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (row): row is LocalComposerDraft =>
        !!row &&
        typeof row.id === 'string' &&
        typeof row.updatedAt === 'number',
    );
  } catch {
    return [];
  }
}

function loadLocalDrafts(userKey: string | null): LocalComposerDraft[] {
  if (typeof window === 'undefined') return [];
  const scopedKey = keyForUser(userKey);
  if (!scopedKey) return [];
  return parseDrafts(window.localStorage.getItem(scopedKey));
}

/**
 * Most recently edited draft from the posts table, plus the total draft
 * count. Powers the Overview Compose card's preview.
 */
export function useLatestDraft(): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const [localRevision, setLocalRevision] = useState(0);

  useEffect(() => {
    const bump = () => setLocalRevision((n) => n + 1);
    const onStorage = (event: StorageEvent) => {
      const scopedKey = keyForUser(userKey);
      if (
        event.key === null ||
        event.key === scopedKey
      ) {
        bump();
      }
    };

    window.addEventListener(DRAFTS_UPDATED_EVENT, bump as EventListener);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(DRAFTS_UPDATED_EVENT, bump as EventListener);
      window.removeEventListener('storage', onStorage);
    };
  }, [userKey]);

  const { data, isPending, isError } = useQuery({
    queryKey: ['latestDraft', userKey, localRevision],
    enabled: !!userKey,
    queryFn: async (): Promise<Omit<State, 'isLoading' | 'hasError'>> => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return { draft: null, draftCount: 0 };

      const localDrafts = loadLocalDrafts(user.id);

      const [latestRes, idsRes] = await Promise.all([
        supabase
          .from('posts')
          .select('id, content, platform, account_id, instagram_account_id, updated_at')
          .eq('user_id', user.id)
          .eq('status', 'draft')
          .order('updated_at', { ascending: false })
          .limit(1)
          .maybeSingle(),
        supabase
          .from('posts')
          .select('id')
          .eq('user_id', user.id)
          .eq('status', 'draft'),
      ]);

      if (latestRes.error) throw latestRes.error;
      if (idsRes.error) throw idsRes.error;

      const remoteIds = new Set((idsRes.data ?? []).map((row) => row.id));
      const localOnlyDrafts = localDrafts.filter((draft) => !remoteIds.has(draft.id));
      const latestLocal =
        [...localDrafts].sort((a, b) => b.updatedAt - a.updatedAt)[0] ?? null;
      const dbRow = latestRes.data;
      const dbUpdatedAt = dbRow?.updated_at ? new Date(dbRow.updated_at).getTime() : 0;
      const useLocal = Boolean(latestLocal && (!dbRow || latestLocal.updatedAt >= dbUpdatedAt));

      if (!dbRow && !latestLocal) {
        return { draft: null, draftCount: remoteIds.size + localOnlyDrafts.length };
      }

      const platform: 'threads' | 'instagram' = useLocal
        ? latestLocal?.preview === 'ig-feed' || latestLocal?.preview === 'ig-story'
          ? 'instagram'
          : 'threads'
        : dbRow?.platform === 'instagram'
        ? 'instagram'
        : 'threads';
      let handle: string | null = null;
      let groupId: string | null = null;
      const targetAccountId = useLocal
        ? latestLocal?.targetIds?.[0] ?? null
        : platform === 'threads'
        ? dbRow?.account_id ?? null
        : dbRow?.instagram_account_id ?? null;

      if (platform === 'threads' && targetAccountId) {
        const { data } = await supabase
          .from('accounts')
          .select('username, group_id')
          .eq('id', targetAccountId)
          .eq('user_id', user.id)
          .maybeSingle();
        handle = data?.username ? `@${data.username}` : null;
        groupId = data?.group_id ?? null;
      } else if (platform === 'instagram' && targetAccountId) {
        const { data } = await supabase
          .from('instagram_accounts')
          .select('username, group_id')
          .eq('id', targetAccountId)
          .eq('user_id', user.id)
          .maybeSingle();
        handle = data?.username ? `@${data.username}` : null;
        groupId = data?.group_id ?? null;
      }

      let groupName: string | null = null;
      let groupColor: string | null = null;
      if (groupId) {
        const { data } = await supabase
          .from('account_groups')
          .select('name, color')
          .eq('id', groupId)
          .eq('user_id', user.id)
          .maybeSingle();
        groupName = data?.name ?? null;
        groupColor = data?.color ?? UNASSIGNED_COLOR;
      }

      return {
        draft: {
          id: useLocal ? latestLocal?.id ?? 'local-draft' : dbRow?.id ?? 'db-draft',
          content: useLocal ? latestLocal?.caption || '' : dbRow?.content || '',
          targetHandle: handle,
          targetGroupName: groupName,
          targetGroupColor: groupColor,
          platform,
          targetAccountId,
          updatedAt: useLocal
            ? new Date(latestLocal?.updatedAt ?? Date.now()).toISOString()
            : dbRow?.updated_at ?? null,
        },
        draftCount: remoteIds.size + localOnlyDrafts.length,
      };
    },
  });

  return {
    draft: data?.draft ?? null,
    draftCount: data?.draftCount ?? 0,
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
