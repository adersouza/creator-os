import { useMutation } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';

const NL_QUERY_TIMEOUT_MS = 12_000;

export type NlPlatform = 'threads' | 'instagram' | 'all';
export type NlGroupBy = 'account' | 'day' | 'none';

export interface NlQuerySpec {
  metric: string;
  timeframeDays: number;
  platform: NlPlatform;
  groupBy: NlGroupBy;
  limit: number;
  orderBy: 'asc' | 'desc';
}

export interface NlQueryRow {
  label: string;
  value: number;
}

export interface NlAvailableMetric {
  key: string;
  platforms: Array<'threads' | 'instagram'>;
  description: string;
}

export interface NlQueryResult {
  spec: NlQuerySpec;
  interpretation: string;
  rows: NlQueryRow[];
  aggregate: number;
  matchedAccounts: number;
  dataThrough?: string | null | undefined;
  stale?: boolean | undefined;
  usedLLM: boolean;
  scope?: {
    accountId: string | null;
    groupId: string | null;
    workspaceId?: string | null | undefined;
    accountCount: number;
  } | undefined;
  availableMetrics: NlAvailableMetric[];
}

export interface NlQueryInput {
  prompt?: string | undefined;
  specOverride?: Partial<NlQuerySpec> | undefined;
  accountId?: string | undefined;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
  workspaceId?: string | null | undefined;
  platform?: NlPlatform | undefined;
}

async function postNlQuery(input: NlQueryInput): Promise<NlQueryResult> {
  const session = (await supabase.auth.getSession()).data.session;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), NL_QUERY_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch('/api/ai?action=nl-query', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(session?.access_token
          ? { Authorization: `Bearer ${session.access_token}` }
          : {}),
      },
      body: JSON.stringify(input),
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('The analytics AI query timed out. Try a narrower question.');
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      code?: string | undefined;
      error?: string | undefined;
    };
    if (body.code === 'RATE_LIMITED') {
      throw new Error('You have hit the hourly AI rate limit.');
    }
    if (body.code === 'NO_API_KEY') {
      throw new Error('Add an AI API key in Settings to use the NL query box.');
    }
    throw new Error(body.error ?? 'Query failed');
  }
  return (await response.json()) as NlQueryResult;
}

export function useNlQuery() {
  return useMutation<NlQueryResult, Error, NlQueryInput>({
    mutationFn: postNlQuery,
  });
}
