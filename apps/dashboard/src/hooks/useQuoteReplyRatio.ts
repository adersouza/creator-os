import { useQuery } from "@tanstack/react-query";
import { useAuthUser } from "@/hooks/useAuthUser";
import { getApiAuthHeaders } from "@/lib/apiAuth";
import { apiUrl } from "@/lib/apiUrl";
import { supabase } from "@/services/supabase";
import { fetchConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { queryClient } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";

export interface QuoteReplyAccount {
	accountId: string;
	username: string | null;
	ratio: number | null;
	quotes: number;
	replies: number;
	posts: number;
}

interface QuoteReplyResponse {
	fleetRatio: number | null;
	accounts: QuoteReplyAccount[];
	periodDays: number;
}

interface QuoteReplyState extends QuoteReplyResponse {
	isLoading: boolean;
	hasError: boolean;
}

const EMPTY: QuoteReplyResponse = {
	fleetRatio: null,
	accounts: [],
	periodDays: 14,
};
const MIN_POSTS_PER_ACCOUNT = 3;

async function fetchRatio(
	periodDays: number,
	accountId: string | null,
): Promise<QuoteReplyResponse> {
	const params = new URLSearchParams({ periodDays: String(periodDays) });
	if (accountId) params.set("accountId", accountId);
	const response = await fetch(
		apiUrl(`/api/analytics?action=quote-reply-ratio&${params}`),
		{
			headers: await getApiAuthHeaders(),
		},
	);
	if (!response.ok) throw new Error("Failed to fetch quote-reply ratio");
	const data = (await response.json()) as QuoteReplyResponse;
	return {
		fleetRatio: data.fleetRatio ?? null,
		accounts: data.accounts ?? [],
		periodDays: data.periodDays ?? periodDays,
	};
}

async function fetchRatioFromSupabase(
	userId: string,
	periodDays: number,
	accountId: string | null,
	accountIds?: string[] | null,
): Promise<QuoteReplyResponse> {
	const since = new Date(
		Date.now() - periodDays * 24 * 60 * 60 * 1000,
	).toISOString();
	const scopedIds = accountIds?.filter(Boolean) ?? [];

	if (!accountId && Array.isArray(accountIds) && scopedIds.length === 0) {
		return { ...EMPTY, periodDays };
	}

	let postsQuery = supabase
		.from("posts")
		.select("account_id, quotes_count, replies_count")
		.eq("user_id", userId)
		.eq("platform", "threads")
		.eq("status", "published")
		.gte("published_at", since);

	if (accountId) postsQuery = postsQuery.eq("account_id", accountId);
	else if (scopedIds.length > 0)
		postsQuery = postsQuery.in("account_id", scopedIds);

	const { data: posts, error: postsError } = await postsQuery;
	if (postsError) throw postsError;

	const rows = (posts ?? []) as Array<{
		account_id: string | null;
		quotes_count: number | null;
		replies_count: number | null;
	}>;

	if (rows.length === 0) return { ...EMPTY, periodDays };

	const connectedAccounts = await queryClient.fetchQuery({
		queryKey: queryKeys.accounts.connected(userId),
		staleTime: 5 * 60_000,
		gcTime: 15 * 60_000,
		queryFn: () => fetchConnectedAccounts(userId),
	});

	const usernames = new Map(
		connectedAccounts
			.filter((account) => account.platform === "threads")
			.map(
				(account) => [account.id, account.handle.replace(/^@/, "")] as const,
			),
	);

	const byAccount = new Map<string, QuoteReplyAccount>();
	let fleetQuotes = 0;
	let fleetReplies = 0;

	for (const row of rows) {
		if (!row.account_id) continue;
		const quotes = row.quotes_count ?? 0;
		const replies = row.replies_count ?? 0;
		fleetQuotes += quotes;
		fleetReplies += replies;

		const current = byAccount.get(row.account_id) ?? {
			accountId: row.account_id,
			username: usernames.get(row.account_id) ?? null,
			ratio: null,
			quotes: 0,
			replies: 0,
			posts: 0,
		};
		current.quotes += quotes;
		current.replies += replies;
		current.posts += 1;
		byAccount.set(row.account_id, current);
	}

	const accounts = [...byAccount.values()]
		.filter(
			(a) => a.posts >= MIN_POSTS_PER_ACCOUNT || a.quotes > 0 || a.replies > 0,
		)
		.map((a) => ({
			...a,
			ratio: a.replies > 0 ? a.quotes / a.replies : null,
		}))
		.sort((a, b) => {
			const ar = a.ratio ?? -1;
			const br = b.ratio ?? -1;
			if (br !== ar) return br - ar;
			return b.replies - a.replies;
		});

	return {
		fleetRatio: fleetReplies > 0 ? fleetQuotes / fleetReplies : null,
		accounts,
		periodDays,
	};
}

/**
 * Quotes / replies per account, plus a fleet-wide ratio. Threads-only —
 * quotes_count is only populated by the Threads sync path.
 */
export function useQuoteReplyRatio(
	periodDays: number = 14,
	accountId: string | null = null,
	accountIds?: string[] | null,
): QuoteReplyState {
	const authUser = useAuthUser();
	const userKey = authUser ? authUser.id : null;
	const scopedIds = accountIds?.filter(Boolean) ?? [];
	const scopedKey = accountId
		? `one:${accountId}`
		: Array.isArray(accountIds)
			? `many:${scopedIds.slice().sort().join(",")}`
			: "all";

	const { data, isPending, isError } = useQuery<QuoteReplyResponse>({
		queryKey: ["quoteReplyRatio", userKey, periodDays, scopedKey],
		enabled: !!userKey,
		staleTime: 10 * 60 * 1000,
		refetchOnWindowFocus: false,
		queryFn: async () => {
			if (!userKey) return EMPTY;
			if (!accountId && Array.isArray(accountIds) && scopedIds.length === 0) {
				return { ...EMPTY, periodDays };
			}
			try {
				const direct = await fetchRatioFromSupabase(
					userKey,
					periodDays,
					accountId,
					accountIds,
				);
				if (direct.fleetRatio != null || direct.accounts.length > 0)
					return direct;
				if (Array.isArray(accountIds)) return direct;
			} catch (error) {
				if (Array.isArray(accountIds)) throw error;
				// Fall through to the API route so deployed environments keep the
				// existing server-side path if direct client reads are denied.
			}
			return fetchRatio(periodDays, accountId);
		},
	});

	return {
		...(data ?? EMPTY),
		isLoading: !!userKey && isPending,
		hasError: !!userKey && isError,
	};
}
