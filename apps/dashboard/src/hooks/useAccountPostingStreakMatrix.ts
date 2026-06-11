import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/services/supabase";
import { useAuthUser } from "@/hooks/useAuthUser";
import {
	type ConnectedAccount,
	useConnectedAccounts,
} from "@/hooks/useConnectedAccounts";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";

export type PostingStreakPlatform = "all" | "threads" | "instagram" | "ig";

export interface PostingStreakCell {
	dateKey: string;
	day: number;
	isToday: boolean;
	isFuture: boolean;
	publishedCount: number;
	scheduledCount: number;
}

export interface AccountPostingStreakRow {
	accountId: string;
	handle: string;
	displayName: string;
	platform: "threads" | "instagram";
	groupId: string | null;
	groupName: string;
	groupColor: string;
	currentStreak: number;
	postsThisMonth: number;
	scheduledThisMonth: number;
	activeDaysThisMonth: number;
	lastPublishedAt: string | null;
	lastPublishedLabel: string;
	daysSinceLastPublished: number | null;
	needsPost: boolean;
	cells: PostingStreakCell[];
}

export interface AccountPostingStreakMatrix {
	monthKey: string;
	days: PostingStreakCell[];
	rows: AccountPostingStreakRow[];
	needsPostRows: AccountPostingStreakRow[];
	longestStreakRows: AccountPostingStreakRow[];
	zeroPostRows: AccountPostingStreakRow[];
	totalPublished: number;
	totalScheduled: number;
	isLoading: boolean;
	hasError: boolean;
}

interface Options {
	monthKey: string;
	platform?: PostingStreakPlatform | undefined;
	groupId?: string | null | undefined;
	scopedAccount?: AccountScopeValue | null | undefined;
	accountIds?: string[] | null | undefined;
	accountId?: string | null | undefined;
	accountHandle?: string | null | undefined;
}

interface PostRow {
	status: string | null;
	platform: string | null;
	account_id: string | null;
	instagram_account_id: string | null;
	published_at: string | null;
	scheduled_for: string | null;
}

const EMPTY: Omit<AccountPostingStreakMatrix, "isLoading" | "hasError"> = {
	monthKey: currentMonthKey(),
	days: [],
	rows: [],
	needsPostRows: [],
	longestStreakRows: [],
	zeroPostRows: [],
	totalPublished: 0,
	totalScheduled: 0,
};

const DAY_MS = 86_400_000;
const NEEDS_POST_HOURS = 48;
const HISTORY_LOOKBACK_DAYS = 120;

export function useAccountPostingStreakMatrix({
	monthKey,
	platform = "all",
	groupId,
	scopedAccount,
	accountIds,
	accountId,
	accountHandle,
}: Options): AccountPostingStreakMatrix {
	const authUser = useAuthUser();
	const { accounts, isLoading: accountsLoading } = useConnectedAccounts();
	const userId = authUser?.id ?? null;
	const normalizedPlatform = normalizePlatform(platform);
	const visibleAccounts = useMemo(
		() =>
			filterAccounts({
				accounts,
				platform: normalizedPlatform,
				groupId,
				scopedAccount,
				accountIds,
				accountId,
				accountHandle,
			}),
		[
			accounts,
			normalizedPlatform,
			groupId,
			scopedAccount,
			accountIds,
			accountId,
			accountHandle,
		],
	);
	const accountIdsKey = visibleAccounts
		.map((account) => account.id)
		.sort()
		.join(",");

	const { data, isPending, isError } = useQuery({
		queryKey: [
			"accountPostingStreakMatrix",
			userId,
			monthKey,
			normalizedPlatform,
			groupId ?? "all",
			scopedAccount?.id ?? null,
			(accountIds ?? []).join(","),
			accountId ?? null,
			accountHandle ?? null,
			accountIdsKey,
		],
		enabled: !!userId && !accountsLoading,
		staleTime: 2 * 60_000,
		gcTime: 10 * 60_000,
		queryFn: async () => {
			if (!userId) return { ...EMPTY, monthKey };
			const month = parseMonthKey(monthKey);
			const days = buildMonthDays(month);
			if (visibleAccounts.length === 0) {
				return buildMatrix(monthKey, days, visibleAccounts, [], []);
			}

			const monthStart = startOfMonth(month);
			const monthEnd = startOfNextMonth(month);
			const historyStart = new Date(monthStart);
			historyStart.setDate(historyStart.getDate() - HISTORY_LOOKBACK_DAYS);

			let publishedQuery = supabase
				.from("posts")
				.select(
					"status, platform, account_id, instagram_account_id, published_at, scheduled_for",
				)
				.eq("user_id", userId)
				.eq("status", "published")
				.not("published_at", "is", null)
				.gte("published_at", historyStart.toISOString())
				.lt("published_at", monthEnd.toISOString())
				.order("published_at", { ascending: true })
				.limit(10_000);

			let scheduledQuery = supabase
				.from("posts")
				.select(
					"status, platform, account_id, instagram_account_id, published_at, scheduled_for",
				)
				.eq("user_id", userId)
				.in("status", ["scheduled", "queued", "publishing"])
				.not("scheduled_for", "is", null)
				.gte("scheduled_for", monthStart.toISOString())
				.lt("scheduled_for", monthEnd.toISOString())
				.order("scheduled_for", { ascending: true })
				.limit(10_000);

			if (normalizedPlatform !== "all") {
				publishedQuery = publishedQuery.eq("platform", normalizedPlatform);
				scheduledQuery = scheduledQuery.eq("platform", normalizedPlatform);
			}

			const [publishedRes, scheduledRes] = await Promise.all([
				publishedQuery,
				scheduledQuery,
			]);
			if (publishedRes.error) throw publishedRes.error;
			if (scheduledRes.error) throw scheduledRes.error;

			return buildMatrix(
				monthKey,
				days,
				visibleAccounts,
				(publishedRes.data ?? []) as PostRow[],
				(scheduledRes.data ?? []) as PostRow[],
			);
		},
	});

	return {
		...(data ?? { ...EMPTY, monthKey, days: buildMonthDays(parseMonthKey(monthKey)) }),
		isLoading: (!!userId && isPending) || accountsLoading,
		hasError: !!userId && isError,
	};
}

export function currentMonthKey(date = new Date()): string {
	return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

export function addMonthsToKey(monthKey: string, delta: number): string {
	const month = parseMonthKey(monthKey);
	month.setMonth(month.getMonth() + delta);
	return currentMonthKey(month);
}

export function formatMonthLabel(monthKey: string): string {
	return parseMonthKey(monthKey).toLocaleDateString(undefined, {
		month: "long",
		year: "numeric",
	});
}

export function toLocalDateKey(input: string | Date): string {
	const date = typeof input === "string" ? new Date(input) : input;
	return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function isValidMonthKey(value: string | null | undefined): value is string {
	return !!value && /^\d{4}-\d{2}$/.test(value) && !Number.isNaN(parseMonthKey(value).getTime());
}

function parseMonthKey(monthKey: string): Date {
	if (!/^\d{4}-\d{2}$/.test(monthKey)) return startOfMonth(new Date());
	const [yearRaw, monthRaw] = monthKey.split("-");
	const year = Number(yearRaw);
	const month = Number(monthRaw);
	if (!Number.isFinite(year) || !Number.isFinite(month) || month < 1 || month > 12) {
		return startOfMonth(new Date());
	}
	return new Date(year, month - 1, 1);
}

function startOfMonth(date: Date): Date {
	const next = new Date(date);
	next.setDate(1);
	next.setHours(0, 0, 0, 0);
	return next;
}

function startOfNextMonth(date: Date): Date {
	const next = startOfMonth(date);
	next.setMonth(next.getMonth() + 1);
	return next;
}

function buildMonthDays(month: Date): PostingStreakCell[] {
	const start = startOfMonth(month);
	const end = startOfNextMonth(month);
	const todayKey = toLocalDateKey(new Date());
	const days: PostingStreakCell[] = [];
	for (const cursor = new Date(start); cursor < end; cursor.setDate(cursor.getDate() + 1)) {
		const key = toLocalDateKey(cursor);
		days.push({
			dateKey: key,
			day: cursor.getDate(),
			isToday: key === todayKey,
			isFuture: cursor.getTime() > Date.now(),
			publishedCount: 0,
			scheduledCount: 0,
		});
	}
	return days;
}

function normalizePlatform(platform: PostingStreakPlatform): "all" | "threads" | "instagram" {
	if (platform === "ig") return "instagram";
	return platform;
}

function filterAccounts({
	accounts,
	platform,
	groupId,
	scopedAccount,
	accountIds,
	accountId,
	accountHandle,
}: {
	accounts: ConnectedAccount[];
	platform: "all" | "threads" | "instagram";
	groupId?: string | null | undefined;
	scopedAccount?: AccountScopeValue | null | undefined;
	accountIds?: string[] | null | undefined;
	accountId?: string | null | undefined;
	accountHandle?: string | null | undefined;
}) {
	const normalizedHandle = accountHandle?.replace(/^@/, "").toLowerCase() ?? null;
	const accountIdSet = new Set(
		(accountIds ?? [])
			.map((value) => value.trim())
			.filter(Boolean)
			.map((value) => value.replace(/^@/, "").toLowerCase()),
	);
	return accounts.filter((account) => {
		if (scopedAccount) {
			return account.id === scopedAccount.id && account.platform === scopedAccount.platform;
		}
		if (
			accountIdSet.size > 0 &&
			!accountIdSet.has(account.id.toLowerCase()) &&
			!accountIdSet.has(account.handle.replace(/^@/, "").toLowerCase())
		) {
			return false;
		}
		if (accountId && account.id !== accountId) return false;
		if (normalizedHandle && account.handle.replace(/^@/, "").toLowerCase() !== normalizedHandle) {
			return false;
		}
		if (platform !== "all" && account.platform !== platform) return false;
		if (groupId && groupId !== "all") {
			const accountGroupId = account.groupId ?? "unassigned";
			if (accountGroupId !== groupId) return false;
		}
		return true;
	});
}

function buildMatrix(
	monthKey: string,
	monthDays: PostingStreakCell[],
	accounts: ConnectedAccount[],
	publishedRows: PostRow[],
	scheduledRows: PostRow[],
): Omit<AccountPostingStreakMatrix, "isLoading" | "hasError"> {
	const monthDayKeys = new Set(monthDays.map((day) => day.dateKey));
	const publishedCounts = new Map<string, number>();
	const scheduledCounts = new Map<string, number>();
	const publishedDatesByAccount = new Map<string, Set<string>>();
	const lastPublishedByAccount = new Map<string, string>();

	for (const row of publishedRows) {
		const accountId = rowAccountId(row);
		if (!accountId || !row.published_at) continue;
		const dateKey = toLocalDateKey(row.published_at);
		const accountDates = publishedDatesByAccount.get(accountId) ?? new Set<string>();
		accountDates.add(dateKey);
		publishedDatesByAccount.set(accountId, accountDates);
		lastPublishedByAccount.set(accountId, row.published_at);
		if (monthDayKeys.has(dateKey)) {
			const key = `${accountId}:${dateKey}`;
			publishedCounts.set(key, (publishedCounts.get(key) ?? 0) + 1);
		}
	}

	for (const row of scheduledRows) {
		const accountId = rowAccountId(row);
		if (!accountId || !row.scheduled_for) continue;
		const dateKey = toLocalDateKey(row.scheduled_for);
		if (!monthDayKeys.has(dateKey)) continue;
		const key = `${accountId}:${dateKey}`;
		scheduledCounts.set(key, (scheduledCounts.get(key) ?? 0) + 1);
	}

	const now = Date.now();
	const rows = accounts.map((account) => {
		const dates = publishedDatesByAccount.get(account.id) ?? new Set<string>();
		const lastPublishedAt = lastPublishedByAccount.get(account.id) ?? null;
		const daysSinceLastPublished = lastPublishedAt
			? Math.floor((startOfLocalDay(now).getTime() - startOfLocalDay(new Date(lastPublishedAt).getTime()).getTime()) / DAY_MS)
			: null;
		const cells = monthDays.map((day) => {
			const key = `${account.id}:${day.dateKey}`;
			return {
				...day,
				publishedCount: publishedCounts.get(key) ?? 0,
				scheduledCount: scheduledCounts.get(key) ?? 0,
			};
		});
		const postsThisMonth = cells.reduce((sum, cell) => sum + cell.publishedCount, 0);
		const scheduledThisMonth = cells.reduce((sum, cell) => sum + cell.scheduledCount, 0);
		const activeDaysThisMonth = cells.filter((cell) => cell.publishedCount > 0).length;
		return {
			accountId: account.id,
			handle: account.handle,
			displayName: account.displayName,
			platform: account.platform,
			groupId: account.groupId,
			groupName: account.groupName,
			groupColor: account.groupColor,
			currentStreak: computeAccountStreak(dates),
			postsThisMonth,
			scheduledThisMonth,
			activeDaysThisMonth,
			lastPublishedAt,
			lastPublishedLabel: formatLastPublished(lastPublishedAt),
			daysSinceLastPublished,
			needsPost:
				!lastPublishedAt ||
				now - new Date(lastPublishedAt).getTime() >= NEEDS_POST_HOURS * 60 * 60 * 1000,
			cells,
		};
	});

	rows.sort((a, b) => {
		if (a.needsPost !== b.needsPost) return a.needsPost ? -1 : 1;
		const aLast = a.lastPublishedAt ? Date.parse(a.lastPublishedAt) : 0;
		const bLast = b.lastPublishedAt ? Date.parse(b.lastPublishedAt) : 0;
		if (aLast !== bLast) return aLast - bLast;
		return a.handle.localeCompare(b.handle);
	});

	return {
		monthKey,
		days: monthDays,
		rows,
		needsPostRows: rows.filter((row) => row.needsPost),
		longestStreakRows: [...rows]
			.filter((row) => row.currentStreak > 0)
			.sort((a, b) => b.currentStreak - a.currentStreak || a.handle.localeCompare(b.handle))
			.slice(0, 5),
		zeroPostRows: rows.filter((row) => row.postsThisMonth === 0),
		totalPublished: rows.reduce((sum, row) => sum + row.postsThisMonth, 0),
		totalScheduled: rows.reduce((sum, row) => sum + row.scheduledThisMonth, 0),
	};
}

function rowAccountId(row: PostRow): string | null {
	return row.platform === "instagram" ? row.instagram_account_id : row.account_id;
}

function computeAccountStreak(dates: Set<string>): number {
	if (dates.size === 0) return 0;
	const cursor = startOfLocalDay(Date.now());
	const todayKey = toLocalDateKey(cursor);
	if (!dates.has(todayKey)) cursor.setDate(cursor.getDate() - 1);
	let streak = 0;
	for (let i = 0; i < HISTORY_LOOKBACK_DAYS; i += 1) {
		const key = toLocalDateKey(cursor);
		if (!dates.has(key)) break;
		streak += 1;
		cursor.setDate(cursor.getDate() - 1);
	}
	return streak;
}

function startOfLocalDay(input: number): Date {
	const date = new Date(input);
	date.setHours(0, 0, 0, 0);
	return date;
}

function formatLastPublished(iso: string | null): string {
	if (!iso) return "Never";
	const days = Math.floor(
		(startOfLocalDay(Date.now()).getTime() - startOfLocalDay(new Date(iso).getTime()).getTime()) /
			DAY_MS,
	);
	if (days <= 0) return "Today";
	if (days === 1) return "Yesterday";
	return `${days}d ago`;
}
