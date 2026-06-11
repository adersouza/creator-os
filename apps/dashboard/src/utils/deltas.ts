export function computeDelta(
	current: number,
	previous: number,
): { value: string; trend: "up" | "down" | "neutral" } {
	if (previous <= 0 && current === 0) return { value: "0%", trend: "neutral" };
	if (previous <= 0)
		return {
			value: current > 0 ? "+∞" : "0%",
			trend: current > 0 ? "up" : "neutral",
		};
	const pct = ((current - previous) / previous) * 100;
	if (Math.abs(pct) < 0.1) return { value: "0%", trend: "neutral" };
	const sign = pct >= 0 ? "+" : "";
	return {
		value: `${sign}${pct.toFixed(1)}%`,
		trend: pct > 0 ? "up" : pct < 0 ? "down" : "neutral",
	};
}

export type DeltaResult = ReturnType<typeof computeDelta>;

export interface StatsDeltas {
	followers: string;
	likes: string;
	replies: string;
	reposts: string;
	views: string;
	clicks: string;
	reach: string;
	saves: string;
	shares: string;
	engagement: string;
}

export const EMPTY_DELTAS: StatsDeltas = {
	followers: "—",
	likes: "—",
	replies: "—",
	reposts: "—",
	views: "—",
	clicks: "—",
	reach: "—",
	saves: "—",
	shares: "—",
	engagement: "—",
};
