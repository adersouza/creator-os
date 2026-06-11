/**
 * Canonical niche set — frontend mirror of `api/_lib/cohorts/niches.ts`.
 *
 * Kept in sync by hand. If you add a niche, add it in both places. The list
 * is tiny on purpose — the (tier × niche) lattice is 5 × 8 = 40 cells, and
 * k-anonymity bites harder when the lattice gets wider than the opt-in base.
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
