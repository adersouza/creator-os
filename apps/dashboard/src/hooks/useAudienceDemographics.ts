import { useEffect, useState } from 'react';
import { supabase } from '@/services/supabase';
import { apiUrl } from '@/lib/apiUrl';

export interface DemographicsData {
  ages: Array<{ bucket: string; pct: number }>;
  gender: { women: number; men: number; other: number };
  locations: Array<{ place: string; pct: number }>;
}

interface State {
  data: DemographicsData | null;
  loading: boolean;
  /** True when the backend returned usable data for this account. */
  hasRealData: boolean;
}

const memoryCache = new Map<string, DemographicsData>();

interface RawBucket { name?: string | undefined; count?: number | undefined; percentage?: number | undefined; value?: number | undefined }

/**
 * Normalize the backend's demographics payload (shape varies by platform and
 * API version) into the compact buckets the Analytics widget renders.
 * Returns null if the payload has no meaningful data.
 */
function normalize(raw: unknown): DemographicsData | null {
  if (!raw || typeof raw !== 'object') return null;
  const body = raw as Record<string, unknown>;

  const toPct = (arr: unknown): Array<{ bucket: string; pct: number }> => {
    if (!Array.isArray(arr)) return [];
    const items = (arr as RawBucket[])
      .map((item) => ({
        bucket: String(item.name ?? ''),
        raw: Number(item.percentage ?? item.count ?? item.value ?? 0),
      }))
      .filter((i) => i.bucket);
    const total = items.reduce((s, i) => s + i.raw, 0) || 1;
    return items.map((i) => ({
      bucket: i.bucket,
      pct: Math.round((i.raw / total) * 1000) / 10,
    }));
  };

  const ages = toPct(body.age_ranges ?? body.ages ?? body.ageRanges);
  const locationsRaw = toPct(body.countries ?? body.cities ?? body.locations);
  const locations = locationsRaw
    .slice(0, 5)
    .map((l) => ({ place: l.bucket, pct: l.pct }));

  const genderSrc = (body.gender ?? body.genderBreakdown) as Record<string, number> | undefined;
  let gender = { women: 0, men: 0, other: 0 };
  if (genderSrc) {
    const women = Number(genderSrc.F ?? genderSrc.female ?? genderSrc.women ?? 0);
    const men = Number(genderSrc.M ?? genderSrc.male ?? genderSrc.men ?? 0);
    const other = Number(genderSrc.U ?? genderSrc.other ?? 0);
    const total = women + men + other || 1;
    gender = {
      women: Math.round((women / total) * 100),
      men: Math.round((men / total) * 100),
      other: Math.round((other / total) * 100),
    };
  }

  if (!ages.length && !locations.length && gender.women === 0 && gender.men === 0) {
    return null;
  }
  return { ages, gender, locations };
}

/**
 * Fetch audience demographics for a scoped account via the Juno33
 * `/api/analytics?action=demographics` endpoint. Returns hasRealData=false
 * when there's no scoped account, the account lacks demographics yet
 * (Meta requires ≥100 followers), or the call fails for any reason.
 */
export function useAudienceDemographics(accountId: string | null): State {
  const [state, setState] = useState<State>({
    // biome-ignore lint/style/noNonNullAssertion: map.has() is checked before get()
    data: accountId && memoryCache.has(accountId) ? memoryCache.get(accountId)! : null,
    loading: Boolean(accountId) && !memoryCache.has(accountId ?? ''),
    hasRealData: Boolean(accountId) && memoryCache.has(accountId ?? ''),
  });

  useEffect(() => {
    if (!accountId) {
      setState({ data: null, loading: false, hasRealData: false });
      return;
    }
    const cached = memoryCache.get(accountId);
    if (cached) {
      setState({ data: cached, loading: false, hasRealData: true });
      return;
    }

    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));

    (async () => {
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session?.access_token) throw new Error('Not authenticated');

        const response = await fetch(apiUrl('/api/analytics?action=demographics'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${session.access_token}`,
          },
          body: JSON.stringify({ accountId }),
        });

        if (!response.ok) throw new Error(`Status ${response.status}`);
        const body = await response.json();
        const raw = body?.data ?? body;
        const data = normalize(raw);

        if (cancelled) return;
        if (data) {
          memoryCache.set(accountId, data);
          setState({ data, loading: false, hasRealData: true });
        } else {
          setState({ data: null, loading: false, hasRealData: false });
        }
      } catch {
        if (cancelled) return;
        setState({ data: null, loading: false, hasRealData: false });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [accountId]);

  return state;
}
