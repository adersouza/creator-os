// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
// Meta Platform Terms: Do not send exact API metrics to third-party AI services
/**
 * Sanitize user data before sending to third-party AI.
 * Strips exact metric values, replaces with relative descriptors.
 * Keeps user-authored content (they wrote it, they can share it).
 */

export function sanitizeMetrics(metrics: Record<string, number>): string {
	const descriptions: string[] = [];
	for (const [key, value] of Object.entries(metrics)) {
		if (value == null || Number.isNaN(value)) continue;
		descriptions.push(`${key}: ${describeValue(value)}`);
	}
	return descriptions.join(", ");
}

export function describeValue(value: number): string {
	if (value === 0) return "none";
	if (value < 10) return "very low";
	if (value < 50) return "low";
	if (value < 100) return "moderate";
	if (value < 500) return "good";
	if (value < 1000) return "strong";
	if (value < 5000) return "high";
	return "very high";
}

/**
 * Describe a post's performance relative to account averages.
 * Uses multiplier-based language instead of exact numbers.
 */
export function describeRelativePerformance(
	actual: number,
	average: number,
	metricName: string,
): string {
	if (average <= 0) return `${metricName}: no baseline`;
	const ratio = actual / average;
	if (ratio < 0.25) return `${metricName}: far below average`;
	if (ratio < 0.5) return `${metricName}: well below average`;
	if (ratio < 0.75) return `${metricName}: below average`;
	if (ratio < 1.25) return `${metricName}: around average`;
	if (ratio < 2) return `${metricName}: above average`;
	if (ratio < 4) return `${metricName}: well above average`;
	return `${metricName}: far above average`;
}

/**
 * Sanitize analytics time series for AI context.
 * Converts exact numbers to trend descriptions.
 */
export function describeAnalyticsTrend(
	rows: Array<{ date: string; [key: string]: unknown }>,
	metricKey: string,
): string {
	if (!rows || rows.length === 0) return "no data";
	if (rows.length === 1)
		return describeValue((rows[0]![metricKey] as number) || 0);

	const values = rows.map((r) => (r[metricKey] as number) || 0);
	const first = values[0];
	const last = values[values.length - 1];
	const avg = values.reduce((s, v) => s + v, 0) / values.length;

	const trend =
		last! > first! * 1.1
			? "trending up"
			: last! < first! * 0.9
				? "trending down"
				: "stable";

	return `${describeValue(avg)} (${trend} over ${rows.length} days)`;
}

/**
 * Describe an engagement rate without revealing exact value.
 */
export function describeEngagementRate(rate: number): string {
	if (rate <= 0) return "no engagement";
	if (rate < 1) return "low engagement";
	if (rate < 3) return "moderate engagement";
	if (rate < 5) return "good engagement";
	if (rate < 10) return "strong engagement";
	return "exceptional engagement";
}
