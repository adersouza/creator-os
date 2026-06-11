import { useQuery } from "@tanstack/react-query";
import { useAuthUser } from "@/hooks/useAuthUser";
import { getApiAuthHeaders } from "@/lib/apiAuth";
import { apiUrl } from "@/lib/apiUrl";

export type ViewsSource =
	| "home"
	| "profile"
	| "search"
	| "activity"
	| "ig"
	| "fb";

export interface ViewsBySourcePoint {
	date: string;
	home: number;
	profile: number;
	search: number;
	activity: number;
	ig: number;
	fb: number;
	total: number;
}

export interface ViewsBySourceData {
	accountIds: string[];
	periodDays: number;
	series: ViewsBySourcePoint[];
	totals: Record<ViewsSource, number>;
	empty: boolean;
}

interface ViewsBySourceState {
	data: ViewsBySourceData | null;
	isLoading: boolean;
	hasError: boolean;
}

interface FetchArgs {
	accountIds?: string[] | undefined;
	accountId?: string | undefined;
	days: number;
}

async function fetchViewsBySource(args: FetchArgs): Promise<ViewsBySourceData> {
	const params = new URLSearchParams({ days: String(args.days) });
	if (args.accountId) params.set("accountId", args.accountId);
	else if (args.accountIds && args.accountIds.length > 0)
		params.set("accountIds", args.accountIds.join(","));

	const response = await fetch(
		apiUrl(`/api/analytics?action=views-by-source&${params}`),
		{
			headers: await getApiAuthHeaders(),
		},
	);
	if (!response.ok) throw new Error("Failed to fetch views-by-source");
	const body = (await response.json()) as {
		success: boolean;
	} & ViewsBySourceData;
	return {
		accountIds: body.accountIds,
		periodDays: body.periodDays,
		series: body.series,
		totals: body.totals,
		empty: body.empty,
	};
}

/**
 * Threads views-by-source daily series (§2 evidence tile). Source buckets:
 * home, profile, search, activity, ig, fb. Backed by
 * account_analytics.threads_views_by_source captured daily during sync.
 *
 * Scope: pass `accountId` for a single account, `accountIds` for a fleet
 * subset, or nothing to query every Threads account in the user's context
 * (workspace-aware).
 */
export function useViewsBySource(args: {
	accountId?: string | null | undefined;
	accountIds?: string[] | null | undefined;
	days?: number | undefined;
	enabled?: boolean | undefined;
}): ViewsBySourceState {
	const { accountId, accountIds, days = 30, enabled = true } = args;
	const authUser = useAuthUser();
	const userKey = authUser ? authUser.id : null;
	const explicitScope = Array.isArray(accountIds);

	const scopeKey = accountId
		? `one:${accountId}`
		: explicitScope
			? `many:${[...accountIds].sort().join(",")}`
			: "all";

	const { data, isPending, isError } = useQuery<ViewsBySourceData>({
		queryKey: ["viewsBySource", userKey, scopeKey, days],
		enabled: !!userKey && enabled,
		staleTime: 5 * 60 * 1000,
		refetchOnWindowFocus: false,
		queryFn: () => {
			if (!accountId && explicitScope && accountIds.length === 0) {
				return {
					accountIds: [],
					periodDays: days,
					series: [],
					totals: { home: 0, profile: 0, search: 0, activity: 0, ig: 0, fb: 0 },
					empty: true,
				};
			}
			return fetchViewsBySource({
				days,
				...(accountId
					? { accountId }
					: accountIds && accountIds.length > 0
						? { accountIds }
						: {}),
			});
		},
	});

	return {
		data: data ?? null,
		isLoading: !!userKey && enabled && isPending,
		hasError: !!userKey && enabled && isError,
	};
}
