import { describe, expect, it } from 'vitest';
import {
  bucketReelRetention,
  computeReelRetentionScore,
  summarizeFleetRetention,
} from './reelRetention';

describe('computeReelRetentionScore', () => {
  it('returns 0 when all inputs are null/zero', () => {
    expect(computeReelRetentionScore({ avgWatchMs: 0, skipRate: 0 })).toBe(0);
    expect(
      computeReelRetentionScore({ avgWatchMs: null, skipRate: null }),
    ).toBe(0);
  });

  it('scales with watch time against the 30s reference', () => {
    // 30s watch, 0% skip = max score 100.
    expect(
      computeReelRetentionScore({ avgWatchMs: 30_000, skipRate: 0 }),
    ).toBe(100);
    // 15s watch, 0% skip = ~50.
    expect(
      computeReelRetentionScore({ avgWatchMs: 15_000, skipRate: 0 }),
    ).toBe(50);
  });

  it('penalizes high skip rate even with decent watch time', () => {
    // 20s avg watch (from the few who stayed) but 80% swiped past in <3s.
    const score = computeReelRetentionScore({
      avgWatchMs: 20_000,
      skipRate: 0.8,
    });
    expect(score).toBeLessThan(20);
  });

  it('clamps skip rate to [0,1]', () => {
    // Hostile input: skipRate = 1.5 (impossible). Shouldn't produce negative.
    const score = computeReelRetentionScore({
      avgWatchMs: 30_000,
      skipRate: 1.5,
    });
    expect(score).toBe(0);
  });

  it('clamps the final score to 100', () => {
    const score = computeReelRetentionScore({
      avgWatchMs: 60_000,
      skipRate: 0,
    });
    expect(score).toBeLessThanOrEqual(100);
  });

  it('ignores NaN/Infinity skipRate defensively', () => {
    // Garbage skipRate → clamped to 0 (fail-open: keep scoring on watch time).
    // This is deliberate — we don't want one weird Meta response to
    // misclassify a Reel as sub-3s when avgWatchMs is clearly solid.
    expect(
      computeReelRetentionScore({
        avgWatchMs: 15_000,
        skipRate: Number.NaN,
      }),
    ).toBe(50);
    expect(
      computeReelRetentionScore({
        avgWatchMs: 15_000,
        skipRate: Number.POSITIVE_INFINITY,
      }),
    ).toBe(50);
  });
});

describe('bucketReelRetention', () => {
  it.each([
    [100, 'excellent'],
    [75, 'excellent'],
    [74, 'strong'],
    [55, 'strong'],
    [54, 'weak'],
    [30, 'weak'],
    [29, 'sub3'],
    [0, 'sub3'],
  ])('score %d → %s bucket', (score, bucket) => {
    expect(bucketReelRetention(score)).toBe(bucket);
  });
});

describe('summarizeFleetRetention', () => {
  it('returns zero summary when input is empty', () => {
    const s = summarizeFleetRetention([]);
    expect(s.sampledReels).toBe(0);
    expect(s.avgScore).toBe(0);
    expect(s.sub3Rate).toBe(0);
  });

  it('skips rows with no usable data from the fleet sample', () => {
    // Mix of real rows + zero rows + null rows. Only the real ones count.
    const s = summarizeFleetRetention([
      { avgWatchMs: 25_000, skipRate: 0.1 }, // real
      { avgWatchMs: 0, skipRate: 0 },        // skipped (no data)
      { avgWatchMs: null, skipRate: null },  // skipped
      { avgWatchMs: 10_000, skipRate: 0.5 }, // real
    ]);
    expect(s.sampledReels).toBe(2);
  });

  it('buckets each Reel correctly and aggregates sub3 rate', () => {
    const s = summarizeFleetRetention([
      { avgWatchMs: 28_000, skipRate: 0 },   // excellent
      { avgWatchMs: 20_000, skipRate: 0.1 }, // strong
      { avgWatchMs: 12_000, skipRate: 0.2 }, // weak
      { avgWatchMs: 5_000, skipRate: 0.6 },  // sub3
      { avgWatchMs: 3_000, skipRate: 0.8 },  // sub3
    ]);
    expect(s.sampledReels).toBe(5);
    expect(s.byBucket.excellent).toBe(1);
    expect(s.byBucket.strong).toBe(1);
    expect(s.byBucket.weak).toBe(1);
    expect(s.byBucket.sub3).toBe(2);
    expect(s.sub3Rate).toBeCloseTo(0.4);
  });
});
