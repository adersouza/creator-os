/**
 * Canonical niche set — single source for the cohort pipeline.
 *
 * The (follower_tier × niche) lattice is 5 × 8 = 40 cells. Kept deliberately
 * small so that, at realistic opt-in bases, k-anonymity (N ≥ 30 accounts AND
 * N ≥ 10 users for medians) does not suppress the majority of cells. Expand
 * only when monitoring shows most cells are clearing thresholds.
 *
 * Imported by the Settings opt-in UI (dropdown), the aggregation job (AI
 * fallback normalization), and the read-side API handler.
 */

export const CANONICAL_NICHES = [
  'ofm',
  'fitness',
  'beauty',
  'lifestyle',
  'business',
  'finance',
  'tech',
  'uncategorized',
] as const;

export type CanonicalNiche = (typeof CANONICAL_NICHES)[number];

export const NICHE_LABELS: Record<CanonicalNiche, string> = {
  ofm: 'OFM',
  fitness: 'Fitness',
  beauty: 'Beauty',
  lifestyle: 'Lifestyle',
  business: 'Business',
  finance: 'Finance',
  tech: 'Tech',
  uncategorized: 'Uncategorized',
};

const NICHE_SET: Set<string> = new Set(CANONICAL_NICHES);

export function isCanonicalNiche(value: unknown): value is CanonicalNiche {
  return typeof value === 'string' && NICHE_SET.has(value);
}

/**
 * Normalize free-text niche hints (e.g., `account_groups.category`) against
 * the canonical set. Falls back to 'uncategorized' when no match.
 */
export function normalizeNiche(raw: string | null | undefined): CanonicalNiche {
  if (!raw) return 'uncategorized';
  const lower = raw.trim().toLowerCase();
  if (NICHE_SET.has(lower)) return lower as CanonicalNiche;
  // Light aliasing for common variants; extend cautiously.
  const aliases: Record<string, CanonicalNiche> = {
    'only fans': 'ofm',
    onlyfans: 'ofm',
    creator: 'ofm',
    gym: 'fitness',
    workout: 'fitness',
    makeup: 'beauty',
    skincare: 'beauty',
    wellness: 'lifestyle',
    travel: 'lifestyle',
    entrepreneur: 'business',
    marketing: 'business',
    crypto: 'finance',
    investing: 'finance',
    software: 'tech',
    ai: 'tech',
  };
  return aliases[lower] ?? 'uncategorized';
}
