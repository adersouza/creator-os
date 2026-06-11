import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { supabase } from "@/services/supabase";
import { useAuthUser } from "@/hooks/useAuthUser";

/**
 * post_templates CRUD — backs the Content Library Templates + Captions tabs.
 *
 * One table (`post_templates`) stores both shapes, differentiated by the
 * `category` column: any row where category starts with "caption" is treated
 * as a caption (short reusable snippet); everything else is a full template
 * (structured post with hashtags, media, poll options).
 */

export type TemplateCategory = "caption" | "template" | string;

export interface PostTemplateRow {
  id: string;
  name: string;
  category: string | null;
  textTemplate: string;
  platform: string | null;
  hashtags: string[];
  mediaUrls: string[];
  pollOptions: string[] | null;
  accountGroupId: string | null;
  isShared: boolean;
  timesUsed: number;
  lastUsedAt: string | null;
  createdAt: string | null;
  metadata: Record<string, unknown>;
}

interface State {
  templates: PostTemplateRow[];
  isLoading: boolean;
  hasError: boolean;
}

function isCaptionCategory(cat: string | null): boolean {
  return typeof cat === "string" && cat.toLowerCase().startsWith("caption");
}

// biome-ignore lint/suspicious/noExplicitAny: row shape is broad
function mapRow(row: any): PostTemplateRow {
  const poll = row.poll_options;
  const pollOptions = Array.isArray(poll)
    ? poll.map((o) => String(o))
    : poll && typeof poll === "object" && Array.isArray(poll.options)
      ? poll.options.map((o: unknown) => String(o))
      : null;
  return {
    id: String(row.id),
    name: String(row.name ?? "Untitled"),
    category: typeof row.category === "string" ? row.category : null,
    textTemplate:
      typeof row.text_template === "string" ? row.text_template : "",
    platform: typeof row.platform === "string" ? row.platform : null,
    hashtags: Array.isArray(row.hashtags)
      ? row.hashtags.map((h: unknown) => String(h))
      : [],
    mediaUrls: Array.isArray(row.media_urls)
      ? row.media_urls.map((u: unknown) => String(u))
      : [],
    pollOptions,
    accountGroupId:
      typeof row.account_group_id === "string" ? row.account_group_id : null,
    isShared: row.is_shared === true,
    timesUsed: typeof row.times_used === "number" ? row.times_used : 0,
    lastUsedAt: typeof row.last_used_at === "string" ? row.last_used_at : null,
    createdAt: typeof row.created_at === "string" ? row.created_at : null,
    metadata:
      row.metadata &&
      typeof row.metadata === "object" &&
      !Array.isArray(row.metadata)
        ? row.metadata
        : {},
  };
}

export interface UsePostTemplatesResult extends State {
  /** Subset matching the given category — templates (full) vs captions (snippet). */
  forCategory: (c: TemplateCategory) => PostTemplateRow[];
  createTemplate: (input: {
    name: string;
    category: TemplateCategory;
    textTemplate: string;
    platform?: string | null | undefined;
    hashtags?: string[] | undefined;
    mediaUrls?: string[] | undefined;
    metadata?: Record<string, unknown> | undefined;
  }) => Promise<PostTemplateRow | null>;
  updateTemplate: (
    id: string,
    patch: Partial<{
      name: string;
      textTemplate: string;
      hashtags: string[];
      mediaUrls: string[];
      platform: string | null;
      metadata: Record<string, unknown>;
    }>,
  ) => Promise<void>;
  deleteTemplate: (id: string) => Promise<void>;
  markUsed: (id: string) => Promise<void>;
  refetch: () => void;
}

export function usePostTemplates(): UsePostTemplatesResult {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const qc = useQueryClient();
  const queryKey = ["postTemplates", userKey] as const;

  const {
    data,
    isPending,
    isError,
    refetch: queryRefetch,
  } = useQuery({
    queryKey,
    enabled: !!userKey,
    queryFn: async (): Promise<PostTemplateRow[]> => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return [];

      const { data, error } = await supabase
        .from("post_templates")
        .select(
          "id, name, category, text_template, platform, hashtags, media_urls, poll_options, account_group_id, is_shared, times_used, last_used_at, created_at, metadata",
        )
        .eq("user_id", user.id)
        .order("times_used", { ascending: false })
        .order("last_used_at", { ascending: false, nullsFirst: false })
        .order("created_at", { ascending: false })
        .limit(200);

      if (error) throw error;
      return (data ?? []).map(mapRow);
    },
  });

  const templates = data ?? [];

  const refetch = useCallback(() => {
    void queryRefetch();
  }, [queryRefetch]);

  const forCategory = useCallback<UsePostTemplatesResult["forCategory"]>(
    (c) =>
      templates.filter((t) =>
        c === "caption"
          ? isCaptionCategory(t.category)
          : !isCaptionCategory(t.category),
      ),
    [templates],
  );

  const createTemplate = useCallback<UsePostTemplatesResult["createTemplate"]>(
    async ({
      name,
      category,
      textTemplate,
      platform,
      hashtags,
      mediaUrls,
      metadata,
    }) => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return null;
      const { data, error } = await supabase
        .from("post_templates")
        .insert({
          user_id: user.id,
          name,
          category,
          text_template: textTemplate,
          platform: platform ?? null,
          hashtags: hashtags ?? [],
          media_urls: mediaUrls ?? [],
          metadata: metadata ?? {},
        })
        .select(
          "id, name, category, text_template, platform, hashtags, media_urls, poll_options, account_group_id, is_shared, times_used, last_used_at, created_at, metadata",
        )
        .single();
      if (error || !data) return null;
      const row = mapRow(data);
      qc.setQueryData<PostTemplateRow[]>(queryKey, (prev) => [
        row,
        ...(prev ?? []),
      ]);
      return row;
    },
    [qc, queryKey],
  );

  const updateTemplate = useCallback<UsePostTemplatesResult["updateTemplate"]>(
    async (id, patch) => {
      const previous = qc.getQueryData<PostTemplateRow[]>(queryKey);
      qc.setQueryData<PostTemplateRow[]>(queryKey, (prev) =>
        (prev ?? []).map((t) =>
          t.id === id
            ? {
                ...t,
                ...(patch.name !== undefined ? { name: patch.name } : {}),
                ...(patch.textTemplate !== undefined
                  ? { textTemplate: patch.textTemplate }
                  : {}),
                ...(patch.hashtags !== undefined
                  ? { hashtags: patch.hashtags }
                  : {}),
                ...(patch.mediaUrls !== undefined
                  ? { mediaUrls: patch.mediaUrls }
                  : {}),
                ...(patch.platform !== undefined
                  ? { platform: patch.platform }
                  : {}),
                ...(patch.metadata !== undefined
                  ? { metadata: patch.metadata }
                  : {}),
              }
            : t,
        ),
      );
      const row: Record<string, unknown> = {};
      if (patch.name !== undefined) row.name = patch.name;
      if (patch.textTemplate !== undefined)
        row.text_template = patch.textTemplate;
      if (patch.hashtags !== undefined) row.hashtags = patch.hashtags;
      if (patch.mediaUrls !== undefined) row.media_urls = patch.mediaUrls;
      if (patch.platform !== undefined) row.platform = patch.platform;
      if (patch.metadata !== undefined) row.metadata = patch.metadata;
      if (Object.keys(row).length === 0) return;
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        qc.setQueryData(queryKey, previous);
        return;
      }
      const { error } = await supabase
        .from("post_templates")
        .update(row)
        .eq("id", id)
        .eq("user_id", user.id);
      if (error) {
        qc.setQueryData(queryKey, previous);
        void queryRefetch();
      }
    },
    [qc, queryKey, queryRefetch],
  );

  const deleteTemplate = useCallback<UsePostTemplatesResult["deleteTemplate"]>(
    async (id) => {
      const previous = qc.getQueryData<PostTemplateRow[]>(queryKey);
      qc.setQueryData<PostTemplateRow[]>(queryKey, (prev) =>
        (prev ?? []).filter((t) => t.id !== id),
      );
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        qc.setQueryData(queryKey, previous);
        return;
      }
      const { error } = await supabase
        .from("post_templates")
        .delete()
        .eq("id", id)
        .eq("user_id", user.id);
      if (error) {
        qc.setQueryData(queryKey, previous);
        void queryRefetch();
      }
    },
    [qc, queryKey, queryRefetch],
  );

  const markUsed = useCallback<UsePostTemplatesResult["markUsed"]>(
    async (id) => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return;
      const existing = templates.find((t) => t.id === id);
      if (!existing) return;
      const nextCount = existing.timesUsed + 1;
      const nowIso = new Date().toISOString();
      const previous = qc.getQueryData<PostTemplateRow[]>(queryKey);
      qc.setQueryData<PostTemplateRow[]>(queryKey, (prev) =>
        (prev ?? []).map((t) =>
          t.id === id ? { ...t, timesUsed: nextCount, lastUsedAt: nowIso } : t,
        ),
      );
      const { error } = await supabase
        .from("post_templates")
        .update({ times_used: nextCount, last_used_at: nowIso })
        .eq("id", id)
        .eq("user_id", user.id);
      if (error) {
        qc.setQueryData(queryKey, previous);
        void queryRefetch();
      }
    },
    [templates, qc, queryKey, queryRefetch],
  );

  return {
    templates,
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
    forCategory,
    createTemplate,
    updateTemplate,
    deleteTemplate,
    markUsed,
    refetch,
  };
}
