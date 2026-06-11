import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';

export interface SaturationAlert {
  pattern: string;
  uses: number;
  window: string;
  status: 'high' | 'watch';
  note: string;
}

export interface ContentSaturationState {
  alerts: SaturationAlert[];
  hasRealData: boolean;
  loading: boolean;
}

const MIN_POSTS = 30;
const HIGH_THRESHOLD = 6;
const WATCH_THRESHOLD = 4;

// Common English stop words to exclude from pattern detection.
const STOP_WORDS = new Set([
  'a','an','the','and','or','but','in','on','at','to','for','of','with',
  'is','are','was','were','be','been','have','has','had','do','did','will',
  'would','could','should','may','might','i','you','we','they','it','this',
  'that','my','your','our','their','its','me','him','her','us','them',
  'how','what','when','where','who','why','which','all','some','any',
  'get','got','can','just','about','out','up','so','from','not','if',
  'no','yes','more','less','one','two','new','day','time','week','month',
]);

function extractPatterns(posts: { content: string | null; ig_media_type: string | null }[]): Map<string, number> {
  const counts = new Map<string, number>();

  for (const post of posts) {
    const text = (post.content ?? '').toLowerCase();

    // Hashtags — high-signal repeated topics.
    const hashtags = text.match(/#[a-z0-9_]{2,}/g) ?? [];
    for (const tag of hashtags) {
      counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }

    // Meaningful 2-grams from non-hashtag text.
    const words = text.replace(/#[a-z0-9_]+/g, '').split(/\W+/).filter((w) => w.length > 3 && !STOP_WORDS.has(w));
    for (let i = 0; i < words.length - 1; i++) {
      const bigram = `${words[i]} ${words[i + 1]}`;
      counts.set(bigram, (counts.get(bigram) ?? 0) + 1);
    }

    // Media type patterns (detect format overuse).
    const mt = (post.ig_media_type ?? '').toUpperCase();
    if (mt === 'REELS') counts.set('[reels]', (counts.get('[reels]') ?? 0) + 1);
    if (mt === 'STORIES') counts.set('[stories]', (counts.get('[stories]') ?? 0) + 1);
  }

  return counts;
}

function buildAlerts(counts: Map<string, number>, windowDays: number): SaturationAlert[] {
  const windowLabel = `${windowDays}d`;
  const alerts: SaturationAlert[] = [];

  for (const [pattern, uses] of counts.entries()) {
    if (uses < WATCH_THRESHOLD) continue;

    const isMediaType = pattern.startsWith('[') && pattern.endsWith(']');
    const displayPattern = isMediaType
      ? pattern === '[reels]' ? 'Reels posts' : 'Stories posts'
      : pattern.startsWith('#') ? `${pattern} content` : pattern;

    const status: 'high' | 'watch' = uses >= HIGH_THRESHOLD ? 'high' : 'watch';
    const note = status === 'high'
      ? `Used ${uses}× — audience fatigue risk. Try a different angle.`
      : `At ${uses}× — nearing fatigue threshold (${HIGH_THRESHOLD}).`;

    alerts.push({ pattern: displayPattern, uses, window: windowLabel, status, note });
  }

  return alerts
    .sort((a, b) => b.uses - a.uses)
    .slice(0, 4);
}

function daysToCutoff(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

export function useContentSaturation(
  windowDays: 30 | 60 | 90 = 30,
  instagramAccountId?: string | null,
): ContentSaturationState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: ['contentSaturation', userKey, windowDays, instagramAccountId ?? null],
    enabled: !!userKey,
    staleTime: 1000 * 60 * 30,
    queryFn: async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return { alerts: [], hasRealData: false } as Omit<ContentSaturationState, 'loading'>;

      const since = daysToCutoff(windowDays);
      let query = supabase
        .from('posts')
        .select('content, ig_media_type')
        .eq('user_id', user.id)
        .eq('status', 'published')
        .eq('platform', 'instagram')
        .gte('published_at', since)
        .not('published_at', 'is', null);

      if (instagramAccountId) {
        query = query.eq('instagram_account_id', instagramAccountId);
      }

      const { data: posts, error } = await query;

      if (error) throw error;
      if (!posts || posts.length < MIN_POSTS) return { alerts: [], hasRealData: false };

      const counts = extractPatterns(posts);
      const alerts = buildAlerts(counts, windowDays);

      return { alerts, hasRealData: true };
    },
  });

  return {
    ...(data ?? { alerts: [], hasRealData: false }),
    loading: !!userKey && isPending,
  };
}
