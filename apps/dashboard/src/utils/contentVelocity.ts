/**
 * Content Velocity — measures how fast a post reaches 1,000 views.
 * Saves-to-Reach Ratio — algorithmic signal strength for IG posts.
 */

export function getContentVelocity(
  views: number,
  publishedAt: Date | string | null
): { label: string; hoursTo1K: number | null; status: 'reached' | 'projected' | 'insufficient' } | null {
  if (!publishedAt || views <= 0) return null;

  const published = typeof publishedAt === 'string' ? new Date(publishedAt) : publishedAt;
  const publishedMs = published.getTime();
  if (Number.isNaN(publishedMs)) return null;
  const hoursSincePublish = (Date.now() - publishedMs) / (1000 * 60 * 60);

  if (hoursSincePublish < 0.5) return null; // Too early to measure

  if (views >= 1000) {
    // Already hit 1K — estimate when (linear interpolation)
    const hoursTo1K = Math.round((1000 / views) * hoursSincePublish * 10) / 10;
    if (hoursTo1K < 1) return { label: `1K in ${Math.round(hoursTo1K * 60)}m`, hoursTo1K, status: 'reached' };
    if (hoursTo1K < 24) return { label: `1K in ${hoursTo1K.toFixed(1)}h`, hoursTo1K, status: 'reached' };
    return { label: `1K in ${Math.round(hoursTo1K / 24)}d`, hoursTo1K, status: 'reached' };
  }

  if (views >= 100) {
    // Project based on current velocity
    const hoursTo1K = Math.round((1000 / views) * hoursSincePublish * 10) / 10;
    if (hoursTo1K > 720) return { label: 'Slow burn', hoursTo1K, status: 'projected' }; // >30 days
    if (hoursTo1K < 24) return { label: `~${hoursTo1K.toFixed(0)}h to 1K`, hoursTo1K, status: 'projected' };
    return { label: `~${Math.round(hoursTo1K / 24)}d to 1K`, hoursTo1K, status: 'projected' };
  }

  return { label: 'Building...', hoursTo1K: null, status: 'insufficient' };
}

export function getSavesToReachRatio(
  saves: number | null | undefined,
  reach: number | null | undefined
): { ratio: number; label: string; tier: 'high' | 'good' | 'low' | 'none' } | null {
  if (saves == null || reach == null || reach === 0) return null;

  const ratio = (saves / reach) * 100;

  if (ratio >= 5) return { ratio, label: `${ratio.toFixed(1)}%`, tier: 'high' };
  if (ratio >= 2) return { ratio, label: `${ratio.toFixed(1)}%`, tier: 'good' };
  if (ratio > 0) return { ratio, label: `${ratio.toFixed(1)}%`, tier: 'low' };
  return null;
}
