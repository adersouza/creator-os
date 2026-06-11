import { create } from "zustand";
import type { ViewMode } from "@/types/index";

interface ShortcutsState {
	isCheatSheetOpen: boolean;
	pendingG: boolean;
	navigateFn: ((view: ViewMode) => void) | null;
	createPostFn: (() => void) | null;

	openCheatSheet: () => void;
	closeCheatSheet: () => void;
	toggleCheatSheet: () => void;
	setPendingG: (value: boolean) => void;
	registerNavigate: (fn: (view: ViewMode) => void) => void;
	registerCreatePost: (fn: () => void) => void;
}

export const useShortcutsStore = create<ShortcutsState>()((set) => ({
	isCheatSheetOpen: false,
	pendingG: false,
	navigateFn: null,
	createPostFn: null,

	openCheatSheet: () => set({ isCheatSheetOpen: true }),
	closeCheatSheet: () => set({ isCheatSheetOpen: false }),
	toggleCheatSheet: () =>
		set((s) => ({ isCheatSheetOpen: !s.isCheatSheetOpen })),
	setPendingG: (value) => set({ pendingG: value }),
	registerNavigate: (fn) => set({ navigateFn: fn }),
	registerCreatePost: (fn) => set({ createPostFn: fn }),
}));
