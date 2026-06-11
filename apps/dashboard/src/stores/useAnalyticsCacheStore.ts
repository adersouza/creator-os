/**
 * useAnalyticsCacheStore — Generic key-value cache for raw analytics API responses.
 *
 * Short-lived (30-minute TTL) cache for dashboard stats, chart data, and other
 * analytics API payloads. Prevents redundant network requests when navigating
 * between tabs/pages. Keys are typically "{accountId}:{endpoint}" strings.
 *
 * NOT for AI-generated results — those live in analyticsStore (24h TTL).
 * Both stores coexist intentionally because they cache fundamentally different data
 * at different freshness requirements.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { createTimeWindowCache } from "@/lib/createTimeWindowCache";

const DEFAULT_MAX_AGE = 30 * 60 * 1000; // 30 minutes

const analyticsCache = createTimeWindowCache<unknown>(DEFAULT_MAX_AGE);

interface AnalyticsCacheState {
	entries: Record<string, { data: unknown; fetchedAt: number }>;

	set: (key: string, data: unknown) => void;
	get: (key: string, maxAge?: number) => unknown | null;
	clear: () => void;
	clearForAccount: (accountId: string) => void;
}

export const useAnalyticsCacheStore = create<AnalyticsCacheState>()(
	persist(
		(set) => ({
			entries: {},

			set: (key, data) => {
				analyticsCache.set(key, data);
				set((state) => ({
					entries: {
						...state.entries,
						[key]: { data, fetchedAt: Date.now() },
					},
				}));
			},

			get: (key, maxAge = DEFAULT_MAX_AGE) => {
				return analyticsCache.get(key, maxAge);
			},

			clear: () => {
				analyticsCache.clear();
				set({ entries: {} });
			},

			clearForAccount: (accountId) => {
				analyticsCache.clearByPrefix(`${accountId}:`);
				set((state) => {
					const filtered: Record<string, { data: unknown; fetchedAt: number }> =
						{};
					for (const [k, v] of Object.entries(state.entries)) {
						if (!k.startsWith(`${accountId}:`)) filtered[k] = v;
					}
					return { entries: filtered };
				});
			},
		}),
		{
			name: "juno33-analytics-cache",
			version: 1,
			partialize: (state) => ({ entries: state.entries }),
		},
	),
);
