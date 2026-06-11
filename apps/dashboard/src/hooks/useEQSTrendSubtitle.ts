import { useQuery } from '@tanstack/react-query';
import { generateAiText } from '@/services/ai';
import { queryKeys } from '@/lib/queryKeys';

type PlatformKey = 'all' | 'threads' | 'ig';

interface Args {
  platform: PlatformKey;
  timeframeLabel: string;
  points: number[];
  previous: number[];
  /** Pre-computed hardcoded fallback used until AI resolves or on any error. */
  fallback: string;
}

interface State {
  text: string;
  /** True while an AI call is in flight. Hook returns fallback in this state. */
  loading: boolean;
  /** Sticks to the fallback when AI is unavailable/rate-limited. */
  source: 'fallback' | 'ai';
}

const MAX_WORDS = 28;
const PLATFORM_LABEL: Record<PlatformKey, string> = {
  all: 'fleet across Threads + Instagram',
  threads: 'Threads',
  ig: 'Instagram',
};

function buildPrompt({ platform, timeframeLabel, points, previous }: Args): string {
  const current = points[points.length - 1]?.toFixed(1) ?? '—';
  const priorMean = previous.length
    ? (previous.reduce((s, v) => s + v, 0) / previous.length).toFixed(1)
    : '—';
  const peak = Math.max(...points).toFixed(1);
  const trough = Math.min(...points).toFixed(1);
  return [
    `Summarize this Engagement Quality Score trend in a single tight sentence (≤${MAX_WORDS} words).`,
    'Use plain operator voice. No marketing language. No emoji. No prefix.',
    `Platform: ${PLATFORM_LABEL[platform]}`,
    `Timeframe: ${timeframeLabel}`,
    `EQS points over period: ${points.map((p) => p.toFixed(1)).join(', ')}`,
    `Current EQS: ${current}. Prior period mean: ${priorMean}. Peak: ${peak}. Trough: ${trough}.`,
    'Lead with the direction (up/down/flat) and one plausible driver. Return only the sentence.',
  ].join('\n');
}

/**
 * Runs a one-shot AI summary for the EQS trend card. Falls back to the
 * hardcoded subtitle on any backend error (auth not ready, AI disabled,
 * rate limited, API failure) so the UI never looks broken.
 */
export function useEQSTrendSubtitle(args: Args): State {
  const cacheKey = JSON.stringify({
    platform: args.platform,
    timeframeLabel: args.timeframeLabel,
    points: args.points,
    previous: args.previous,
    fallback: args.fallback,
  });

  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.analytics.eqsTrendSubtitle(cacheKey),
    staleTime: 60 * 60_000,
    gcTime: 24 * 60 * 60_000,
    retry: false,
    queryFn: async (): Promise<string> => {
      const raw = await generateAiText(buildPrompt(args), {
        feature: 'eqs-trend-subtitle',
        temperature: 0.4,
        maxTokens: 120,
      });
      const cleaned = raw.trim().replace(/^["']|["']$/g, '');
      if (!cleaned) throw new Error('Empty AI response');
      return cleaned;
    },
  });

  if (data) {
    return { text: data, loading: false, source: 'ai' };
  }
  if (isError) {
    return { text: args.fallback, loading: false, source: 'fallback' };
  }
  return { text: args.fallback, loading: isPending, source: 'fallback' };
}
