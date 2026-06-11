import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/services/supabase";
import { useAuthUser } from "@/hooks/useAuthUser";
import { fetchConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { queryClient } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";

export interface StoryAccountRow {
	igUserId: string;
	accountId: string;
	username: string | null;
	reach: number;
	follows: number;
	replies: number;
	impressions: number;
	exits: number;
	tapsBack: number;
	// Fractional rates (0–1). null when reach == 0.
	completionRate: number | null;
	tapBackRate: number | null;
}

interface StoryActivityResponse {
	totalReach: number;
	totalFollows: number;
	totalImpressions: number;
	totalExits: number;
	totalTapsBack: number;
	// Reach-weighted fleet rates (0–1). null when totalReach == 0.
	fleetCompletionRate: number | null;
	fleetTapBackRate: number | null;
	accounts: StoryAccountRow[];
}

interface StoryActivityState extends StoryActivityResponse {
	isLoading: boolean;
	hasError: boolean;
}

const EMPTY: StoryActivityResponse = {
	totalReach: 0,
	totalFollows: 0,
	totalImpressions: 0,
	totalExits: 0,
	totalTapsBack: 0,
	fleetCompletionRate: null,
	fleetTapBackRate: null,
	accounts: [],
};
const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * IG story activity from synced post insights. Story → profile transition is
 * not in the Meta API surface, so this reports raw measurable story metrics
 * instead of inferring "profile visits."
 */
export function useStoryActivity(
	periodDays: number = 30,
	accountIds?: string[] | null,
): StoryActivityState {
	const authUser = useAuthUser();
	const userKey = authUser ? authUser.id : null;
	const scopedIds = accountIds?.filter(Boolean) ?? [];
	const scopedKey = Array.isArray(accountIds)
		? scopedIds.slice().sort().join(",")
		: null;

	const { data, isPending, isError } = useQuery<StoryActivityResponse>({
		queryKey: ["storyActivity", userKey, periodDays, scopedKey],
		enabled: !!userKey,
		staleTime: 5 * 60 * 1000,
		refetchOnWindowFocus: false,
		queryFn: async (): Promise<StoryActivityResponse> => {
			if (!userKey) return EMPTY;
			if (Array.isArray(accountIds) && scopedIds.length === 0) return EMPTY;

			const since = new Date(Date.now() - periodDays * DAY_MS).toISOString();
			let insightsQuery = supabase
				.from("posts")
				.select(
					"instagram_account_id, ig_impressions, ig_reach, ig_follows_count, ig_story_exits, ig_story_replies, ig_story_taps_back, ig_story_taps_forward, ig_media_type, media_type",
				)
				.eq("user_id", userKey)
				.eq("platform", "instagram")
				.eq("status", "published")
				.gte("published_at", since);

			if (scopedIds.length > 0)
				insightsQuery = insightsQuery.in("instagram_account_id", scopedIds);

			const [connectedAccounts, insightsRes] = await Promise.all([
				queryClient.fetchQuery({
					queryKey: queryKeys.accounts.connected(userKey),
					staleTime: 5 * 60_000,
					gcTime: 15 * 60_000,
					queryFn: () => fetchConnectedAccounts(userKey),
				}),
				insightsQuery,
			]);

			if (insightsRes.error) return EMPTY;

			const accountsById = new Map<string, { username: string | null }>();
			for (const account of connectedAccounts) {
				if (scopedIds.length > 0 && !scopedIds.includes(account.id)) continue;
				if (account.platform === "instagram") {
					accountsById.set(account.id, {
						username: account.handle.replace(/^@/, ""),
					});
				}
			}
			if (accountsById.size === 0) return EMPTY;

			const byAccount = new Map<string, StoryAccountRow>();
			for (const row of (insightsRes.data ?? []) as Array<{
				instagram_account_id: string | null;
				ig_impressions: number | null;
				ig_reach: number | null;
				ig_follows_count: number | null;
				ig_story_exits: number | null;
				ig_story_replies: number | null;
				ig_story_taps_back: number | null;
				ig_story_taps_forward: number | null;
				ig_media_type: string | null;
				media_type: string | null;
			}>) {
				if (!row.instagram_account_id) continue;
				const meta = accountsById.get(row.instagram_account_id);
				if (!meta) continue;

				const mediaType =
					`${row.ig_media_type ?? ""} ${row.media_type ?? ""}`.toLowerCase();
				const hasStoryMetrics =
					(row.ig_story_exits ?? 0) > 0 ||
					(row.ig_story_replies ?? 0) > 0 ||
					(row.ig_story_taps_back ?? 0) > 0 ||
					(row.ig_story_taps_forward ?? 0) > 0;
				if (!mediaType.includes("story") && !hasStoryMetrics) continue;

				const existing = byAccount.get(row.instagram_account_id) ?? {
					igUserId: row.instagram_account_id,
					accountId: row.instagram_account_id,
					username: meta.username,
					reach: 0,
					follows: 0,
					replies: 0,
					impressions: 0,
					exits: 0,
					tapsBack: 0,
					completionRate: null,
					tapBackRate: null,
				};
				existing.reach += row.ig_reach || 0;
				existing.follows += row.ig_follows_count || 0;
				existing.replies += row.ig_story_replies || 0;
				existing.impressions += row.ig_impressions || 0;
				existing.exits += row.ig_story_exits || 0;
				existing.tapsBack += row.ig_story_taps_back || 0;
				byAccount.set(row.instagram_account_id, existing);
			}

			// Compute per-account rates after summation.
			// Completion rate = (reach − exits) / reach. Pre-expiry stories only;
			// exits is monotonic-cumulative over the story's lifetime.
			// Tap-back rate = taps_back / reach.
			for (const acc of byAccount.values()) {
				if (acc.reach > 0) {
					acc.completionRate = Math.max(0, (acc.reach - acc.exits) / acc.reach);
					acc.tapBackRate = acc.tapsBack / acc.reach;
				}
			}

			const accounts = [...byAccount.values()].sort(
				(a, b) => b.reach - a.reach,
			);
			const totals = accounts.reduce(
				(acc, a) => {
					acc.totalReach += a.reach;
					acc.totalFollows += a.follows;
					acc.totalImpressions += a.impressions;
					acc.totalExits += a.exits;
					acc.totalTapsBack += a.tapsBack;
					return acc;
				},
				{
					totalReach: 0,
					totalFollows: 0,
					totalImpressions: 0,
					totalExits: 0,
					totalTapsBack: 0,
				},
			);

			// Reach-weighted fleet rates: divide aggregate exits/taps_back by
			// aggregate reach, NOT the mean of per-account rates. Avoids letting
			// tiny-reach accounts skew the headline.
			const fleetCompletionRate =
				totals.totalReach > 0
					? Math.max(
							0,
							(totals.totalReach - totals.totalExits) / totals.totalReach,
						)
					: null;
			const fleetTapBackRate =
				totals.totalReach > 0 ? totals.totalTapsBack / totals.totalReach : null;

			return { ...totals, fleetCompletionRate, fleetTapBackRate, accounts };
		},
	});

	return {
		...(data ?? EMPTY),
		isLoading: !!userKey && isPending,
		hasError: !!userKey && isError,
	};
}
