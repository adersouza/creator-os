import { create } from "zustand";

interface ApiError {
	id: string;
	type: "rate_limit" | "auth" | "network" | "server";
	message: string;
	retryAfter?: number | undefined;
	requestId?: string | undefined;
	timestamp: number;
}

interface ErrorStore {
	errors: ApiError[];
	addError: (error: Omit<ApiError, "id" | "timestamp">) => void;
	removeError: (id: string) => void;
	dismissError: (id: string) => void;
	clearErrors: () => void;
	clearAllTimers: () => void;
}

// Track auto-dismiss timeouts so they can be cleaned up
const dismissTimers = new Map<string, ReturnType<typeof setTimeout>>();

export const useErrorStore = create<ErrorStore>((set, get) => ({
	errors: [],
	addError: (error) => {
		const id = `${error.type}_${Date.now()}`;
		if (
			error.type === "rate_limit" &&
			get().errors.some((e) => e.type === "rate_limit")
		)
			return;
		set((state) => ({
			errors: [...state.errors, { ...error, id, timestamp: Date.now() }],
		}));
		const dismissAfter = (error.retryAfter || 30) * 1000;
		const timer = setTimeout(() => {
			dismissTimers.delete(id);
			set((state) => ({
				errors: state.errors.filter((e) => e.id !== id),
			}));
		}, dismissAfter);
		dismissTimers.set(id, timer);
	},
	removeError: (id) => {
		const timer = dismissTimers.get(id);
		if (timer) {
			clearTimeout(timer);
			dismissTimers.delete(id);
		}
		set((state) => ({
			errors: state.errors.filter((e) => e.id !== id),
		}));
	},
	dismissError: (id) => {
		// Alias for removeError — also clears the auto-dismiss timer for this error
		const timer = dismissTimers.get(id);
		if (timer) {
			clearTimeout(timer);
			dismissTimers.delete(id);
		}
		set((state) => ({
			errors: state.errors.filter((e) => e.id !== id),
		}));
	},
	clearAllTimers: () => {
		for (const timer of dismissTimers.values()) clearTimeout(timer);
		dismissTimers.clear();
	},
	clearErrors: () => {
		// Clear all pending auto-dismiss timers, then reset error state
		for (const timer of dismissTimers.values()) clearTimeout(timer);
		dismissTimers.clear();
		set({ errors: [] });
	},
}));
