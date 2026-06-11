import { create } from "zustand";
import { createTimeWindowCache } from "@/lib/createTimeWindowCache";

const dashboardCache = createTimeWindowCache<unknown>(60_000);

interface DashboardCacheState {
	/** Cache keyed by accountId/platform combo */
	cache: Record<string, { data: unknown; fetchedAt: number }>;
	set: (key: string, data: unknown) => void;
	get: (key: string, maxAge?: number) => unknown | null;
	clear: () => void;
}

export const useDashboardStore = create<DashboardCacheState>((set) => ({
	cache: {},
	set: (key, data) => {
		dashboardCache.set(key, data);
		set((state) => ({
			cache: { ...state.cache, [key]: { data, fetchedAt: Date.now() } },
		}));
	},
	get: (key, maxAge = 60_000) => {
		return dashboardCache.get(key, maxAge);
	},
	clear: () => {
		dashboardCache.clear();
		set({ cache: {} });
	},
}));
