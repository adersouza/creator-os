import { useMutation, useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import type { NarrativeSegment, NarrativeTemplate } from '@/components/analytics-v2/hero/narratives';

export type NarrativePlatform = 'all' | 'ig' | 'threads';

/** Mirrors api/_lib/handlers/ai/generate-narrative.ts BodySchema. */
export interface NarrativeInput {
  platform: NarrativePlatform;
  reachDeltaPct: number | null | undefined;
  atRiskCount: number;
  accountCount: number;
  anomalyCount?: number | undefined;
  topAnomalies?: Array<{
            accountLabel?: string | undefined;
            reason: string;
            severity: 'critical' | 'warning';
            description?: string | undefined;
          }> | undefined;
  cohortPercentile?: number | null | undefined;
  nicheLabel?: string | null | undefined;
}

export interface NarrativeBriefState {
  narrative: NarrativeTemplate | null;
  isLoading: boolean;
  hasError: boolean;
  /** True when we successfully generated a fresh narrative (not stale / fallback). */
  isFresh: boolean;
  /** ISO timestamp of when the LLM call completed — null when no live narrative
   *  is available. Tiles use this to render an honest "as of HH:MM" eyebrow
   *  instead of the page-load wall clock. */
  generatedAt: string | null;
  /** Refresh on demand (e.g. "Regenerate" button). */
  refetch: () => void;
}

interface ServerNarrative {
  eyebrow: string;
  headline: string;
  body: Array<string | { kind: 'ev'; text: string; n: number }>;
  anomalyBadge: string;
}

interface CachedNarrative {
  narrative: ServerNarrative;
  updatedAt: number;
}

const NARRATIVE_TIMEOUT_MS = 10_000;
const NARRATIVE_STALE_TIME_MS = 60 * 60 * 1000;
const NARRATIVE_GC_TIME_MS = 6 * 60 * 60 * 1000;
const NARRATIVE_CACHE_VERSION = 'v1';

async function fetchNarrative(input: NarrativeInput): Promise<ServerNarrative> {
  const session = (await supabase.auth.getSession()).data.session;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), NARRATIVE_TIMEOUT_MS);
  const response = await fetch('/api/ai?action=generate-narrative', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(session?.access_token
        ? { Authorization: `Bearer ${session.access_token}` }
        : {}),
    },
    body: JSON.stringify(input),
    signal: controller.signal,
  }).finally(() => window.clearTimeout(timeout));
  if (!response.ok) {
    // Propagate status so the caller can quietly fall back on 503 (no AI key)
    // or 429 (rate limit) without surfacing a scary error.
    throw Object.assign(new Error('narrative unavailable'), {
      status: response.status,
    });
  }
  const body = (await response.json()) as {
    success: boolean;
    narrative: ServerNarrative;
  };
  return body.narrative;
}

function toTemplate(n: ServerNarrative): NarrativeTemplate {
  // anomalyBadge is returned by the server but not used by HeroTile (it
  // renders its own pill from useAnomalyFeed). Dropping it keeps the
  // template type narrow.
  return {
    eyebrow: n.eyebrow,
    headline: n.headline,
    body: n.body as NarrativeSegment[],
  };
}

/**
 * LLM-generated hero narrative (spec §3 / §12). Feeds fleet deltas + top
 * anomalies to Gemini and returns a narrative in the same shape as the
 * hardcoded NARRATIVES table in hero/narratives.ts.
 *
 * Caller is expected to own the fallback (HeroTile renders the hardcoded
 * narrative when `narrative` is null, `hasError` is true, or `isLoading`
 * is still true on first paint). Token placeholders like {{REACH_DELTA}}
 * inside the headline are filled client-side by `fillTokens`.
 *
 * Queries are keyed on a compact, rounded input signature so changing view or
 * meaningful fleet state refetches, but tiny data churn does not spend tokens.
 */
export function useNarrativeBrief(
  input: NarrativeInput | null,
  opts: { enabled?: boolean | undefined } = {},
): NarrativeBriefState {
  const { enabled = true } = opts;
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const inputKey = input ? cacheKey(input) : null;
  const persisted = userKey && inputKey ? readNarrativeCache(userKey, inputKey) : null;

  // A short stable digest of the inputs as the query key. The shape can be
  // large (top anomaly list), so hash by serialising deterministically.
  const queryKey = [
    'narrativeBrief',
    userKey,
    inputKey,
  ];

  const isEnabled = !!userKey && enabled && input !== null;

  const queryOptions = {
    queryKey,
    enabled: isEnabled,
    staleTime: NARRATIVE_STALE_TIME_MS,
    gcTime: NARRATIVE_GC_TIME_MS,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
    queryFn: async () => {
      if (!input) throw new Error('no narrative input');
      const narrative = await fetchNarrative(input);
      if (userKey && inputKey) {
        writeNarrativeCache(userKey, inputKey, narrative);
      }
      return narrative;
    },
    ...(persisted?.narrative ? { initialData: persisted.narrative } : {}),
    ...(persisted?.updatedAt ? { initialDataUpdatedAt: persisted.updatedAt } : {}),
  };

  const { data, isPending, isError, refetch, dataUpdatedAt } = useQuery<ServerNarrative, Error>(queryOptions);

  return {
    narrative: data ? toTemplate(data) : null,
    isLoading: isEnabled && isPending,
    hasError: isEnabled && isError,
    isFresh: !!data,
    generatedAt: data && dataUpdatedAt ? new Date(dataUpdatedAt).toISOString() : null,
    refetch: () => {
      void refetch();
    },
  };
}

function cacheKey(input: NarrativeInput): string {
  const anomaliesKey = (input.topAnomalies ?? [])
    .slice(0, 5)
    .map((a) => `${a.severity}:${a.accountLabel ?? ''}:${a.reason}`)
    .join('|');
  const reachDelta =
    typeof input.reachDeltaPct === 'number' && Number.isFinite(input.reachDeltaPct)
      ? Math.round(input.reachDeltaPct * 10) / 10
      : '';
  const cohortPercentile =
    typeof input.cohortPercentile === 'number' && Number.isFinite(input.cohortPercentile)
      ? Math.round(input.cohortPercentile)
      : '';
  return [
    input.platform,
    reachDelta,
    input.atRiskCount,
    input.accountCount,
    input.anomalyCount ?? 0,
    cohortPercentile,
    input.nicheLabel ?? '',
    anomaliesKey,
  ].join('/');
}

function storageKey(userKey: string, inputKey: string): string {
  return `juno33:analytics:narrative:${NARRATIVE_CACHE_VERSION}:${userKey}:${inputKey}`;
}

function readNarrativeCache(userKey: string, inputKey: string): CachedNarrative | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(storageKey(userKey, inputKey));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CachedNarrative;
    if (!parsed?.narrative || typeof parsed.updatedAt !== 'number') return null;
    if (Date.now() - parsed.updatedAt > NARRATIVE_STALE_TIME_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeNarrativeCache(
  userKey: string,
  inputKey: string,
  narrative: ServerNarrative,
): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(
      storageKey(userKey, inputKey),
      JSON.stringify({ narrative, updatedAt: Date.now() } satisfies CachedNarrative),
    );
  } catch {
    // Storage can be full or disabled; React Query's in-memory cache still works.
  }
}

/**
 * Imperative mutation alternative — exposed for callers that want an
 * explicit "regenerate narrative" button (HeroTile doesn't use this yet
 * but the handler is ready). Returned errors carry .status when the server
 * responded with a non-2xx, matching fetchNarrative's behavior.
 */
export function useGenerateNarrative() {
  return useMutation<ServerNarrative, Error, NarrativeInput>({
    mutationFn: (input) => fetchNarrative(input),
  });
}
