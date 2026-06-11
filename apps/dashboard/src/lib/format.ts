export function formatNumber(n: number): string {
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
	return n.toString();
}

export type DeltaUnit = 'pts' | 'pp' | '%' | '';

/**
 * Signed delta formatter with Unicode minus (U+2212) for cleaner VoiceOver output.
 * Single source of truth for +/− sign choice across KPI surfaces.
 */
export function formatSignedDelta(
	v: number | null | undefined,
	unit: DeltaUnit = '',
	fractionDigits = 1,
): string | null {
	if (v == null) return null;
	const sign = v >= 0 ? '+' : '−';
	const suffix = unit === 'pts' ? ' pts' : unit;
	return `${sign}${Math.abs(v).toFixed(fractionDigits)}${suffix}`;
}

/**
 * Shared greeting. Falls through to "Good evening" for late/overnight hours
 * — HIG writing guidance avoids blame ("Still up", "oops"-style copy).
 */
export function greetingForHour(h: number = new Date().getHours()): string {
	if (h >= 5 && h < 12) return 'Good morning';
	if (h >= 12 && h < 17) return 'Good afternoon';
	return 'Good evening';
}
