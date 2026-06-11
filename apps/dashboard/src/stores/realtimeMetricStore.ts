import { create } from "zustand";

/**
 * realtimeMetricStore — tracks optimistic metric bumps from webhook events.
 *
 * Webhook broadcasts include `threads_user_id` / `ig_user_id` and `event_type`
 * but NOT a specific post ID. We store bumps keyed by account user ID so that
 * the most recent post for that account can optimistically increment its counter.
 *
 * Flow:
 * 1. Webhook event arrives (e.g. threads_event { event_type: "replies", threads_user_id: "123" })
 * 2. PostsPage calls bumpAccountMetric("123", "replies")
 * 3. TweetCard for the most recent post by that account reads the bump
 * 4. AnimatedNumber smoothly animates the increment
 * 5. On next data refetch, bumps are cleared (real data replaces optimistic)
 */

export type MetricField =
	| "replies"
	| "likes"
	| "views"
	| "reposts"
	| "quotes"
	| "reach"
	| "saves"
	| "shares"
	| "comments"
	| "mentions";

export interface MetricBumps {
	[metric: string]: number;
}

interface RealtimeMetricState {
	/** Account-level bumps: { [accountUserId]: { replies: 1, comments: 2, ... } } */
	accountBumps: Record<string, MetricBumps>;

	/** Bump a metric for an account (incremental +delta) */
	bumpAccountMetric: (
		accountUserId: string,
		metric: MetricField,
		delta?: number,
	) => void;

	/** Clear all bumps for an account (e.g. after a data refetch) */
	clearAccountBumps: (accountUserId: string) => void;

	/** Clear all bumps globally (e.g. on full refresh) */
	clearAllBumps: () => void;
}

export const useRealtimeMetricStore = create<RealtimeMetricState>((set) => ({
	accountBumps: {},

	bumpAccountMetric: (accountUserId, metric, delta = 1) => {
		set((state) => {
			const existing = state.accountBumps[accountUserId] || {};
			return {
				accountBumps: {
					...state.accountBumps,
					[accountUserId]: {
						...existing,
						[metric]: (existing[metric] || 0) + delta,
					},
				},
			};
		});
	},

	clearAccountBumps: (accountUserId) => {
		set((state) => {
			const { [accountUserId]: _, ...rest } = state.accountBumps;
			return { accountBumps: rest };
		});
	},

	clearAllBumps: () => {
		set({ accountBumps: {} });
	},
}));
