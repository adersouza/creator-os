import { useCallback, useEffect, useRef, useState } from 'react';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { createHookCache } from '@/hooks/_hookCache';

/**
 * Reports CRUD — reads/writes `public.reports`.
 *
 * The Reports page also surfaces a derived "size" (PDF byte size) and a "shared"
 * flag — neither is persisted here yet. Size ships once the PDF renderer does;
 * `shared` is computed from `recipients.length > 0`.
 */

export type ReportType = 'scheduled' | 'one-off';
export type ReportCadence = 'weekly' | 'monthly' | 'quarterly' | 'one-off';
export type ReportStatus = 'active' | 'paused' | 'generated' | 'draft';

export interface ReportRecipient {
  email: string;
  name?: string | undefined;
}

export interface ReportRow {
  id: string;
  name: string;
  type: ReportType;
  cadence: ReportCadence;
  status: ReportStatus;
  network: string | null;
  recipients: ReportRecipient[];
  lastRunAt: string | null;
  nextRunAt: string | null;
  config: Record<string, unknown>;
  lastSentAt: string | null;
  lastDeliveryStatus: 'sent' | 'failed' | 'skipped' | null;
  lastDeliveryError: string | null;
  lastDeliveryAt: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

interface State {
  reports: ReportRow[];
  isLoading: boolean;
}

export interface CreateReportInput {
  name: string;
  type: ReportType;
  cadence: ReportCadence;
  status?: ReportStatus | undefined;
  network?: string | null | undefined;
  recipients?: ReportRecipient[] | undefined;
  nextRunAt?: string | null | undefined;
  config?: Record<string, unknown> | undefined;
}

export interface UpdateReportInput {
  name?: string | undefined;
  type?: ReportType | undefined;
  cadence?: ReportCadence | undefined;
  status?: ReportStatus | undefined;
  network?: string | null | undefined;
  recipients?: ReportRecipient[] | undefined;
  lastRunAt?: string | null | undefined;
  nextRunAt?: string | null | undefined;
  config?: Record<string, unknown> | undefined;
  lastSentAt?: string | null | undefined;
}

export interface UseReportsResult extends State {
  createReport: (input: CreateReportInput) => Promise<ReportRow | null>;
  updateReport: (id: string, patch: UpdateReportInput) => Promise<void>;
  deleteReport: (id: string) => Promise<void>;
  duplicateReport: (id: string) => Promise<ReportRow | null>;
  refetch: () => void;
}

const cache = createHookCache<State>();
const reportsInFlight = new Map<string, Promise<State>>();

const TYPE_VALUES: ReadonlyArray<ReportType> = ['scheduled', 'one-off'];
const CADENCE_VALUES: ReadonlyArray<ReportCadence> = [
  'weekly',
  'monthly',
  'quarterly',
  'one-off',
];
const STATUS_VALUES: ReadonlyArray<ReportStatus> = [
  'active',
  'paused',
  'generated',
  'draft',
];

function asType(v: unknown): ReportType {
  return TYPE_VALUES.includes(v as ReportType) ? (v as ReportType) : 'scheduled';
}
function asCadence(v: unknown): ReportCadence {
  return CADENCE_VALUES.includes(v as ReportCadence)
    ? (v as ReportCadence)
    : 'monthly';
}
function asStatus(v: unknown): ReportStatus {
  return STATUS_VALUES.includes(v as ReportStatus)
    ? (v as ReportStatus)
    : 'draft';
}

function asRecipients(v: unknown): ReportRecipient[] {
  if (!Array.isArray(v)) return [];
  const out: ReportRecipient[] = [];
  for (const entry of v) {
    if (entry && typeof entry === 'object' && typeof (entry as { email?: unknown | undefined }).email === 'string') {
      const name = (entry as { name?: unknown | undefined }).name;
      out.push({
        email: (entry as { email: string }).email,
        ...(typeof name === 'string' ? { name } : {}),
      });
    }
  }
  return out;
}

// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape is broad
function mapRow(row: any, delivery?: ReportDeliveryState | undefined): ReportRow {
  return {
    id: String(row.id),
    name: String(row.name ?? ''),
    type: asType(row.type),
    cadence: asCadence(row.cadence),
    status: asStatus(row.status),
    network: typeof row.network === 'string' ? row.network : null,
    recipients: asRecipients(row.recipients),
    lastRunAt: typeof row.last_run_at === 'string' ? row.last_run_at : null,
    nextRunAt: typeof row.next_run_at === 'string' ? row.next_run_at : null,
    config: row.config && typeof row.config === 'object' && !Array.isArray(row.config) ? row.config : {},
    lastSentAt: typeof row.last_sent_at === 'string' ? row.last_sent_at : null,
    lastDeliveryStatus: delivery?.status ?? null,
    lastDeliveryError: delivery?.error ?? null,
    lastDeliveryAt: delivery?.sentAt ?? null,
    createdAt: typeof row.created_at === 'string' ? row.created_at : null,
    updatedAt: typeof row.updated_at === 'string' ? row.updated_at : null,
  };
}

const SELECT_COLUMNS =
  'id, name, type, cadence, status, network, recipients, last_run_at, next_run_at, config, last_sent_at, created_at, updated_at';

interface ReportDeliveryState {
  status: 'sent' | 'failed' | 'skipped';
  error: string | null;
  sentAt: string | null;
}

async function fetchReportsForUser(userId: string): Promise<State> {
  const existing = reportsInFlight.get(userId);
  if (existing) return existing;

  const request = (async () => {
    const { data, error } = await supabase
      .from('reports')
      .select(SELECT_COLUMNS)
      .eq('user_id', userId)
      .order('created_at', { ascending: false })
      .limit(200);

    if (error) throw error;
    const deliveryByReportId = await fetchLatestDeliveryLogs(
      (data ?? []).map((row) => String(row.id)).filter(Boolean),
    );
    const next: State = {
      reports: (data ?? []).map((row) => mapRow(row, deliveryByReportId.get(String(row.id)))),
      isLoading: false,
    };
    cache.set(userId, next);
    return next;
  })().finally(() => {
    if (reportsInFlight.get(userId) === request) {
      reportsInFlight.delete(userId);
    }
  });

  reportsInFlight.set(userId, request);
  return request;
}

async function fetchLatestDeliveryLogs(reportIds: string[]): Promise<Map<string, ReportDeliveryState>> {
  const latest = new Map<string, ReportDeliveryState>();
  if (reportIds.length === 0) return latest;
  const { data, error } = await supabase
    .from('report_send_log')
    .select('report_id, status, error, sent_at')
    .in('report_id', reportIds)
    .order('sent_at', { ascending: false })
    .limit(Math.min(Math.max(reportIds.length * 3, 20), 1000));
  if (error) return latest;
  for (const row of data ?? []) {
    const reportId = typeof row.report_id === 'string' ? row.report_id : String(row.report_id ?? '');
    if (!reportId || latest.has(reportId)) continue;
    const status = row.status === 'sent' || row.status === 'failed' || row.status === 'skipped' ? row.status : null;
    if (!status) continue;
    latest.set(reportId, {
      status,
      error: typeof row.error === 'string' ? row.error : null,
      sentAt: typeof row.sent_at === 'string' ? row.sent_at : null,
    });
  }
  return latest;
}

export function useReports(): UseReportsResult {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const [state, setState] = useState<State>(() => {
    const cached = cache.get(userKey);
    if (cached) return { ...cached, isLoading: false };
    return { reports: [], isLoading: true };
  });
  const [_nonce, setNonce] = useState(0);
  const forceRefetchRef = useRef(false);
  const refetch = useCallback(() => {
    forceRefetchRef.current = true;
    setNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!authUser) {
      // Stay loading while auth hydrates — empty-state flash otherwise.
      return;
    }

    const cached = cache.get(userKey);
    if (cached) setState({ ...cached, isLoading: false });

    const shouldForceRefetch = forceRefetchRef.current;
    forceRefetchRef.current = false;

    // Skip refetch if cached payload is fresh (<30s old).
    if (!shouldForceRefetch && cache.isFresh(userKey)) return;

    (async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user || cancelled) return;

      let next: State;
      try {
        next = await fetchReportsForUser(user.id);
      } catch {
        if (!cancelled) setState((s) => ({ ...s, isLoading: false }));
        return;
      }

      if (cancelled) return;
      setState(next);
    })();

    return () => {
      cancelled = true;
    };
  }, [userKey, authUser]);

  const createReport = useCallback<UseReportsResult['createReport']>(
    async (input) => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return null;
      const { data, error } = await supabase
        .from('reports')
        .insert({
          user_id: user.id,
          name: input.name,
          type: input.type,
          cadence: input.cadence,
          status: input.status ?? 'draft',
          network: input.network ?? null,
          recipients: (input.recipients ?? []) as never,
          next_run_at: input.nextRunAt ?? null,
          config: (input.config ?? {}) as never,
        })
        .select(SELECT_COLUMNS)
        .single();
      if (error || !data) return null;
      reportsInFlight.delete(user.id);
      const row = mapRow(data);
      setState((s) => {
        const next: State = { ...s, reports: [row, ...s.reports] };
        cache.set(userKey, next);
        return next;
      });
      return row;
    },
    [userKey],
  );

  const updateReport = useCallback<UseReportsResult['updateReport']>(
    async (id, patch) => {
      let previous: ReportRow | null = null;
      setState((s) => {
        previous = s.reports.find((r) => r.id === id) ?? null;
        const next: State = {
          ...s,
          reports: s.reports.map((r) =>
            r.id === id
              ? {
                  ...r,
                  ...(patch.name !== undefined ? { name: patch.name } : {}),
                  ...(patch.type !== undefined ? { type: patch.type } : {}),
                  ...(patch.cadence !== undefined ? { cadence: patch.cadence } : {}),
                  ...(patch.status !== undefined ? { status: patch.status } : {}),
                  ...(patch.network !== undefined ? { network: patch.network } : {}),
                  ...(patch.recipients !== undefined ? { recipients: patch.recipients } : {}),
                  ...(patch.lastRunAt !== undefined ? { lastRunAt: patch.lastRunAt } : {}),
                  ...(patch.nextRunAt !== undefined ? { nextRunAt: patch.nextRunAt } : {}),
                  ...(patch.config !== undefined ? { config: patch.config } : {}),
                  ...(patch.lastSentAt !== undefined ? { lastSentAt: patch.lastSentAt } : {}),
                }
              : r,
          ),
        };
        cache.set(userKey, next);
        return next;
      });
      const row: Record<string, unknown> = {};
      if (patch.name !== undefined) row.name = patch.name;
      if (patch.type !== undefined) row.type = patch.type;
      if (patch.cadence !== undefined) row.cadence = patch.cadence;
      if (patch.status !== undefined) row.status = patch.status;
      if (patch.network !== undefined) row.network = patch.network;
      if (patch.recipients !== undefined) row.recipients = patch.recipients;
      if (patch.lastRunAt !== undefined) row.last_run_at = patch.lastRunAt;
      if (patch.nextRunAt !== undefined) row.next_run_at = patch.nextRunAt;
      if (patch.config !== undefined) row.config = patch.config;
      if (patch.lastSentAt !== undefined) row.last_sent_at = patch.lastSentAt;
      if (Object.keys(row).length === 0) return;
      row.updated_at = new Date().toISOString();
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        if (previous) {
          const rollback = previous;
          setState((s) => {
            const next: State = {
              ...s,
              reports: s.reports.map((r) => (r.id === id ? rollback : r)),
            };
            cache.set(userKey, next);
            return next;
          });
        }
        return;
      }
      const { error } = await supabase
        .from('reports')
        .update(row)
        .eq('id', id)
        .eq('user_id', user.id);
      reportsInFlight.delete(user.id);
      if (error && previous) {
        const rollback = previous;
        setState((s) => {
          const next: State = {
            ...s,
            reports: s.reports.map((r) => (r.id === id ? rollback : r)),
          };
          cache.set(userKey, next);
          return next;
        });
      }
    },
    [userKey],
  );

  const deleteReport = useCallback<UseReportsResult['deleteReport']>(
    async (id) => {
      let previous: ReportRow | null = null;
      setState((s) => {
        previous = s.reports.find((r) => r.id === id) ?? null;
        const next: State = { ...s, reports: s.reports.filter((r) => r.id !== id) };
        cache.set(userKey, next);
        return next;
      });
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        if (previous) {
          setState((s) => {
            // biome-ignore lint/style/noNonNullAssertion: previous is guarded by outer if(previous) check; TypeScript cannot narrow through setState closure
            const next: State = { ...s, reports: [previous!, ...s.reports] };
            cache.set(userKey, next);
            return next;
          });
        }
        return;
      }
      const { error } = await supabase.from('reports').delete().eq('id', id).eq('user_id', user.id);
      reportsInFlight.delete(user.id);
      if (error && previous) {
        setState((s) => {
          // biome-ignore lint/style/noNonNullAssertion: previous is guarded by outer if(previous) check; TypeScript cannot narrow through setState closure
          const next: State = { ...s, reports: [previous!, ...s.reports] };
          cache.set(userKey, next);
          return next;
        });
      }
    },
    [userKey],
  );

  const duplicateReport = useCallback<UseReportsResult['duplicateReport']>(
    async (id) => {
      const source = state.reports.find((r) => r.id === id);
      if (!source) return null;
      return createReport({
        name: `${source.name} (copy)`,
        type: source.type,
        cadence: source.cadence,
        status: 'draft',
        network: source.network,
        recipients: source.recipients,
      });
    },
    [state.reports, createReport],
  );

  return {
    ...state,
    createReport,
    updateReport,
    deleteReport,
    duplicateReport,
    refetch,
  };
}
