import { useQuery } from "@tanstack/react-query";
import { useAuthUser } from "@/hooks/useAuthUser";
import { getApiAuthHeaders } from "@/lib/apiAuth";
import { apiUrl } from "@/lib/apiUrl";
import { supabase } from "@/services/supabase";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";

export interface ReplyChainItem {
	id: string;
	replied_to: string | null;
	timestamp: number;
	username: string | null;
	text: string | null;
}

export interface ReplyDepthLeader {
	id: string;
	content: string | null;
	publishedAt: string;
	permalink: string | null;
	replyDepth: number;
	replies: number;
	quotes: number;
	reposts: number;
	score: number;
	accountId: string | null;
	accountUsername?: string | null | undefined;
	accountAvatarUrl?: string | null | undefined;
	creatorRepliesCount?: number | null | undefined;
	// Populated only for the top leader. Powers the velocity histogram
	// (ConvWinner tile) and the text-bearing reply tree (ConvQuality tile).
	velocityHistogram?: number[] | null | undefined;
	velocityWindowHours?: number | null | undefined;
	replyChain?: ReplyChainItem[] | null | undefined;
}

interface ReplyDepthResponse {
	leaders: ReplyDepthLeader[];
	periodDays: number;
}

interface ReplyDepthState extends ReplyDepthResponse {
	isLoading: boolean;
	hasError: boolean;
}

const EMPTY: ReplyDepthResponse = { leaders: [], periodDays: 14 };

async function fetchLeaders(
	periodDays: number,
	accountId: string | null,
	accountIds?: string[],
): Promise<ReplyDepthResponse> {
	const params = new URLSearchParams({ periodDays: String(periodDays) });
	if (accountId) params.set("accountId", accountId);
	if (!accountId && accountIds && accountIds.length > 0)
		params.set("accountIds", accountIds.join(","));
	const response = await fetch(
		apiUrl(`/api/analytics?action=reply-depth-leaders&${params}`),
		{
			headers: await getApiAuthHeaders(),
		},
	);
	if (!response.ok) throw new Error("Failed to fetch reply-depth leaders");
	const data = (await response.json()) as ReplyDepthResponse;
	return {
		leaders: data.leaders ?? [],
		periodDays: data.periodDays ?? periodDays,
	};
}

async function fetchPostBackedLeaders(
	userId: string,
	periodDays: number,
	accountId: string | null,
	accountIds?: string[],
): Promise<ReplyDepthResponse> {
	const since = new Date();
	since.setDate(since.getDate() - periodDays);
	since.setHours(0, 0, 0, 0);

	let query = supabase
		.from("posts")
		.select(
			"id, content, published_at, permalink, reply_depth, replies_count, quotes_count, reposts_count, account_id, reply_chain",
		)
		.eq("user_id", userId)
		.eq("platform", "threads")
		.eq("status", "published")
		.gt("reply_depth", 1)
		.gte("published_at", since.toISOString());
	if (accountId) query = query.eq("account_id", accountId);
	else if (accountIds && accountIds.length > 0)
		query = query.in("account_id", accountIds);

	const { data: posts, error } = await query;
	if (error) throw error;

	const metaAccountIds = Array.from(
		new Set(
			((posts ?? []) as Array<{ account_id: string | null }>)
				.map((post) => post.account_id)
				.filter((id): id is string => !!id),
		),
	);

	const accountMetaById = new Map<
		string,
		{ username: string | null; avatarUrl: string | null }
	>();
	if (metaAccountIds.length > 0) {
		const { data: accounts } = await supabase
			.from("accounts")
			.select("id, username, avatar_url")
			.in("id", metaAccountIds);
		for (const account of (accounts ?? []) as Array<{
			id: string;
			username: string | null;
			avatar_url: string | null;
		}>) {
			accountMetaById.set(account.id, {
				username: account.username,
				avatarUrl: account.avatar_url,
			});
		}
	}

	const leaders = (
		(posts ?? []) as Array<{
			id: string;
			content: string | null;
			published_at: string;
			permalink: string | null;
			reply_depth: number | null;
			replies_count: number | null;
			quotes_count: number | null;
			reposts_count: number | null;
			account_id: string | null;
			reply_chain: ReplyChainItem[] | null;
		}>
	)
		.map((post) => {
			const replyDepth = post.reply_depth || 0;
			const replies = post.replies_count || 0;
			return {
				id: post.id,
				content: post.content,
				publishedAt: post.published_at,
				permalink: post.permalink,
				replyDepth,
				replies,
				quotes: post.quotes_count || 0,
				reposts: post.reposts_count || 0,
				score: replyDepth * Math.max(1, replies),
				accountId: post.account_id,
				accountUsername: post.account_id
					? (accountMetaById.get(post.account_id)?.username ?? null)
					: null,
				accountAvatarUrl: post.account_id
					? (accountMetaById.get(post.account_id)?.avatarUrl ?? null)
					: null,
				replyChain: post.reply_chain ?? null,
				velocityHistogram: null,
				velocityWindowHours: null,
				creatorRepliesCount: null,
			};
		})
		.sort((a, b) => b.score - a.score)
		.slice(0, 8);

	return { leaders, periodDays };
}

/**
 * Threads posts ranked by reply_depth × replies_count — the "long
 * conversation" leaderboard. Threads-only.
 */
export function useReplyDepthLeaders(
	periodDays: number = 14,
	scopedAccount: AccountScopeValue | null = null,
	accountIds?: string[],
	groupId?: string | null,
): ReplyDepthState {
	const authUser = useAuthUser();
	const userKey = authUser ? authUser.id : null;
	const accountId =
		scopedAccount?.platform === "threads" ? scopedAccount.id : null;

	const { data, isPending, isError } = useQuery<ReplyDepthResponse>({
		queryKey: [
			"replyDepthLeaders",
			userKey,
			periodDays,
			accountId ?? "fleet",
			groupId ?? "all",
			accountIds?.join(",") ?? null,
		],
		enabled: !!userKey,
		staleTime: 10 * 60 * 1000,
		refetchOnWindowFocus: false,
		queryFn: async () => {
			const postBacked = await fetchPostBackedLeaders(
				userKey as string,
				periodDays,
				accountId,
				accountIds,
			);
			if (postBacked.leaders.length > 0) return postBacked;
			return fetchLeaders(periodDays, accountId, accountIds).catch(
				() => postBacked,
			);
		},
	});

	return {
		...(data ?? EMPTY),
		isLoading: !!userKey && isPending,
		hasError: !!userKey && isError,
	};
}
