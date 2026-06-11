/**
 * Health-score → color mapping. Single source of truth across Accounts,
 * Dashboard fleet wall, Inbox attention rows, and any future surface
 * that shows per-account health.
 *
 * Published breakpoints — do NOT shift without a design-system change:
 *   85+ → sage (Good)
 *   65–84 → warning/amber (Attention)
 *   <65 → critical red (Critical)
 */
export function healthColor(score: number): string {
	if (score >= 85) return "var(--color-health-good)";
	if (score >= 65) return "var(--color-warning)";
	return "var(--color-health-critical)";
}

export type HealthTier = "good" | "warn" | "crit";

export function healthTier(score: number): HealthTier {
	if (score >= 85) return "good";
	if (score >= 65) return "warn";
	return "crit";
}
