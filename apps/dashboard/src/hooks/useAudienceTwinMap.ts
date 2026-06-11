import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export type AudienceTwinPlatform = 'all' | 'instagram' | 'threads';

export interface AudienceTwinAccount {
  id: string;
  username: string | null;
  platform: 'threads' | 'instagram';
  sampleSize: number;
}

export interface AudienceTwinPair {
  similarity: number;
  accounts: [AudienceTwinAccount, AudienceTwinAccount];
  sharedSignals: string[];
}

export interface AudienceTwinCluster {
  label: string;
  accounts: AudienceTwinAccount[];
  avgSimilarity: number;
  signals: string[];
}

interface AudienceTwinMapResponse {
  platform: AudienceTwinPlatform;
  accountsWithDemographics: number;
  totalAccounts: number;
  coveragePct: number;
  pairs: AudienceTwinPair[];
  clusters: AudienceTwinCluster[];
  notes?: Record<string, unknown> | undefined;
}

interface AudienceTwinMapState extends AudienceTwinMapResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: AudienceTwinMapResponse = {
  platform: 'all',
  accountsWithDemographics: 0,
  totalAccounts: 0,
  coveragePct: 0,
  pairs: [],
  clusters: [],
  notes: {},
};

async function fetchAudienceTwinMap(platform: AudienceTwinPlatform): Promise<AudienceTwinMapResponse> {
  const params = new URLSearchParams({
    action: 'audience-twin-map',
    platform,
  });
  const response = await fetch(apiUrl(`/api/analytics?${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch audience twin map');

  const data = (await response.json()) as Partial<AudienceTwinMapResponse>;
  return {
    platform: data.platform ?? platform,
    accountsWithDemographics: data.accountsWithDemographics ?? 0,
    totalAccounts: data.totalAccounts ?? 0,
    coveragePct: data.coveragePct ?? 0,
    pairs: data.pairs ?? [],
    clusters: data.clusters ?? [],
    notes: data.notes ?? {},
  };
}

export function useAudienceTwinMap(platform: AudienceTwinPlatform = 'all'): AudienceTwinMapState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<AudienceTwinMapResponse>({
    queryKey: ['audienceTwinMap', userKey, platform],
    enabled: !!userKey,
    staleTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchAudienceTwinMap(platform),
  });

  return {
    ...(data ?? { ...EMPTY, platform }),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
