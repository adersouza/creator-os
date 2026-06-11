import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { Platform } from "@/components/dashboard-v2/shared";
import type { TimeRange } from "@/lib/timeRange";

export type DashboardTimeframe = "7d" | "14d" | "30d" | "90d";

export interface DashboardUrlState {
	platform: Platform;
	timeframe: DashboardTimeframe;
}

export const DASHBOARD_TIMEFRAMES: Array<{
	id: DashboardTimeframe;
	label: string;
}> = [
	{ id: "7d", label: "7D" },
	{ id: "14d", label: "14D" },
	{ id: "30d", label: "30D" },
	{ id: "90d", label: "90D" },
];

const DEFAULT_STATE: DashboardUrlState = {
	platform: "all",
	timeframe: "30d",
};

const PLATFORM_SET = new Set<Platform>(["all", "threads", "ig"]);
const TIMEFRAME_SET = new Set<DashboardTimeframe>(["7d", "14d", "30d", "90d"]);

export function parseDashboardState(params: URLSearchParams): DashboardUrlState {
	const platformRaw = params.get("p");
	const timeframeRaw = params.get("d");
	return {
		platform: PLATFORM_SET.has(platformRaw as Platform)
			? (platformRaw as Platform)
			: DEFAULT_STATE.platform,
		timeframe: TIMEFRAME_SET.has(timeframeRaw as DashboardTimeframe)
			? (timeframeRaw as DashboardTimeframe)
			: DEFAULT_STATE.timeframe,
	};
}

export function serializeDashboardState(state: DashboardUrlState): URLSearchParams {
	const params = new URLSearchParams();
	if (state.platform !== DEFAULT_STATE.platform) params.set("p", state.platform);
	if (state.timeframe !== DEFAULT_STATE.timeframe) params.set("d", state.timeframe);
	return params;
}

export function useDashboardUrlState(): [
	DashboardUrlState,
	(patch: Partial<DashboardUrlState>) => void,
] {
	const [searchParams, setSearchParams] = useSearchParams();
	const state = useMemo(() => parseDashboardState(searchParams), [searchParams]);

	const update = useCallback(
		(patch: Partial<DashboardUrlState>) => {
			setSearchParams(serializeDashboardState({ ...state, ...patch }), {
				replace: true,
			});
		},
		[state, setSearchParams],
	);

	return [state, update];
}

export function dashboardTimeframeToDays(timeframe: DashboardTimeframe): number {
	switch (timeframe) {
		case "7d":
			return 7;
		case "14d":
			return 14;
		case "30d":
			return 30;
		case "90d":
			return 90;
	}
}

export function dashboardTimeframeToFleetMetrics(
	timeframe: DashboardTimeframe,
): TimeRange {
	if (timeframe == null) return '30d';
	return timeframe;
}

export function dashboardTimeframeToTopPosts(
	timeframe: DashboardTimeframe,
): TimeRange {
	if (timeframe == null) return '30d';
	return timeframe;
}
