import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import { supabase } from '@/services/supabase';

export interface StoryProfileActivityPost {
  id: string;
  content: string | null;
  publishedAt: string;
  permalink: string | null;
  mediaType: string | null;
  profileVisits: number;
  follows: number;
  bioLinkTaps: number;
  score: number;
}

interface StoryProfileResponse {
  posts: StoryProfileActivityPost[];
  periodDays: number;
}

interface StoryProfileState extends StoryProfileResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: StoryProfileResponse = { posts: [], periodDays: 7 };

type ProfileActivityJson =
  | Record<string, number | null | undefined>
  | Array<{ action_type?: string | null | undefined; value?: number | null | undefined }>
  | null;

function addProfileAction(
  totals: { profileVisits: number; follows: number; bioLinkTaps: number },
  key: string,
  value: number,
) {
  const normalized = key.toLowerCase().replace(/[^a-z0-9]+/g, '_');
  if (normalized === 'profile_visits' || normalized === 'profile_visit') {
    totals.profileVisits += value;
  } else if (normalized === 'follows' || normalized === 'follow') {
    totals.follows += value;
  } else if (
    normalized === 'bio_link_taps' ||
    normalized === 'bio_link_tap' ||
    normalized === 'bio_link_clicks' ||
    normalized === 'website_clicks'
  ) {
    totals.bioLinkTaps += value;
  }
}

function normalizeProfileActivity(
  activity: ProfileActivityJson,
  directProfileVisits = 0,
  directFollows = 0,
) {
  const totals = {
    profileVisits: Number(directProfileVisits) || 0,
    follows: Number(directFollows) || 0,
    bioLinkTaps: 0,
  };
  if (Array.isArray(activity)) {
    activity.forEach((item) => {
      addProfileAction(totals, item.action_type || '', Number(item.value) || 0);
    });
  } else if (activity && typeof activity === 'object') {
    Object.entries(activity).forEach(([key, value]) => {
      addProfileAction(totals, key, Number(value) || 0);
    });
  }
  return totals;
}

async function fetchPostBackedActivity(
  userId: string,
  periodDays: number,
  accountId: string | null,
): Promise<StoryProfileResponse> {
  const since = new Date();
  since.setDate(since.getDate() - periodDays);
  since.setHours(0, 0, 0, 0);

  let query = supabase
    .from('posts')
    .select(
      'id, content, published_at, permalink, ig_post_profile_activity, ig_profile_visits, ig_follows_count, media_type',
    )
    .eq('user_id', userId)
    .eq('platform', 'instagram')
    .eq('status', 'published')
    .gte('published_at', since.toISOString());
  if (accountId) query = query.eq('instagram_account_id', accountId);

  const { data, error } = await query;
  if (error) throw error;

  const posts = ((data ?? []) as Array<{
    id: string;
    content: string | null;
    published_at: string;
    permalink: string | null;
    ig_post_profile_activity: ProfileActivityJson;
    ig_profile_visits: number | null;
    ig_follows_count: number | null;
    media_type: string | null;
  }>)
    .map((post) => {
      const activity = normalizeProfileActivity(
        post.ig_post_profile_activity,
        post.ig_profile_visits || 0,
        post.ig_follows_count || 0,
      );
      const score = activity.profileVisits + activity.follows * 3;
      return {
        id: post.id,
        content: post.content,
        publishedAt: post.published_at,
        permalink: post.permalink,
        mediaType: post.media_type,
        profileVisits: activity.profileVisits,
        follows: activity.follows,
        bioLinkTaps: activity.bioLinkTaps,
        score,
      };
    })
    .filter((post) => post.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);

  return { posts, periodDays };
}

async function fetchActivity(
  periodDays: number,
  accountId: string | null,
): Promise<StoryProfileResponse> {
  const params = new URLSearchParams({ periodDays: String(periodDays) });
  if (accountId) params.set('accountId', accountId);
  const response = await fetch(
    apiUrl(`/api/analytics?action=story-profile-activity&${params}`),
    {
      headers: await getApiAuthHeaders(),
    },
  );
  if (!response.ok) throw new Error('Failed to fetch story profile activity');
  const data = (await response.json()) as StoryProfileResponse;
  return {
    posts: data.posts ?? [],
    periodDays: data.periodDays ?? periodDays,
  };
}

/**
 * IG posts (stories + feed + reels) ranked by profile-activity lifts:
 * profile_visits + 3×follows. Follows weighted higher — they're the
 * higher-intent outcome of a profile visit.
 */
export function useStoryProfileActivity(
  periodDays: number = 7,
  accountId: string | null = null,
): StoryProfileState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<StoryProfileResponse>({
    queryKey: ['storyProfileActivity', userKey, periodDays, accountId],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      try {
        return await fetchActivity(periodDays, accountId);
      } catch (error) {
        if (!userKey) throw error;
        return fetchPostBackedActivity(userKey, periodDays, accountId);
      }
    },
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
