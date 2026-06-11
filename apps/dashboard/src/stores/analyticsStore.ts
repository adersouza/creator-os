/**
 * analyticsStore — Analytics UI state (timeframe, refresh).
 *
 * AI result caching lives in analyticsAICacheStore (split via M14).
 * Raw analytics API data lives in useAnalyticsCacheStore (30m TTL).
 *
 * Re-exports AI cache types and store for backward compatibility.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { useAnalyticsAICacheStore } from "./analyticsAICacheStore";

// Re-export AI cache types for backward compatibility
export type {
	CachedDiagnosis,
	CachedViralAnalysis,
} from "./analyticsAICacheStore";

export type Timeframe = "7D" | "30D" | "90D" | "YTD";

interface AnalyticsState {
	timeframe: Timeframe;
	setTimeframe: (tf: Timeframe) => void;
	refreshKey: number;
	forceRefresh: () => void;
	reset: () => void;
}

export const useAnalyticsStore = create<AnalyticsState>()(
	persist(
		(set) => ({
			timeframe: "30D",
			setTimeframe: (tf) => set({ timeframe: tf, refreshKey: Date.now() }),
			refreshKey: Date.now(),
			forceRefresh: () => {
				set({ refreshKey: Date.now() });
				useAnalyticsAICacheStore.getState().clearAICache();
			},
			reset: () => {
				set({ timeframe: "30D", refreshKey: Date.now() });
				useAnalyticsAICacheStore.getState().clearAICache();
			},
		}),
		{
			name: "analytics-store",
			partialize: (state) => ({
				timeframe: state.timeframe,
			}),
		},
	),
);

// Helper to get date range from timeframe
export const getDateRangeFromTimeframe = (
	timeframe: Timeframe,
): { start: Date; end: Date } => {
	const end = new Date();
	end.setHours(23, 59, 59, 999);
	const start = new Date();

	switch (timeframe) {
		case "7D":
			start.setDate(start.getDate() - 7);
			break;
		case "30D":
			start.setDate(start.getDate() - 30);
			break;
		case "90D":
			start.setDate(start.getDate() - 90);
			break;
		case "YTD":
			start.setMonth(0, 1);
			break;
	}
	start.setHours(0, 0, 0, 0);
	return { start, end };
};

// Helper to format date range for display
export const formatTimeframeRange = (timeframe: Timeframe): string => {
	const { start, end } = getDateRangeFromTimeframe(timeframe);
	const formatOptions: Intl.DateTimeFormatOptions = {
		month: "short",
		day: "numeric",
	};
	const startStr = start.toLocaleDateString("en-US", formatOptions);
	const endStr = end.toLocaleDateString("en-US", formatOptions);
	return `${startStr} – ${endStr}`;
};

export const timeframeLabels: Record<Timeframe, string> = {
	"7D": "last 7 days",
	"30D": "last 30 days",
	"90D": "last 90 days",
	YTD: "year to date",
};
