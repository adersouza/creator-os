// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Autopilot service — reads the live auto-poster operational tables that back
 * the `/autopilot` page.
 *
 * Live:
 *   - fetchJobs() → cron_runs grouped by job_name, last 24h
 *   - fetchRateLimits() → Threads + Instagram rate-limit tables, sorted by % used
 *   - fetchQueueHealth() → scheduled posts rolled up by account group
 *   - fetchFailures() → failed/publish_failed posts from the last 30d
 */

import { classifyFailureReason, normalizeFailureReason } from '@/lib/autopilotFailureClassify';
import { z } from 'zod';
import { ApiHttpError, apiFetch } from '@/lib/apiFetch';
import { supabase } from './supabase';
import type { Json } from '@/types/supabase';

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

export type JobStatus = 'running' | 'idle' | 'paused' | 'failed';

export interface JobSummary {
  id: string;
  name: string;
  description: string;
  schedule: string;
  lastRunRelative: string;
  nextRunRelative: string;
  nextRunMs: number | null;
  successRate24h: number;
  runs24h: number;
  status: JobStatus;
  spark: number[];
}

export interface RateLimitRow {
  id: string;
  handle: string;
  network: string;
  platform: 'threads' | 'instagram';
  used: number;
  cap: number;
  resetRelative: string;
}

export interface QueueHealthRow {
  network: string;
  networkLabel: string;
  days: number;
  scheduledCount: number;
  accountCount: number;
}

export interface FailureRow {
  id: string;
  accountId: string | null;
  failedAt: string | null;
  whenRelative: string;
  handle: string;
  avatarUrl: string | null;
  network: string;
  platform: 'threads' | 'instagram';
  errorType: string;
  failureClass: string;
  detail: string;
  retryCount: number;
}

export type AutopilotRunType = 'queue_fill' | 'publish' | 'sync' | 'reply_chain' | 'auto_unpost';
export type AutopilotRunStatus = 'success' | 'failed' | 'partial' | 'in_progress';
export type AutopilotStepStatus = 'success' | 'failed' | 'skipped';

export interface AutopilotReplayRun {
  id: string;
  user_id: string;
  run_type: AutopilotRunType;
  account_id: string | null;
  post_id: string | null;
  status: AutopilotRunStatus;
  trigger: string | null;
  parent_run_id: string | null;
  started_at: string;
  finished_at: string | null;
  metadata: Json | null;
}

export interface AutopilotReplayStep {
  id: string;
  run_id: string;
  step_index: number;
  step_name: string;
  status: AutopilotStepStatus;
  inputs: Json | null;
  outputs: Json | null;
  error_message: string | null;
  duration_ms: number | null;
  started_at: string;
  finished_at: string | null;
}

const replayStepResponseSchema = z.object({
  success: z.boolean().optional(),
  runId: z.string().nullable(),
  status: z.string(),
});

function apiHttpErrorMessage(error: ApiHttpError, fallback: string): string {
  try {
    const body = JSON.parse(error.body) as { error?: unknown | undefined };
    if (typeof body.error === 'string') return body.error;
  } catch {
    /* keep fallback */
  }
  return fallback;
}

/* ------------------------------------------------------------------ */
/* Job metadata — which crons Autopilot surfaces, their human schedule,
 * and a short description. Keyed on the actual job_name written by
 * trackCronRun() in the backend cronUtils.                           */
/* ------------------------------------------------------------------ */

interface JobMeta {
  name: string;
  description: string;
  schedule: string;
  intervalMinutes: number | null;
}

const AUTOPILOT_JOBS: JobMeta[] = [
  {
    name: 'publish-worker',
    description: 'Drains the scheduled-post queue — claims rows, calls platform APIs, records receipts.',
    schedule: 'every 5 minutes',
    intervalMinutes: 5,
  },
  {
    name: 'reconcile-daily',
    description: 'Daily orphan-detection sweep — reconciles scheduled vs. published posts on Threads + Instagram.',
    schedule: 'daily 03:30 UTC',
    intervalMinutes: null,
  },
  {
    name: 'dawn-planner',
    description: 'Plans the day\'s queue from the content library when draft stock drops below 4 days.',
    schedule: 'daily at dawn',
    intervalMinutes: null,
  },
  {
    name: 'autoposter-watchdog',
    description: 'Polls token health, refreshes expiring tokens, surfaces publish failures to the activity feed.',
    schedule: 'every 10 minutes',
    intervalMinutes: 10,
  },
  {
    name: 'scheduler',
    description: 'Builds the next 24h of posting slots across networks based on per-account timing windows.',
    schedule: 'every 30 minutes',
    intervalMinutes: 30,
  },
];

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function relativePast(date: Date): string {
  const secs = Math.max(0, (Date.now() - date.getTime()) / 1000);
  if (secs < 60) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function relativeFuture(minutes: number): string {
  if (minutes < 1) return 'any second';
  if (minutes < 60) return `in ${minutes}m`;
  const hrs = Math.floor(minutes / 60);
  if (hrs < 24) return `in ${hrs}h`;
  return `in ${Math.floor(hrs / 24)}d`;
}

function nextRunFromSchedule(meta: JobMeta, lastRunAt: Date | null): string {
  if (meta.intervalMinutes != null && lastRunAt) {
    const nextAt = lastRunAt.getTime() + meta.intervalMinutes * 60_000;
    const minsFromNow = Math.round((nextAt - Date.now()) / 60_000);
    if (minsFromNow <= 0) return 'any second';
    return relativeFuture(minsFromNow);
  }
  return meta.schedule;
}

function nextRunMsFromSchedule(meta: JobMeta, lastRunAt: Date | null): number | null {
  if (meta.intervalMinutes != null && lastRunAt) {
    return lastRunAt.getTime() + meta.intervalMinutes * 60_000;
  }
  return null;
}

async function requireAuthedUserId(): Promise<string> {
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    throw new Error('Not authenticated');
  }
  return user.id;
}

/* ------------------------------------------------------------------ */
/* fetchJobs                                                          */
/* ------------------------------------------------------------------ */

export async function fetchJobs(): Promise<JobSummary[]> {
  const sinceIso = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const names = AUTOPILOT_JOBS.map((j) => j.name);

  const { data, error } = await supabase
    .from('cron_runs')
    .select('id, job_name, status, started_at, finished_at, items_processed, error')
    .in('job_name', names)
    .gte('started_at', sinceIso)
    .order('started_at', { ascending: false });

  if (error) throw error;

  const rowsByJob = new Map<string, typeof data>();
  for (const row of data ?? []) {
    if (!rowsByJob.has(row.job_name)) rowsByJob.set(row.job_name, []);
    rowsByJob.get(row.job_name)?.push(row);
  }

  return AUTOPILOT_JOBS.map((meta) => {
    const rows = rowsByJob.get(meta.name) ?? [];
    const runs24h = rows.length;
    const failures = rows.filter((r) => r.status === 'failed').length;
    const successRate24h = runs24h === 0 ? 100 : ((runs24h - failures) / runs24h) * 100;
    const last = rows[0];
    const lastRunAt = last?.started_at ? new Date(last.started_at) : null;

    let status: JobStatus = 'idle';
    if (last?.status === 'running' && !last.finished_at) status = 'running';
    else if (last?.status === 'failed') status = 'failed';
    else if (last?.status === 'succeeded' || last?.status === 'ok') status = 'idle';

    const spark = buildSparkline(rows.slice(0, 24).reverse());

    return {
      id: meta.name,
      name: meta.name,
      description: meta.description,
      schedule: meta.schedule,
      lastRunRelative: lastRunAt ? relativePast(lastRunAt) : 'never',
      nextRunRelative: nextRunFromSchedule(meta, lastRunAt),
      nextRunMs: nextRunMsFromSchedule(meta, lastRunAt),
      successRate24h,
      runs24h,
      status,
      spark,
    };
  });
}

function buildSparkline(
  rows: Array<{ status: string; started_at: string }>,
): number[] {
  if (rows.length === 0) return new Array(24).fill(100);
  return rows.map((r) => (r.status === 'failed' ? 0 : 100));
}

/* ------------------------------------------------------------------ */
/* fetchRateLimits                                                    */
/* ------------------------------------------------------------------ */

const THREADS_DAILY_CAP = 250;
const INSTAGRAM_DAILY_CAP = 100;
const UNASSIGNED_GROUP_KEY = '__all_accounts__';
const UNASSIGNED_GROUP_LABEL = 'All accounts';

export async function fetchRateLimits(limit = 24): Promise<RateLimitRow[]> {
  const userId = await requireAuthedUserId();
  const [threadAccountsResp, instagramAccountsResp] = await Promise.all([
    supabase
      .from('accounts')
      .select('id')
      .eq('user_id', userId)
      .eq('is_active', true)
      .eq('is_retired', false),
    supabase
      .from('instagram_accounts')
      .select('id')
      .eq('user_id', userId)
      .eq('is_active', true),
  ]);

  if (threadAccountsResp.error) throw threadAccountsResp.error;
  if (instagramAccountsResp.error) throw instagramAccountsResp.error;

  const threadAccountIds = (threadAccountsResp.data ?? []).map((row) => row.id);
  const instagramAccountIds = (instagramAccountsResp.data ?? []).map((row) => row.id);
  if (threadAccountIds.length === 0 && instagramAccountIds.length === 0) return [];

  const [threadsResp, instagramResp] = await Promise.all([
    threadAccountIds.length
      ? supabase
          .from('rate_limit_tracking')
          .select(
            `
              id,
              account_id,
              posts_today,
              day_window_start,
              accounts (
                username,
                group_id
              )
            `,
          )
          .in('account_id', threadAccountIds)
      : Promise.resolve({ data: [], error: null }),
    instagramAccountIds.length
      ? supabase
          .from('ig_rate_limit_tracking')
          .select(
            `
              id,
              account_id,
              daily_count,
              daily_reset_at,
              instagram_accounts (
                username,
                group_id
              )
            `,
          )
          .in('account_id', instagramAccountIds)
      : Promise.resolve({ data: [], error: null }),
  ]);

  if (threadsResp.error) throw threadsResp.error;
  if (instagramResp.error) throw instagramResp.error;

  const rows: RateLimitRow[] = [
    ...(threadsResp.data ?? []).map((row) => {
      const acct = (row.accounts ?? {}) as { username?: string | undefined; group_id?: string | null | undefined };
      const used = row.posts_today ?? 0;
      const windowStart = row.day_window_start ? new Date(row.day_window_start) : null;
      const resetRelative = windowStart
        ? relativeFuture(
            Math.max(0, Math.round((24 * 60 - (Date.now() - windowStart.getTime()) / 60_000))),
          )
        : '—';

      return {
        id: row.id,
        handle: acct.username ? `@${acct.username}` : '—',
        network: acct.group_id ?? UNASSIGNED_GROUP_KEY,
        platform: 'threads' as const,
        used,
        cap: THREADS_DAILY_CAP,
        resetRelative: resetRelative.replace(/^in /, ''),
      };
    }),
    ...(instagramResp.data ?? []).map((row) => {
      const acct = (row.instagram_accounts ?? {}) as {
        username?: string | undefined;
        group_id?: string | null | undefined;
      };
      const used = row.daily_count ?? 0;
      const resetAt = row.daily_reset_at ? new Date(row.daily_reset_at) : null;
      const resetRelative = resetAt
        ? relativeFuture(Math.max(0, Math.round((resetAt.getTime() - Date.now()) / 60_000)))
        : '—';

      return {
        id: row.id,
        handle: acct.username ? `@${acct.username}` : '—',
        network: acct.group_id ?? UNASSIGNED_GROUP_KEY,
        platform: 'instagram' as const,
        used,
        cap: INSTAGRAM_DAILY_CAP,
        resetRelative: resetRelative.replace(/^in /, ''),
      };
    }),
  ];

  return rows
    .sort((a, b) => b.used / b.cap - a.used / a.cap)
    .slice(0, limit);
}

/* ------------------------------------------------------------------ */
/* fetchQueueHealth                                                   */
/* ------------------------------------------------------------------ */

const DEFAULT_POSTS_PER_ACCOUNT_PER_DAY = 1;
const QUEUE_LOOKAHEAD_DAYS = 30;

export async function fetchQueueHealth(): Promise<QueueHealthRow[]> {
  const userId = await requireAuthedUserId();
  const now = new Date();
  const lookaheadIso = new Date(
    now.getTime() + QUEUE_LOOKAHEAD_DAYS * 24 * 60 * 60 * 1000,
  ).toISOString();

  const [postsResp, accountsResp, instagramAccountsResp, groupsResp] = await Promise.all([
    supabase
      .from('posts')
      .select('id, account_id, instagram_account_id, platform, scheduled_for')
      .eq('user_id', userId)
      .eq('status', 'scheduled')
      .gte('scheduled_for', now.toISOString())
      .lt('scheduled_for', lookaheadIso),
    supabase
      .from('accounts')
      .select('id, group_id')
      .eq('user_id', userId)
      .eq('is_active', true)
      .eq('is_retired', false),
    supabase
      .from('instagram_accounts')
      .select('id, group_id')
      .eq('user_id', userId)
      .eq('is_active', true),
    supabase
      .from('account_groups')
      .select('id, name')
      .eq('user_id', userId),
  ]);

  if (postsResp.error) throw postsResp.error;
  if (accountsResp.error) throw accountsResp.error;
  if (instagramAccountsResp.error) throw instagramAccountsResp.error;

  const threadAccounts = accountsResp.data ?? [];
  const instagramAccounts = instagramAccountsResp.data ?? [];
  const accountToGroup = new Map<string, string | null>();
  const groupAccountCount = new Map<string, number>();
  for (const a of threadAccounts) {
    const groupKey = a.group_id ?? UNASSIGNED_GROUP_KEY;
    accountToGroup.set(`threads:${a.id}`, groupKey);
    groupAccountCount.set(groupKey, (groupAccountCount.get(groupKey) ?? 0) + 1);
  }
  for (const a of instagramAccounts) {
    const groupKey = a.group_id ?? UNASSIGNED_GROUP_KEY;
    accountToGroup.set(`instagram:${a.id}`, groupKey);
    groupAccountCount.set(groupKey, (groupAccountCount.get(groupKey) ?? 0) + 1);
  }

  const groupScheduled = new Map<string, number>();
  for (const p of postsResp.data ?? []) {
    const accountKey =
      p.platform === 'instagram' || p.instagram_account_id
        ? `instagram:${p.instagram_account_id ?? ''}`
        : `threads:${p.account_id ?? ''}`;
    const groupId = accountToGroup.get(accountKey);
    if (!groupId) continue;
    groupScheduled.set(groupId, (groupScheduled.get(groupId) ?? 0) + 1);
  }

  // Group label lookup — account_groups may not exist in every tenant.
  // Swallow errors and fall back to the group_id itself.
  const groupLabels = new Map<string, string>();
  groupLabels.set(UNASSIGNED_GROUP_KEY, UNASSIGNED_GROUP_LABEL);
  if (!groupsResp.error) {
    for (const g of (groupsResp.data ?? []) as Array<{ id: string; name: string | null }>) {
      if (g.name) groupLabels.set(g.id, g.name);
    }
  }

  const allGroupIds = new Set<string>([
    ...groupAccountCount.keys(),
    ...groupScheduled.keys(),
  ]);

  return Array.from(allGroupIds)
    .map<QueueHealthRow>((groupId) => {
      const accountCount = groupAccountCount.get(groupId) ?? 0;
      const scheduledCount = groupScheduled.get(groupId) ?? 0;
      const target = Math.max(1, accountCount) * DEFAULT_POSTS_PER_ACCOUNT_PER_DAY;
      const days = scheduledCount / target;
      return {
        network: groupId,
        networkLabel: groupLabels.get(groupId) ?? groupId,
        days,
        scheduledCount,
        accountCount,
      };
    })
    .sort((a, b) => a.days - b.days);
}

/* ------------------------------------------------------------------ */
/* fetchFailures                                                      */
/* ------------------------------------------------------------------ */

const FAILURE_STATUSES = ['failed', 'publish_failed'];
const FAILURE_LOOKBACK_DAYS = 30;

export async function fetchFailures(limit = 500): Promise<FailureRow[]> {
  const userId = await requireAuthedUserId();
  const sinceIso = new Date(Date.now() - FAILURE_LOOKBACK_DAYS * 24 * 60 * 60 * 1000).toISOString();
  const { data, error } = await supabase
    .from('posts')
    .select(
      `
        id,
        status,
        error_message,
        scheduled_for,
        updated_at,
        retry_count,
        platform,
        account_id,
        instagram_account_id
      `,
    )
    .eq('user_id', userId)
    .in('status', FAILURE_STATUSES)
    .gte('updated_at', sinceIso)
    .order('updated_at', { ascending: false, nullsFirst: false })
    .limit(limit);

  if (error) throw error;

  const rows = data ?? [];
  const threadIds = rows
    .filter((row) => row.platform !== 'instagram' && row.account_id)
    .map((row) => row.account_id)
    .filter((id): id is string => !!id);
  const instagramIds = rows
    .filter((row) => row.platform === 'instagram' || row.instagram_account_id)
    .map((row) => row.instagram_account_id)
    .filter((id): id is string => !!id);

  const [threadsResp, instagramResp] = await Promise.all([
    threadIds.length
      ? supabase
          .from('accounts')
          .select('id, username, group_id, avatar_url')
          .in('id', threadIds)
          .eq('user_id', userId)
      : Promise.resolve({ data: [], error: null }),
    instagramIds.length
      ? supabase
          .from('instagram_accounts')
          .select('id, username, group_id, avatar_url')
          .in('id', instagramIds)
          .eq('user_id', userId)
      : Promise.resolve({ data: [], error: null }),
  ]);

  if (threadsResp.error) throw threadsResp.error;
  if (instagramResp.error) throw instagramResp.error;

  const threadsById = new Map((threadsResp.data ?? []).map((row) => [row.id, row]));
  const instagramById = new Map((instagramResp.data ?? []).map((row) => [row.id, row]));

  return rows.map((row) => {
    const { errorType, detail } = parseError(row.error_message ?? null);
    const normalizedReason = normalizeFailureReason(row.error_message ?? detail);
    const platform: 'threads' | 'instagram' =
      row.platform === 'instagram' || row.instagram_account_id
        ? 'instagram'
        : 'threads';
    const account =
      platform === 'instagram'
        ? (row.instagram_account_id ? instagramById.get(row.instagram_account_id) : undefined)
        : (row.account_id ? threadsById.get(row.account_id) : undefined);
    const when = row.updated_at ?? row.scheduled_for ?? null;
    return {
      id: row.id,
      accountId:
        platform === 'instagram'
          ? (row.instagram_account_id ?? null)
          : (row.account_id ?? null),
      failedAt: when,
      whenRelative: when ? relativePast(new Date(when)) : '—',
      handle: account?.username ? `@${account.username}` : '—',
      avatarUrl: account?.avatar_url ?? null,
      network: account?.group_id ?? UNASSIGNED_GROUP_KEY,
      platform,
      errorType,
      failureClass: classifyFailureReason(normalizedReason),
      detail: normalizedReason || detail,
      retryCount: row.retry_count ?? 0,
    };
  });
}

/* ------------------------------------------------------------------ */
/* fetchReplayRuns / fetchReplaySteps                                  */
/* ------------------------------------------------------------------ */

export async function fetchReplayRuns(
  days = 7,
  limit = 80,
): Promise<AutopilotReplayRun[]> {
  await requireAuthedUserId();
  const sinceIso = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
  // biome-ignore lint/suspicious/noExplicitAny: Phase 5 tables are not in generated Supabase types yet
  const { data, error } = await (supabase as any)
    .from('autopilot_runs')
    .select(
      'id, user_id, run_type, account_id, post_id, status, trigger, parent_run_id, started_at, finished_at, metadata',
    )
    .gte('started_at', sinceIso)
    .order('started_at', { ascending: false })
    .limit(limit);

  if (error) throw error;
  return (data ?? []) as AutopilotReplayRun[];
}

export async function fetchReplaySteps(runId: string): Promise<AutopilotReplayStep[]> {
  await requireAuthedUserId();
  // biome-ignore lint/suspicious/noExplicitAny: Phase 5 tables are not in generated Supabase types yet
  const { data, error } = await (supabase as any)
    .from('autopilot_run_steps')
    .select(
      'id, run_id, step_index, step_name, status, inputs, outputs, error_message, duration_ms, started_at, finished_at',
    )
    .eq('run_id', runId)
    .order('step_index', { ascending: true });

  if (error) throw error;
  return (data ?? []) as AutopilotReplayStep[];
}

export async function replayAutopilotStep(
  runId: string,
  stepId: string,
): Promise<{ runId: string | null; status: string }> {
  try {
    const body = await apiFetch('/api/autopilot-replay', replayStepResponseSchema, {
      method: 'POST',
      headers: {
        'Idempotency-Key': `autopilot-replay:${runId}:${stepId}`,
      },
      json: { runId, stepId },
    });
    return { runId: body.runId, status: body.status };
  } catch (error) {
    if (error instanceof ApiHttpError) {
      throw new Error(
        apiHttpErrorMessage(error, `Replay failed (${error.status})`),
      );
    }
    throw error;
  }
}

/** Pulls the first UPPER_CASE token out of the error string (e.g.
 *  "TOKEN_EXPIRED: ...") and returns it as errorType with the rest as
 *  detail. Falls back to a generic label. */
function parseError(message: string | null): { errorType: string; detail: string } {
  if (!message) return { errorType: 'UNKNOWN', detail: 'No error detail recorded.' };
  const match = message.match(/^([A-Z][A-Z0-9_]{2,})[:\s-]\s*(.*)$/s);
  if (match) {
    return {
      errorType: match[1]!.slice(0, 32),
      detail: match[2]!.trim() || message,
    };
  }
  return { errorType: 'PUBLISH_FAILED', detail: message };
}

/* ------------------------------------------------------------------ */
/* retryFailedPost(s) — flips failed posts back to scheduled so the
 * existing scheduled-post-publish cron picks them up on next run.
 * RLS enforces ownership; the status filter prevents re-queuing
 * already-published rows if something races.                         */
/* ------------------------------------------------------------------ */

const RETRY_DELAY_SECONDS = 60;

export async function retryFailedPost(postId: string): Promise<void> {
  const when = new Date(Date.now() + RETRY_DELAY_SECONDS * 1000).toISOString();
  const { error } = await supabase
    .from('posts')
    .update({
      status: 'scheduled',
      scheduled_for: when,
      retry_count: 0,
      error_message: null,
    })
    .eq('id', postId)
    .in('status', FAILURE_STATUSES);

  if (error) throw error;
}

export async function retryFailedPosts(postIds: string[]): Promise<{ retried: number }> {
  if (postIds.length === 0) return { retried: 0 };
  const when = new Date(Date.now() + RETRY_DELAY_SECONDS * 1000).toISOString();
  const { data, error } = await supabase
    .from('posts')
    .update({
      status: 'scheduled',
      scheduled_for: when,
      retry_count: 0,
      error_message: null,
    })
    .in('id', postIds)
    .in('status', FAILURE_STATUSES)
    .select('id');

  if (error) throw error;
  return { retried: (data ?? []).length };
}
