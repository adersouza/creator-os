import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "@/services/supabase";
import { useAuthUser } from "@/hooks/useAuthUser";
import { createHookCache } from "@/hooks/_hookCache";

/**
 * Smart Links CRUD — reads/writes against the user's `public.smart_links`.
 *
 * Core fields: code, title, target_url, is_active. Plus linktree extras the
 * detail view owns: items (rider links), utm (builder), theme.
 */

export interface SmartLinkItem {
  id: string;
  title: string;
  url: string;
  clicks: number;
  blockType?: string | undefined;
  subtitle?: string | undefined;
  metadata?: Record<string, unknown> | undefined;
}

export interface SmartLinkUtm {
  source?: string | undefined;
  medium?: string | undefined;
  campaign?: string | undefined;
}

export interface SmartLinkRow {
  id: string;
  code: string;
  title: string | null;
  targetUrl: string;
  clickCount: number;
  isActive: boolean;
  postId: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  utm: SmartLinkUtm | null;
  theme: string | null;
  items: SmartLinkItem[];
  blocks: SmartLinkItem[];
  metadata: Record<string, unknown> | null;
}

interface State {
  links: SmartLinkRow[];
  isLoading: boolean;
}

export interface UseSmartLinksResult extends State {
  createLink: (input: {
    title: string;
    code: string;
    targetUrl: string;
    isActive?: boolean | undefined;
  }) => Promise<SmartLinkRow | null>;
  updateLink: (
    id: string,
    patch: Partial<{
      title: string;
      code: string;
      targetUrl: string;
      isActive: boolean;
      utm: SmartLinkUtm;
      theme: string;
      items: SmartLinkItem[];
      metadata: Record<string, unknown>;
    }>,
  ) => Promise<void>;
  deleteLink: (id: string) => Promise<void>;
  refetch: () => void;
}

const cache = createHookCache<State>();

// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape is broad
function mapRow(row: any): SmartLinkRow {
  const rawItems = Array.isArray(row.blocks)
    ? row.blocks
    : Array.isArray(row.items)
      ? row.items
      : [];
  const items: SmartLinkItem[] = rawItems
    // biome-ignore lint/suspicious/noExplicitAny: jsonb blob
    .map((raw: any) => ({
      id: typeof raw?.id === "string" ? raw.id : "",
      title: typeof raw?.title === "string" ? raw.title : "",
      url: typeof raw?.url === "string" ? raw.url : "",
      clicks: typeof raw?.clicks === "number" ? raw.clicks : 0,
      blockType: typeof raw?.blockType === "string" ? raw.blockType : undefined,
      subtitle: typeof raw?.subtitle === "string" ? raw.subtitle : undefined,
      metadata:
        raw?.metadata &&
        typeof raw.metadata === "object" &&
        !Array.isArray(raw.metadata)
          ? raw.metadata
          : undefined,
    }))
    .filter((it: SmartLinkItem) => it.id);
  const rawUtm = row.utm && typeof row.utm === "object" ? row.utm : null;
  const utm: SmartLinkUtm | null = rawUtm
    ? {
        source: typeof rawUtm.source === "string" ? rawUtm.source : undefined,
        medium: typeof rawUtm.medium === "string" ? rawUtm.medium : undefined,
        campaign:
          typeof rawUtm.campaign === "string" ? rawUtm.campaign : undefined,
      }
    : null;
  return {
    id: String(row.id),
    code: String(row.code ?? ""),
    title: typeof row.title === "string" ? row.title : null,
    targetUrl: String(row.target_url ?? ""),
    clickCount: typeof row.click_count === "number" ? row.click_count : 0,
    isActive: row.is_active !== false,
    postId: typeof row.post_id === "string" ? row.post_id : null,
    createdAt: typeof row.created_at === "string" ? row.created_at : null,
    updatedAt: typeof row.updated_at === "string" ? row.updated_at : null,
    utm,
    theme: typeof row.theme === "string" ? row.theme : null,
    items,
    blocks: items,
    metadata:
      row.metadata &&
      typeof row.metadata === "object" &&
      !Array.isArray(row.metadata)
        ? row.metadata
        : null,
  };
}

const SELECT_COLUMNS =
  "id, code, title, target_url, click_count, is_active, post_id, created_at, updated_at, utm, theme, items, blocks, metadata";

export function useSmartLinks(): UseSmartLinksResult {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const [state, setState] = useState<State>(() => {
    const cached = cache.get(userKey);
    if (cached) return { ...cached, isLoading: false };
    return { links: [], isLoading: true };
  });
  const [_nonce, setNonce] = useState(0);
  const forceRefetchRef = useRef(false);
  const refetch = useCallback(() => {
    forceRefetchRef.current = true;
    setNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!authUser) {
      // Stay loading while auth hydrates — empty-state flash otherwise.
      return;
    }

    const cached = cache.get(userKey);
    if (cached) setState({ ...cached, isLoading: false });

    const shouldForceRefetch = forceRefetchRef.current;
    forceRefetchRef.current = false;

    // Skip refetch if cached payload is fresh (<30s old).
    if (!shouldForceRefetch && cache.isFresh(userKey)) return;

    (async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user || cancelled) return;

      const { data, error } = await supabase
        .from("smart_links")
        .select(SELECT_COLUMNS)
        .eq("user_id", user.id)
        .order("created_at", { ascending: false })
        .limit(200);

      if (cancelled) return;
      if (error) {
        setState((s) => ({ ...s, isLoading: false }));
        return;
      }

      const links = (data ?? []).map(mapRow);
      const next: State = { links, isLoading: false };
      cache.set(userKey, next);
      setState(next);
    })();

    return () => {
      cancelled = true;
    };
  }, [userKey, authUser]);

  const createLink = useCallback<UseSmartLinksResult["createLink"]>(
    async ({ title, code, targetUrl, isActive = true }) => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return null;
      const { data, error } = await supabase
        .from("smart_links")
        .insert({
          user_id: user.id,
          code,
          title,
          target_url: targetUrl,
          is_active: isActive,
        })
        .select(SELECT_COLUMNS)
        .single();
      if (error || !data) return null;
      const row = mapRow(data);
      setState((s) => {
        const next: State = { ...s, links: [row, ...s.links] };
        cache.set(userKey, next);
        return next;
      });
      return row;
    },
    [userKey],
  );

  const updateLink = useCallback<UseSmartLinksResult["updateLink"]>(
    async (id, patch) => {
      let previous: SmartLinkRow | null = null;
      setState((s) => {
        previous = s.links.find((l) => l.id === id) ?? null;
        const next: State = {
          ...s,
          links: s.links.map((l) =>
            l.id === id
              ? {
                  ...l,
                  ...(patch.title !== undefined ? { title: patch.title } : {}),
                  ...(patch.code !== undefined ? { code: patch.code } : {}),
                  ...(patch.targetUrl !== undefined
                    ? { targetUrl: patch.targetUrl }
                    : {}),
                  ...(patch.isActive !== undefined
                    ? { isActive: patch.isActive }
                    : {}),
                  ...(patch.utm !== undefined ? { utm: patch.utm } : {}),
                  ...(patch.theme !== undefined ? { theme: patch.theme } : {}),
                  ...(patch.items !== undefined ? { items: patch.items } : {}),
                  ...(patch.items !== undefined ? { blocks: patch.items } : {}),
                  ...(patch.metadata !== undefined
                    ? { metadata: patch.metadata }
                    : {}),
                }
              : l,
          ),
        };
        cache.set(userKey, next);
        return next;
      });
      const row: Record<string, unknown> = {};
      if (patch.title !== undefined) row.title = patch.title;
      if (patch.code !== undefined) row.code = patch.code;
      if (patch.targetUrl !== undefined) row.target_url = patch.targetUrl;
      if (patch.isActive !== undefined) row.is_active = patch.isActive;
      if (patch.utm !== undefined) row.utm = patch.utm;
      if (patch.theme !== undefined) row.theme = patch.theme;
      if (patch.items !== undefined) row.items = patch.items;
      if (patch.items !== undefined) row.blocks = patch.items;
      if (patch.metadata !== undefined) row.metadata = patch.metadata;
      if (Object.keys(row).length === 0) return;
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        if (previous) {
          const rollback = previous;
          setState((s) => {
            const next: State = {
              ...s,
              links: s.links.map((l) => (l.id === id ? rollback : l)),
            };
            cache.set(userKey, next);
            return next;
          });
        }
        return;
      }
      const { data, error } = await supabase
        .from("smart_links")
        .update(row)
        .eq("id", id)
        .eq("user_id", user.id)
        .select(SELECT_COLUMNS)
        .maybeSingle();
      if (error && previous) {
        const rollback = previous;
        setState((s) => {
          const next: State = {
            ...s,
            links: s.links.map((l) => (l.id === id ? rollback : l)),
          };
          cache.set(userKey, next);
          return next;
        });
        return;
      }
      // Rehydrate local state with server truth so updated_at + any
      // trigger-managed fields don't drift away from what the DB actually
      // stored. Without this, relLastEdited() shows the pre-edit timestamp.
      if (data) {
        const fresh = mapRow(data);
        setState((s) => {
          const next: State = {
            ...s,
            links: s.links.map((l) => (l.id === id ? fresh : l)),
          };
          cache.set(userKey, next);
          return next;
        });
      }
    },
    [userKey],
  );

  const deleteLink = useCallback<UseSmartLinksResult["deleteLink"]>(
    async (id) => {
      let previous: SmartLinkRow | null = null;
      setState((s) => {
        previous = s.links.find((l) => l.id === id) ?? null;
        const next: State = { ...s, links: s.links.filter((l) => l.id !== id) };
        cache.set(userKey, next);
        return next;
      });
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        if (previous) {
          setState((s) => {
            // biome-ignore lint/style/noNonNullAssertion: previous is guarded by outer if(previous) check; TypeScript cannot narrow through setState closure
            const next: State = { ...s, links: [previous!, ...s.links] };
            cache.set(userKey, next);
            return next;
          });
        }
        return;
      }
      const { error } = await supabase
        .from("smart_links")
        .delete()
        .eq("id", id)
        .eq("user_id", user.id);
      if (error && previous) {
        setState((s) => {
          // biome-ignore lint/style/noNonNullAssertion: previous is guarded by outer if(previous) check; TypeScript cannot narrow through setState closure
          const next: State = { ...s, links: [previous!, ...s.links] };
          cache.set(userKey, next);
          return next;
        });
      }
    },
    [userKey],
  );

  return { ...state, createLink, updateLink, deleteLink, refetch };
}
