// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { describe, expect, it } from 'vitest';
import type { FleetMetricsState } from '@/hooks/useFleetMetrics';
import { buildAccountAggregatesCsv, buildDailySeriesCsv } from './analyticsCsv';

// Minimal fleet payload factory — only fills the fields these CSV builders
// read. Widening the real FleetMetricsState type-by-type would couple the
// tests to every future metric.
function fleetState(patch: Partial<FleetMetricsState> = {}): FleetMetricsState {
  return {
    eqs: 0,
    eqsDelta: null,
    totalReach: 0,
    reachDeltaPct: null,
    sendsPlusSaves: 0,
    sendsPlusSavesDeltaPct: null,
    scheduleCompliance: null,
    scheduleComplianceDelta: null,
    followerGrowthPct: null,
    followerGrowthDeltaPct: null,
    series: [],
    accounts: [],
    postCount: 0,
    eqsQualifyingPostCount: 0,
    isLoading: false,
    hasError: false,
    ...patch,
  };
}

describe('buildAccountAggregatesCsv', () => {
  it('emits just the header row when there are no accounts', () => {
    const csv = buildAccountAggregatesCsv(fleetState());
    const lines = csv.trim().split('\n');
    expect(lines).toHaveLength(1);
    expect(lines[0]).toBe(
      'handle,platform,posts,eqs,reach,sends,saves,comments,likes,follower_growth_pct',
    );
  });

  it('formats numeric columns and growth pct', () => {
    const csv = buildAccountAggregatesCsv(
      fleetState({
        accounts: [
          {
            accountId: 'a1',
            platform: 'threads',
            username: 'aurora.core',
            groupId: null,
            eqs: 74.2189,
            reach: 12345,
            sends: 101,
            saves: 0,
            comments: 7,
            likes: 200,
            posts: 4,
            followerGrowthPct: 3.51,
            priorReach: 0,
            priorPosts: 0,
            reachDeltaPct: null,
          },
        ],
      }),
    );
    const [, row] = csv.trim().split('\n');
    expect(row).toBe('aurora.core,threads,4,74.22,12345,101,0,7,200,3.51');
  });

  it('leaves follower_growth_pct empty when null, never "null"', () => {
    const csv = buildAccountAggregatesCsv(
      fleetState({
        accounts: [
          {
            accountId: 'a1',
            platform: 'instagram',
            username: 'harbor',
            groupId: null,
            eqs: 0,
            reach: 0,
            sends: 0,
            saves: 0,
            comments: 0,
            likes: 0,
            posts: 0,
            followerGrowthPct: null,
            priorReach: 0,
            priorPosts: 0,
            reachDeltaPct: null,
          },
        ],
      }),
    );
    const [, row] = csv.trim().split('\n');
    // Trailing empty field — no "null", no "undefined".
    expect(row!.endsWith(',')).toBe(true);
    expect(row).not.toMatch(/null|undefined/);
  });

  it('quotes + escapes fields containing commas, quotes, or newlines', () => {
    const csv = buildAccountAggregatesCsv(
      fleetState({
        accounts: [
          {
            accountId: 'a1',
            platform: 'threads',
            // handle that would break naive CSV: contains a comma, a quote, and a newline
            username: 'weird,"name"\nline',
            groupId: null,
            eqs: 0,
            reach: 0,
            sends: 0,
            saves: 0,
            comments: 0,
            likes: 0,
            posts: 0,
            followerGrowthPct: null,
            priorReach: 0,
            priorPosts: 0,
            reachDeltaPct: null,
          },
        ],
      }),
    );
    // The escaped field should be wrapped in quotes with embedded quotes doubled.
    expect(csv).toContain('"weird,""name""\nline"');
  });

  it('emits an empty string for null username rather than "null"', () => {
    const csv = buildAccountAggregatesCsv(
      fleetState({
        accounts: [
          {
            accountId: 'a1',
            platform: 'threads',
            username: null,
            groupId: null,
            eqs: 0,
            reach: 0,
            sends: 0,
            saves: 0,
            comments: 0,
            likes: 0,
            posts: 0,
            followerGrowthPct: null,
            priorReach: 0,
            priorPosts: 0,
            reachDeltaPct: null,
          },
        ],
      }),
    );
    const [, row] = csv.trim().split('\n');
    expect(row!.startsWith(',threads,')).toBe(true);
  });
});

describe('buildDailySeriesCsv', () => {
  it('emits header-only CSV when the series is empty', () => {
    const csv = buildDailySeriesCsv(fleetState());
    expect(csv.trim()).toBe('date,eqs,reach');
  });

  it('formats each bucket with 2-decimal EQS + integer reach', () => {
    const csv = buildDailySeriesCsv(
      fleetState({
        series: [
          { date: '2026-04-15', eqs: 74.123, reach: 12_000 },
          { date: '2026-04-16', eqs: 0, reach: 0 },
        ],
      }),
    );
    const [header, first, second] = csv.trim().split('\n');
    expect(header).toBe('date,eqs,reach');
    expect(first).toBe('2026-04-15,74.12,12000');
    expect(second).toBe('2026-04-16,0.00,0');
  });
});
