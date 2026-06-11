/**
 * Shared EQS (Engagement Quality Score) helpers.
 *
 * EQS = weighted engagement per reach, capped at 100.
 * Weights: sends×5 + saves×3 + comments×2 + likes×1.
 * A post doing ~5% weighted engagement → 100.
 */

export interface EqsPostRow {
  platform: string | null;
  likes_count?: number | null | undefined;
  shares_count?: number | null | undefined;
  replies_count?: number | null | undefined;
  views_count?: number | null | undefined;
  ig_saved?: number | null | undefined;
  ig_shares?: number | null | undefined;
  ig_comment_count?: number | null | undefined;
  ig_reach?: number | null | undefined;
}

export interface PostSignals {
  sends: number;
  saves: number;
  comments: number;
  likes: number;
  reach: number;
}

/** Minimum reach to count a post toward EQS (avoid divide-by-zero amplification on 0-view posts). */
export const MIN_REACH_FOR_EQS = 50;

/**
 * Normalize a post to a platform-agnostic engagement shape.
 * - Threads: shares_count = reposts (treat as sends), no saves column, replies_count = comments.
 * - Instagram: ig_shares = sends, ig_saved = saves, ig_comment_count = comments, ig_reach preferred over views_count.
 */
export function signalsFor(row: EqsPostRow): PostSignals {
  if (row.platform === 'instagram') {
    return {
      sends: row.ig_shares ?? 0,
      saves: row.ig_saved ?? 0,
      comments: row.ig_comment_count ?? 0,
      likes: row.likes_count ?? 0,
      reach: row.ig_reach ?? row.views_count ?? 0,
    };
  }
  return {
    sends: row.shares_count ?? 0,
    saves: 0,
    comments: row.replies_count ?? 0,
    likes: row.likes_count ?? 0,
    reach: row.views_count ?? 0,
  };
}

export function eqsForSignals(signals: PostSignals[]): number {
  let weightedTotal = 0;
  let reachTotal = 0;
  for (const s of signals) {
    if (s.reach < MIN_REACH_FOR_EQS) continue;
    weightedTotal += s.sends * 5 + s.saves * 3 + s.comments * 2 + s.likes;
    reachTotal += s.reach;
  }
  if (reachTotal === 0) return 0;
  const ratio = weightedTotal / reachTotal;
  const scaled = (ratio / 0.05) * 100;
  return Math.max(0, Math.min(100, Math.round(scaled * 10) / 10));
}

export function toDateKey(iso: string): string {
  return iso.slice(0, 10);
}

export function fillDateRange(start: Date, end: Date): string[] {
  const days: string[] = [];
  const cursor = new Date(start);
  cursor.setUTCHours(0, 0, 0, 0);
  const endDay = new Date(end);
  endDay.setUTCHours(0, 0, 0, 0);
  while (cursor <= endDay) {
    days.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}
