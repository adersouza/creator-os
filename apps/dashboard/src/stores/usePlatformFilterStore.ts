import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { PlatformFilter } from "@/types/platform";

export type { PlatformFilter } from "@/types/platform";

// Migrate old localStorage key
if (typeof window !== "undefined") {
	const old = localStorage.getItem("threadsdash-platform-filter");
	if (old && !localStorage.getItem("juno33-platform-filter")) {
		localStorage.setItem("juno33-platform-filter", old);
		localStorage.removeItem("threadsdash-platform-filter");
	}
}

interface PlatformFilterState {
	platform: PlatformFilter;
	setPlatform: (platform: PlatformFilter) => void;
	reset: () => void;
}

export const usePlatformFilterStore = create<PlatformFilterState>()(
	persist(
		(set) => ({
			platform: "all",
			setPlatform: (platform) => set({ platform }),
			reset: () => set({ platform: "all" }),
		}),
		{
			name: "juno33-platform-filter",
		},
	),
);
