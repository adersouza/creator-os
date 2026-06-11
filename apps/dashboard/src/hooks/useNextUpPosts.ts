import { useQuery } from "@tanstack/react-query";
import { useAuthUser } from "@/hooks/useAuthUser";
import { supabase } from "@/services/supabase";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";

type ScopePlatform = "all" | "threads" | "ig";
type ScopeTimeframe = "7" | "30" | "90";

export interface NextUpItem {
	id: string;
	scheduledAt: string | null;
	time: string;
	text: string;
	handle: string;
	platform: "threads" | "instagram";
	groupName: string;
	groupColor: string;
	isAccent: boolean;
}

interface NextUpState {
	items: NextUpItem[];
	totalQueue: number;
	isLoading: boolean;
	hasError: boolean;
}

const UNASSIGNED_COLOR = "#6B6B70";
const MAX_ROWS = 3;

const WINDOW_MINUTES: Record<ScopeTimeframe, number> = {
	"7": 60,
	"30": 120,
	"90": 180,
};

const EMPTY: Omit<NextUpState, "isLoading" | "hasError"> = {
	items: [],
	totalQueue: 0,
};

interface NextUpRpcItem {
	id: string;
	content: string | null;
	scheduled_for: string | null;
	platform: "threads" | "instagram";
	username: string | null;
	group_name: string | null;
	group_color: string | null;
}

interface NextUpRpcPayload {
	items: NextUpRpcItem[];
	totalQueue: number;
}

/**
 * Next scheduled posts in the upcoming N-minute window via
 * `get_next_up_posts` RPC. 5 queries + 2 sequential JS joins → 1 RPC.
 * Client still formats the `time` label (locale-dependent HH:mm) and
 * assigns the accent row.
 */
export function useNextUpPosts(
	platform: ScopePlatform = "all",
	timeframe: ScopeTimeframe = "7",
	scopedAccount: AccountScopeValue | null = null,
	accountIds?: string[],
	groupId?: string | null,
): NextUpState {
	const authUser = useAuthUser();
	const userKey = authUser ? authUser.id : null;

	const { data, isPending, isError } = useQuery({
		queryKey: [
			"nextUpPosts",
			userKey,
			platform,
			timeframe,
			scopedAccount?.id ?? null,
			scopedAccount?.handle ?? null,
			scopedAccount?.platform ?? null,
			groupId ?? "all",
			accountIds?.join(",") ?? null,
		],
		enabled: !!userKey,
		queryFn: async () => {
			const { data, error } = await supabase.rpc("get_next_up_posts", {
				p_platform: platform,
				p_window_minutes: WINDOW_MINUTES[timeframe],
				p_limit: MAX_ROWS,
				p_scoped_account_id: scopedAccount?.id ?? null,
				p_scoped_platform: scopedAccount?.platform ?? null,
				p_account_ids:
					!scopedAccount && accountIds && accountIds.length > 0
						? accountIds
						: null,
			});
			if (error) {
				return EMPTY;
			}
			if (!data) return EMPTY;
			const payload = data as NextUpRpcPayload;
			const now = new Date();
			const items: NextUpItem[] = (payload.items ?? []).map((row, idx) => {
				const scheduledAt = row.scheduled_for
					? new Date(row.scheduled_for)
					: now;
				const time = scheduledAt.toLocaleTimeString([], {
					hour: "2-digit",
					minute: "2-digit",
					hour12: false,
				});
				return {
					id: row.id,
					scheduledAt: row.scheduled_for,
					time,
					text: row.content ?? "",
					handle: row.username ? `@${row.username}` : "Unnamed account",
					platform: row.platform,
					groupName: row.group_name ?? "Unassigned",
					groupColor: row.group_color ?? UNASSIGNED_COLOR,
					isAccent: idx === 0,
				};
			});
			return {
				items,
				totalQueue: payload.totalQueue ?? 0,
			};
		},
	});

	return {
		...(data ?? EMPTY),
		isLoading: !!userKey && isPending,
		hasError: !!userKey && isError,
	};
}
