// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { generateAiText } from '@/services/ai';
import { queryKeys } from '@/lib/queryKeys';

export interface HookPattern {
  pattern: string;
  posts: number;
  avgEQS: number;
  lift: string;
  dir: 'up' | 'down';
}

interface State {
  patterns: HookPattern[];
  loading: boolean;
  /** True when backend returned enough posts + AI produced parseable output. */
  hasRealData: boolean;
}

const LOOKBACK_DAYS = 60;
const MIN_POSTS = 30;

interface PostRow {
  content: string | null;
  likes_count: number | null;
  replies_count: number | null;
  reposts_count: number | null;
  views_count: number | null;
}

interface ScoredPost {
  firstLine: string;
  eqs: number;
}

function computeEQS(row: PostRow): number {
  const sends = 0;
  const saves = 0;
  const comments = row.replies_count ?? 0;
  const likes = row.likes_count ?? 0;
  const reposts = row.reposts_count ?? 0;
  const views = Math.max(1, row.views_count ?? 0);
  const weighted = sends * 5 + saves * 3 + comments * 2 + likes * 1 + reposts * 1.5;
  return (weighted / views) * 100;
}

function firstLineOf(content: string | null): string | null {
  if (!content) return null;
  const trimmed = content.trim();
  if (!trimmed) return null;
  const line = trimmed.split(/\r?\n/)[0]!.trim();
  return line.slice(0, 200) || null;
}

function buildPrompt(top: ScoredPost[], bottom: ScoredPost[]): string {
  const topBlock = top.map((p, i) => `${i + 1}. "${p.firstLine}" (EQS ${p.eqs.toFixed(1)})`).join('\n');
  const botBlock = bottom.map((p, i) => `${i + 1}. "${p.firstLine}" (EQS ${p.eqs.toFixed(1)})`).join('\n');
  const avgTop = (top.reduce((s, p) => s + p.eqs, 0) / Math.max(1, top.length)).toFixed(1);
  const avgBot = (bottom.reduce((s, p) => s + p.eqs, 0) / Math.max(1, bottom.length)).toFixed(1);

  return [
    'Analyze these Threads post first-lines and identify 5–7 recurring opener patterns.',
    'Group openers by linguistic template (curiosity hook, vulnerability, hot take, reminder, product push, question, etc.).',
    `Score each pattern by appearance in top decile (avg EQS ${avgTop}) vs bottom decile (avg EQS ${avgBot}).`,
    '',
    'TOP decile first-lines:',
    topBlock,
    '',
    'BOTTOM decile first-lines:',
    botBlock,
    '',
    'Return ONLY a JSON array with this exact shape, no prose, no code fences:',
    '[{"pattern":"\\"Nobody tells you…\\"","posts":14,"avgEQS":86.2,"lift":"+41%","dir":"up"}]',
    'Rules:',
    '- pattern: short quoted template (≤40 chars) that captures the opener style',
    '- posts: count of first-lines matching that template across both deciles',
    '- avgEQS: mean EQS for matching first-lines, 1 decimal',
    '- lift: percent delta vs overall mean, with sign ("+41%" or "-32%")',
    '- dir: "up" if lift positive, "down" if negative',
    '- 5 to 7 items, sorted by absolute lift descending',
    '- Prefer patterns that appear in ≥3 posts; skip one-offs',
    'No commentary. JSON array only.',
  ].join('\n');
}

function parsePatterns(raw: string): HookPattern[] | null {
  try {
    const cleaned = raw
      .trim()
      .replace(/^```(?:json)?\s*/i, '')
      .replace(/```\s*$/, '')
      .trim();
    const parsed = JSON.parse(cleaned);
    if (!Array.isArray(parsed)) return null;
    const normalized: HookPattern[] = [];
    for (const item of parsed) {
      if (!item || typeof item !== 'object') continue;
      const pattern = typeof item.pattern === 'string' ? item.pattern.slice(0, 60) : null;
      const posts = Number(item.posts);
      const avgEQS = Number(item.avgEQS);
      const lift = typeof item.lift === 'string' ? item.lift : null;
      const dir = item.dir === 'up' || item.dir === 'down' ? item.dir : null;
      if (!pattern || !Number.isFinite(posts) || !Number.isFinite(avgEQS) || !lift || !dir) continue;
      normalized.push({ pattern, posts, avgEQS: Math.round(avgEQS * 10) / 10, lift, dir });
    }
    return normalized.length > 0 ? normalized.slice(0, 7) : null;
  } catch {
    return null;
  }
}

interface HookPatternsResult {
  patterns: HookPattern[];
  hasRealData: boolean;
}

const EMPTY: HookPatternsResult = { patterns: [], hasRealData: false };

/**
 * Threads-only opener-pattern NLP widget. Pulls the user's last 60 days of
 * published Threads posts, splits into top/bottom deciles by computed EQS,
 * and asks the backend AI to cluster the first-lines into templates. Returns
 * hasRealData=false when there are fewer than MIN_POSTS posts or any step
 * fails, so the caller can surface an empty state.
 */
export function useHookPatterns(accountId: string | null = null): State {
  const authUser = useAuthUser();
  const userKey = authUser?.id ?? null;

  const { data, isPending } = useQuery({
    queryKey: queryKeys.analytics.hookPatterns(userKey, accountId),
    enabled: !!userKey,
    staleTime: 60 * 60_000,
    gcTime: 24 * 60 * 60_000,
    retry: false,
    queryFn: async (): Promise<HookPatternsResult> => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return EMPTY;

      const since = new Date();
      since.setDate(since.getDate() - LOOKBACK_DAYS);

      let query = supabase
        .from('posts')
        .select('content, likes_count, replies_count, reposts_count, views_count')
        .eq('user_id', user.id)
        .eq('status', 'published')
        .eq('platform', 'threads')
        .gte('published_at', since.toISOString())
        .limit(500);
      if (accountId) query = query.eq('account_id', accountId);

      const { data, error } = await query;
      if (error) throw error;

      const scored: ScoredPost[] = [];
      for (const row of (data ?? []) as PostRow[]) {
        const firstLine = firstLineOf(row.content);
        if (!firstLine) continue;
        scored.push({ firstLine, eqs: computeEQS(row) });
      }

      if (scored.length < MIN_POSTS) return EMPTY;

      const sorted = [...scored].sort((a, b) => b.eqs - a.eqs);
      const decileSize = Math.max(5, Math.floor(sorted.length / 10));
      const top = sorted.slice(0, decileSize);
      const bottom = sorted.slice(-decileSize);

      const raw = await generateAiText(buildPrompt(top, bottom), {
        feature: 'hook-patterns',
        temperature: 0.2,
        maxTokens: 800,
      });
      const patterns = parsePatterns(raw);
      if (!patterns) throw new Error('Could not parse hook-pattern response');
      return { patterns, hasRealData: true };
    },
  });

  return {
    patterns: data?.patterns ?? [],
    hasRealData: data?.hasRealData ?? false,
    loading: !!userKey && isPending,
  };
}
