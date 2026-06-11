import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/services/supabase";
import { useAuthUser } from "@/hooks/useAuthUser";
import { queryKeys } from "@/lib/queryKeys";

export interface ConnectedAccount {
	id: string;
	handle: string;
	displayName: string;
	platform: "threads" | "instagram";
	groupId: string | null;
	groupName: string;
	groupColor: string;
	isEligibleForGeoGating?: boolean;
}

interface State {
	accounts: ConnectedAccount[];
	isLoading: boolean;
	hasError: boolean;
}

const UNASSIGNED_COLOR_LIGHT = "#6B6B70";
const CONNECTED_ACCOUNTS_TTL_MS = 30_000;
const connectedAccountsCache = new Map<
	string,
	{ expiresAt: number; value: ConnectedAccount[] }
>();
const connectedAccountsInFlight = new Map<
	string,
	Promise<ConnectedAccount[]>
>();

export async function fetchConnectedAccounts(
	userId: string,
): Promise<ConnectedAccount[]> {
	const cached = connectedAccountsCache.get(userId);
	if (cached && cached.expiresAt > Date.now()) return cached.value;
	if (cached) connectedAccountsCache.delete(userId);

	const existing = connectedAccountsInFlight.get(userId);
	if (existing) return existing;

	const request = readConnectedAccounts(userId)
		.then((value) => {
			connectedAccountsCache.set(userId, {
				expiresAt: Date.now() + CONNECTED_ACCOUNTS_TTL_MS,
				value,
			});
			return value;
		})
		.finally(() => {
			if (connectedAccountsInFlight.get(userId) === request) {
				connectedAccountsInFlight.delete(userId);
			}
		});
	connectedAccountsInFlight.set(userId, request);
	return request;
}

const THREADS_COLUMNS_FULL =
	"id, username, display_name, group_id, is_eligible_for_geo_gating";
const THREADS_COLUMNS_FALLBACK = "id, username, display_name, group_id";

type ConnectedAccountRow = {
	id: string;
	username: string | null;
	display_name: string | null;
	group_id: string | null;
	is_eligible_for_geo_gating?: boolean | null;
};

function isConnectedAccountRow(row: unknown): row is ConnectedAccountRow {
	if (!row || typeof row !== "object") return false;
	const candidate = row as Partial<Record<keyof ConnectedAccountRow, unknown>>;
	return typeof candidate.id === "string";
}

function filterConnectedAccountRows(
	rows: readonly unknown[] | null | undefined,
): ConnectedAccountRow[] {
	return rows?.filter(isConnectedAccountRow) ?? [];
}

async function selectThreadsAccounts(userId: string) {
	const baseQuery = (columns: string) =>
		supabase
			.from("accounts")
			.select(columns)
			.eq("user_id", userId)
			.eq("is_retired", false);

	const full = await baseQuery(THREADS_COLUMNS_FULL);
	if (!full.error) return full;
	// 42703 = undefined_column. Retry without the optional column so the UI
	// still renders if a stale schema is missing it.
	if ((full.error as { code?: string } | null)?.code === "42703") {
		return baseQuery(THREADS_COLUMNS_FALLBACK);
	}
	return full;
}

async function readConnectedAccounts(
	userId: string,
): Promise<ConnectedAccount[]> {
	const [threadsRes, igRes, groupsRes] = await Promise.all([
		selectThreadsAccounts(userId),
		supabase
			.from("instagram_accounts")
			.select("id, username, display_name, group_id")
			.eq("user_id", userId),
		supabase
			.from("account_groups")
			.select("id, name, color")
			.eq("user_id", userId),
	]);

	if (threadsRes.error) throw threadsRes.error;
	if (igRes.error) throw igRes.error;
	if (groupsRes.error) throw groupsRes.error;

	const groupsById = new Map<string, { name: string; color: string }>();
	for (const g of groupsRes.data ?? []) {
		groupsById.set(g.id, {
			name: g.name,
			color: g.color || UNASSIGNED_COLOR_LIGHT,
		});
	}

	const normalize = (
		rows: ConnectedAccountRow[],
		platform: "threads" | "instagram",
	): ConnectedAccount[] =>
		rows.map((row) => {
			const group = row.group_id ? groupsById.get(row.group_id) : null;
			const fallbackLabel =
				platform === "threads"
					? "Unnamed Threads account"
					: "Unnamed Instagram account";
			const handle = row.username ? `@${row.username}` : fallbackLabel;
			const displayName = row.display_name || row.username || fallbackLabel;
			return {
				id: row.id,
				handle,
				displayName,
				platform,
				groupId: row.group_id,
				groupName: group?.name ?? "Unassigned",
				groupColor: group?.color ?? UNASSIGNED_COLOR_LIGHT,
				...(platform === "threads"
					? { isEligibleForGeoGating: row.is_eligible_for_geo_gating === true }
					: {}),
			};
		});

	return [
		...normalize(filterConnectedAccountRows(threadsRes.data as unknown[]), "threads"),
		...normalize(filterConnectedAccountRows(igRes.data as unknown[]), "instagram"),
	];
}

export function useConnectedAccounts(): State {
	const authUser = useAuthUser();
	const userKey = authUser ? authUser.id : null;

	const { data, isPending, isError } = useQuery({
		queryKey: queryKeys.accounts.connected(userKey),
		enabled: !!userKey,
		// Account list rarely changes; skip refetches that fire on every mount
		// when this hook is consumed by sidebar/composer/settings simultaneously.
		staleTime: 5 * 60_000,
		gcTime: 15 * 60_000,
		queryFn: async (): Promise<ConnectedAccount[]> => {
			const {
				data: { user },
			} = await supabase.auth.getUser();
			if (!user) return [];
			return fetchConnectedAccounts(user.id);
		},
	});

	return {
		accounts: data ?? [],
		isLoading: !!userKey && isPending,
		hasError: !!userKey && isError,
	};
}
