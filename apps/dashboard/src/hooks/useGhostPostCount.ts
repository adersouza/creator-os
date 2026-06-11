import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/services/supabase";
import { useAuthUser } from "@/hooks/useAuthUser";
import { fetchConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { queryClient } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";

export interface GhostFleetAccount {
	accountId: string;
	username: string | null;
	ghostCount: number;
	withLinks: number;
	/** Most recent ghost-post age in hours, used to highlight active suppression. */
	freshestAgeHours: number;
	hasLink: boolean;
}

interface GhostCountResponse {
	total: number;
	withLinks: number;
	weekOverWeekDelta: number;
	accounts: GhostFleetAccount[];
}

interface GhostCountState extends GhostCountResponse {
	isLoading: boolean;
	hasError: boolean;
}

const EMPTY: GhostCountResponse = {
	total: 0,
	withLinks: 0,
	weekOverWeekDelta: 0,
	accounts: [],
};
const GHOST_VIEW_THRESHOLD = 10;
const GHOST_AGE_HOURS = 24;
const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Threads ghost-post count — published >24h ago with <10 views, fleet-wide.
 * Heuristic for shadowban / link suppression. Compares last 7d to prior 7d
 * for the WoW delta. Threads-only; IG ghost detection needs a different
 * heuristic (no per-post views < threshold maps cleanly to non-Reels feed).
 */
export function useGhostPostCount(
	accountIds?: string[] | null,
): GhostCountState {
	const authUser = useAuthUser();
	const userKey = authUser ? authUser.id : null;
	const scopedIds = accountIds?.filter(Boolean) ?? [];
	const scopedKey = Array.isArray(accountIds)
		? scopedIds.slice().sort().join(",")
		: null;

	const { data, isPending, isError } = useQuery<GhostCountResponse>({
		queryKey: ["ghostPostCount", userKey, scopedKey],
		enabled: !!userKey,
		staleTime: 5 * 60 * 1000,
		refetchOnWindowFocus: false,
		queryFn: async (): Promise<GhostCountResponse> => {
			if (!userKey) return EMPTY;
			if (Array.isArray(accountIds) && scopedIds.length === 0) return EMPTY;

			const now = Date.now();
			const ghostMaxPublished = new Date(
				now - GHOST_AGE_HOURS * 60 * 60 * 1000,
			).toISOString();
			const last7Cutoff = new Date(now - 7 * DAY_MS).toISOString();
			const prev7Cutoff = new Date(now - 14 * DAY_MS).toISOString();
			const prev7End = new Date(now - 7 * DAY_MS - 1).toISOString();

			let baseQuery = supabase
				.from("posts")
				.select("id, content, published_at, account_id", { count: "exact" })
				.eq("user_id", userKey)
				.eq("platform", "threads")
				.eq("status", "published")
				.lt("views_count", GHOST_VIEW_THRESHOLD)
				.lt("published_at", ghostMaxPublished);

			let prevQuery = supabase
				.from("posts")
				.select("id", { count: "exact" })
				.eq("user_id", userKey)
				.eq("platform", "threads")
				.eq("status", "published")
				.lt("views_count", GHOST_VIEW_THRESHOLD)
				.gte("published_at", prev7Cutoff)
				.lte("published_at", prev7End)
				.limit(1);

			if (scopedIds.length > 0) {
				baseQuery = baseQuery.in("account_id", scopedIds);
				prevQuery = prevQuery.in("account_id", scopedIds);
			}

			const [last7Res, prev7Res, accountRows] = await Promise.all([
				baseQuery.gte("published_at", last7Cutoff),
				prevQuery,
				queryClient.fetchQuery({
					queryKey: queryKeys.accounts.connected(userKey),
					staleTime: 5 * 60_000,
					gcTime: 15 * 60_000,
					queryFn: () => fetchConnectedAccounts(userKey),
				}),
			]);

			if (last7Res.error) throw last7Res.error;
			if (prev7Res.error) throw prev7Res.error;

			const total = last7Res.count ?? 0;
			const rows = (last7Res.data ?? []) as Array<{
				content: string | null;
				published_at: string | null;
				account_id: string | null;
			}>;
			const withLinks = rows.filter(
				(r) => typeof r.content === "string" && /https?:\/\//i.test(r.content),
			).length;
			const prevTotal = prev7Res.count ?? 0;
			const weekOverWeekDelta = total - prevTotal;

			// Per-account breakdown for the ghost-fleet tile. Sort by ghost count
			// descending; ties broken by freshest (newest) ghost so active spirals
			// float to the top.
			const usernameById = new Map<string, string | null>();
			for (const account of accountRows) {
				if (account.platform === "threads")
					usernameById.set(account.id, account.handle.replace(/^@/, ""));
			}

			const byAccount = new Map<string, GhostFleetAccount>();
			for (const r of rows) {
				if (!r.account_id) continue;
				const existing = byAccount.get(r.account_id) ?? {
					accountId: r.account_id,
					username: usernameById.get(r.account_id) ?? null,
					ghostCount: 0,
					withLinks: 0,
					freshestAgeHours: Number.POSITIVE_INFINITY,
					hasLink: false,
				};
				existing.ghostCount += 1;
				const linked =
					typeof r.content === "string" && /https?:\/\//i.test(r.content);
				if (linked) {
					existing.withLinks += 1;
					existing.hasLink = true;
				}
				if (r.published_at) {
					const ageH = (now - Date.parse(r.published_at)) / (60 * 60 * 1000);
					if (Number.isFinite(ageH) && ageH < existing.freshestAgeHours) {
						existing.freshestAgeHours = ageH;
					}
				}
				byAccount.set(r.account_id, existing);
			}

			const accounts = [...byAccount.values()]
				.map((a) => ({
					...a,
					freshestAgeHours: Number.isFinite(a.freshestAgeHours)
						? a.freshestAgeHours
						: 0,
				}))
				.sort((a, b) => {
					if (b.ghostCount !== a.ghostCount) return b.ghostCount - a.ghostCount;
					return a.freshestAgeHours - b.freshestAgeHours;
				});

			return { total, withLinks, weekOverWeekDelta, accounts };
		},
	});

	return {
		...(data ?? EMPTY),
		isLoading: !!userKey && isPending,
		hasError: !!userKey && isError,
	};
}
