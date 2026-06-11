/**
 * Format a follower count with K/M abbreviations.
 * e.g. 1234 → "1.2K", 1500000 → "1.5M"
 */
export function formatFollowers(count: number): string {
	if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
	if (count >= 1000) return `${(count / 1000).toFixed(1)}K`;
	return count.toString();
}
