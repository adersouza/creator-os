/**
 * Engagement Rate Calculation Utilities
 *
 * For dashboard-level ER, use the pre-computed value from getAnalyticsStats().
 * This utility is for post-level ER computation (e.g., sorting posts by ER).
 * Formula source of truth: api/_lib/metricCalculators.ts
 */

import type { PostPerformance } from '@/types/analytics';

export type ERTier = 'high' | 'medium' | 'low';

export interface ERBadgeConfig {
  tier: ERTier;
  label: string;
  bgColor: string;
  textColor: string;
  borderColor: string;
}

/**
 * Calculate engagement rate from post performance metrics (Threads).
 *
 * Weighted formula (matches backend metricCalculators.ts):
 *   (likes + replies×2 + reposts×1.5 + quotes + shares) / views × 100
 *
 * @param performance - Post performance metrics
 * @returns Engagement rate as percentage, or null if no valid divisor
 */
export const calculateEngagementRate = (performance: PostPerformance | undefined): number | null => {
  if (!performance?.views || performance.views === 0) return null;

  const { likes = 0, replies = 0, reposts = 0, quotes = 0, shares = 0 } = performance;
  const engagement = likes + replies * 2 + reposts * 1.5 + quotes + shares;
  return (engagement / performance.views) * 100;
};

/**
 * Calculate engagement rate for Instagram posts/account-level metrics.
 *
 * Weighted formula (matches backend metricCalculators.ts):
 *   (likes + comments×2 + saves×3 + shares) / reach × 100
 * Falls back to impressions if reach is 0.
 */
export const calculateInstagramEngagementRate = (metrics: {
  likes?: number | undefined;
  comments?: number | undefined;
  shares?: number | undefined;
  saved?: number | undefined;
  reach?: number | undefined;
  impressions?: number | undefined;
  followers?: number | undefined;
}): number => {
  const { likes = 0, comments = 0, shares = 0, saved = 0 } = metrics;
  const interactions = likes + comments * 2 + saved * 3 + shares;

  const divisor =
    (metrics.reach && metrics.reach > 0) ? metrics.reach :
    (metrics.impressions && metrics.impressions > 0) ? metrics.impressions :
    0;

  if (divisor === 0) return 0;
  return (interactions / divisor) * 100;
};

/**
 * Get the tier classification for an engagement rate
 * - high: >3% (exceptional performance)
 * - medium: 1.5-3% (good performance)
 * - low: <1.5% (average/below average)
 */
export const getERTier = (er: number): ERTier => {
  if (er > 3) return 'high';
  if (er >= 1.5) return 'medium';
  return 'low';
};

/**
 * Get badge styling configuration based on engagement rate
 * Colors are optimized for both dark and light modes with WCAG AA contrast
 */
export const getERBadgeConfig = (er: number): ERBadgeConfig => {
  const tier = getERTier(er);

  // Cap display at 20% to avoid misleading high percentages from low-view posts
  const displayER = Math.min(er, 20);

  // CLAUDE.md editorial health palette — never stoplight (emerald/amber/red).
  // Good = muted sage, warn = warm gold, idle = neutral grey. Values come from
  // the --color-health-* CSS vars resolved at runtime.
  const configs: Record<ERTier, ERBadgeConfig> = {
    high: {
      tier: 'high',
      label: `${displayER.toFixed(1)}%`,
      bgColor: 'color-mix(in srgb, var(--color-health-good) 12%, transparent)',
      textColor: 'var(--color-health-good)',
      borderColor: 'color-mix(in srgb, var(--color-health-good) 30%, transparent)',
    },
    medium: {
      tier: 'medium',
      label: `${displayER.toFixed(1)}%`,
      bgColor: 'color-mix(in srgb, var(--color-health-warn) 12%, transparent)',
      textColor: 'var(--color-health-warn)',
      borderColor: 'color-mix(in srgb, var(--color-health-warn) 30%, transparent)',
    },
    low: {
      tier: 'low',
      label: `${displayER.toFixed(1)}%`,
      bgColor: 'color-mix(in srgb, var(--color-health-idle) 14%, transparent)',
      textColor: 'var(--color-health-idle)',
      borderColor: 'color-mix(in srgb, var(--color-health-idle) 30%, transparent)',
    },
  };

  return configs[tier];
};

/**
 * Calculate aggregate Threads engagement rate from dashboard stats totals.
 * Weighted formula (matches backend metricCalculators.ts):
 *   (likes + replies×2 + reposts×1.5 + quotes + shares) / views × 100
 */
export const calculateThreadsAggregateER = (stats: {
  totalLikes?: number | undefined;
  totalReplies?: number | undefined;
  totalReposts?: number | undefined;
  totalQuotes?: number | undefined;
  totalShares?: number | undefined;
  totalViews?: number | undefined;
}): number => {
  const interactions = (stats.totalLikes || 0)
    + (stats.totalReplies || 0) * 2
    + (stats.totalReposts || 0) * 1.5
    + (stats.totalQuotes || 0)
    + (stats.totalShares || 0);
  if (!stats.totalViews || stats.totalViews === 0) return 0;
  return (interactions / stats.totalViews) * 100;
};

/**
 * Calculate aggregate Instagram engagement rate from dashboard stats totals.
 * Weighted formula (matches backend metricCalculators.ts):
 *   (likes + comments×2 + saved×3 + shares) / reach × 100
 * Falls back to impressions if reach is 0.
 */
export const calculateInstagramAggregateER = (stats: {
  totalLikes?: number | undefined;
  totalComments?: number | undefined;
  totalSaved?: number | undefined;
  totalShares?: number | undefined;
  totalReach?: number | undefined;
  totalImpressions?: number | undefined;
}, insights?: { totalInteractions?: number | undefined; reach?: number | undefined }): number => {
  // Source consistency guard: only use insights when both fields are present.
  // If insights is partial (API failure), fall through to all-post-level igStats
  // to ensure numerator and denominator always come from the same source.
  if (insights?.totalInteractions && insights?.reach) {
    return (insights.totalInteractions / insights.reach) * 100;
  }
  const interactions = (stats.totalLikes || 0)
    + (stats.totalComments || 0) * 2
    + (stats.totalSaved || 0) * 3
    + (stats.totalShares || 0);
  const divisor = (stats.totalReach && stats.totalReach > 0)
    ? stats.totalReach
    : (stats.totalImpressions && stats.totalImpressions > 0)
      ? stats.totalImpressions
      : 0;
  if (divisor === 0) return 0;
  return (interactions / divisor) * 100;
};

/**
 * Check if a post qualifies for AI Boost (high performer)
 * Requires >3% engagement rate and at least 10 views for reliability
 */
export const isHighPerformer = (performance: PostPerformance | undefined): boolean => {
  if (!performance?.views) return false;

  // Require minimum views for statistical significance
  if (performance.views < 10) return false;

  const er = calculateEngagementRate(performance);
  return er !== null && er > 3;
};

/**
 * Format engagement rate for display with appropriate precision
 */
export const formatEngagementRate = (er: number | null): string => {
  if (er === null) return '-';
  if (er < 0.1) return '<0.1%';
  if (er > 20) return '>20%';
  return `${er.toFixed(1)}%`;
};
