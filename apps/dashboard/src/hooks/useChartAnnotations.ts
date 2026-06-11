import { useQuery } from '@tanstack/react-query';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import { useAuthUser } from '@/hooks/useAuthUser';

export interface ChartAnnotation {
  id: string;
  account_id: string;
  annotation_date: string;
  label: string;
  color: string | null;
  annotation_type: string | null;
}

interface State {
  annotations: ChartAnnotation[];
  isLoading: boolean;
  hasError: boolean;
}

async function fetchAnnotations(accountId: string, days: number): Promise<ChartAnnotation[]> {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - days);
  const params = new URLSearchParams({
    action: 'annotations',
    accountId,
    startDate: start.toISOString().slice(0, 10),
    endDate: end.toISOString().slice(0, 10),
  });
  const response = await fetch(apiUrl(`/api/analytics?${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to load chart annotations');
  const data = (await response.json()) as { annotations?: ChartAnnotation[] | undefined };
  return data.annotations ?? [];
}

export function useChartAnnotations(accountId: string | null, days: number): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const enabled = !!userKey && !!accountId;

  const { data, isPending, isError } = useQuery({
    queryKey: ['chartAnnotations', userKey, accountId, days],
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchAnnotations(accountId as string, days),
  });

  return {
    annotations: data ?? [],
    isLoading: enabled && isPending,
    hasError: enabled && isError,
  };
}
