import { useQuery } from "@tanstack/react-query";
import { CalendarDays, CalendarPlus } from "lucide-react";
import { useMemo } from "react";
import {
	type ScopedAccountLite,
	toFleetPlatform,
} from "@/components/analytics/analyticsShared";
import { useAuthUser } from "@/hooks/useAuthUser";
import {
	type ConnectedAccount,
	useConnectedAccounts,
} from "@/hooks/useConnectedAccounts";
import { supabase } from "@/services/supabase";
import { Badge } from "@/components/ui/Badge";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { EvidenceTile } from "../EvidenceTile";
import { AnalyticsActionLink } from "@/components/analytics-v2/AnalyticsActionLink";
import { scopedRoute } from "@/lib/scopedRoutes";
import type { Platform } from "../shared";

interface Props {
	platform: Platform;
	days: number;
	scopedAccount?: ScopedAccountLite | null | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
}

interface CadenceCell {
	key: string;
	label: string;
	weekday: string;
	count: number;
}

interface CadenceRow {
	accountId: string;
	handle: string;
	platform: "threads" | "instagram";
	total: number;
	activeDays: number;
	cells: CadenceCell[];
}

interface CadenceData {
	rows: CadenceRow[];
	totals: CadenceCell[];
	days: number;
	totalPosts: number;
	activeAccounts: number;
	maxCell: number;
	peak: { label: string; count: number } | null;
}

interface PostRow {
	platform: string | null;
	account_id: string | null;
	instagram_account_id: string | null;
	published_at: string | null;
}

const DAY_MS = 86_400_000;
const ROW_LIMIT = 12;
const WEEKDAYS = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];

export function PostingCadenceHeatmapTile({
	platform,
	days,
	scopedAccount,
	accountIds,
	groupId,
}: Props) {
	const authUser = useAuthUser();
	const { accounts } = useConnectedAccounts();
	const cadenceDays = normalizeCadenceDays(days);
	const platformFilter = toFleetPlatform(platform);
	const accountScope = scopedAccount?.id ? scopedAccount : null;
	const accountIdsKey =
		!accountScope && accountIds && accountIds.length > 0
			? [...accountIds].sort().join(",")
			: null;
	const isAccountScope = !!accountScope;
	const scopeLabel = isAccountScope
		? "Account"
		: accountIdsKey
			? "Scope"
			: "Workspace";
	const totalLabel = `${scopeLabel} total`;
	const accountHandle = accountScope?.handle
		? accountScope.handle.startsWith("@")
			? accountScope.handle
			: `@${accountScope.handle}`
		: null;
	const accountSignature = accounts
		.map((account) => `${account.platform}:${account.id}`)
		.join("|");

	const { data, isLoading, isError } = useQuery({
		queryKey: [
			"analytics-posting-cadence",
			authUser?.id ?? null,
			platformFilter,
			cadenceDays,
			accountScope?.id ?? accountIdsKey ?? "fleet",
			groupId ?? null,
			accountSignature,
		],
		enabled: !!authUser,
		staleTime: 5 * 60_000,
		gcTime: 15 * 60_000,
		queryFn: async () => {
			if (!authUser) return buildCadenceData([], accounts, cadenceDays);
			const since = startOfLocalDay(Date.now() - (cadenceDays - 1) * DAY_MS);
			let query = supabase
				.from("posts")
				.select("platform, account_id, instagram_account_id, published_at")
				.eq("user_id", authUser.id)
				.eq("status", "published")
				.gte("published_at", since.toISOString())
				.not("published_at", "is", null)
				.order("published_at", { ascending: true })
				.limit(6000);

			if (platformFilter !== "all")
				query = query.eq("platform", platformFilter);
			if (accountScope) {
				query =
					accountScope.platform === "instagram"
						? query.eq("instagram_account_id", accountScope.id)
						: query.eq("account_id", accountScope.id);
			} else if (accountIds && accountIds.length > 0) {
				const ids = accountIds.join(",");
				query = query.or(
					`account_id.in.(${ids}),instagram_account_id.in.(${ids})`,
				);
			}

			const { data: posts, error } = await query;
			if (error) throw error;
			const postRows = (posts ?? []) as PostRow[];
			const hydratedAccounts = await hydrateHistoricalAccountLabels(
				postRows,
				accounts,
				authUser.id,
			);
			const visibleAccounts =
				!accountScope && accountIds && accountIds.length > 0
					? hydratedAccounts.filter((account) =>
							accountIds.includes(account.id),
						)
					: hydratedAccounts;
			return buildCadenceData(postRows, visibleAccounts, cadenceDays);
		},
	});

	const summary = useMemo(() => {
		const live = data;
		if (!live) return null;
		const avg = isAccountScope
			? live.totalPosts / Math.max(1, cadenceDays)
			: live.activeAccounts > 0
				? live.totalPosts / live.activeAccounts
				: 0;
		return {
			avg: `${avg.toFixed(avg >= 10 ? 0 : 1)} ${
				isAccountScope ? "posts/day" : "posts/account"
			}`,
			peak: live.peak
				? `${live.peak.label} · ${live.peak.count} post${live.peak.count === 1 ? "" : "s"}`
				: "No peak yet",
		};
	}, [data, isAccountScope, cadenceDays]);

	if (isLoading || !data) {
		return (
			<EvidenceTile
				state="loading"
				index={42}
				title={isAccountScope ? "Account cadence" : "Posting cadence"}
				hint={`${scopeLabel} day heatmap · last ${cadenceDays}d`}
				variant="heatmap"
			/>
		);
	}

	if (isError) {
		return (
			<EvidenceTile
				state="empty"
				label="Cadence"
				title={isAccountScope ? "Account cadence" : "Posting cadence"}
				note={`Posting cadence could not be computed for this ${scopeLabel.toLowerCase()}. The tile appears once published post timestamps can be read.`}
				variant="heatmap"
				statusLabel="Cadence unavailable"
			/>
		);
	}

	if (data.totalPosts === 0 || data.rows.length === 0) {
		return (
			<EvidenceTile
				state="empty"
				label="Cadence"
				title={isAccountScope ? "Account cadence" : "Posting cadence"}
				note={
					isAccountScope
						? `No published posts landed for ${accountHandle ?? "this account"} in the last ${cadenceDays} days. Once posts publish, this becomes a day-by-day cadence map.`
						: `No published posts landed in the last ${cadenceDays} days for this ${scopeLabel.toLowerCase()}. Once posts publish, this becomes an account-by-day cadence map.`
				}
				variant="heatmap"
				statusLabel="No cadence sample"
			/>
		);
	}

	return (
		<EvidenceCard
			eyebrow="Cadence"
			title={isAccountScope ? "Account cadence" : "Posting cadence"}
			description={
				isAccountScope
					? `${accountHandle ?? "Selected account"} · ${data.totalPosts.toLocaleString()} posts · last ${cadenceDays}d`
					: `${data.activeAccounts} active accounts · ${data.totalPosts.toLocaleString()} posts · last ${cadenceDays}d`
			}
			action={
				<div className="flex flex-wrap items-center justify-end gap-2">
					<AnalyticsActionLink
						to={scopedRoute(
							"/calendar",
							{ scopedAccount, accountIds, groupId, platform },
						)}
						label="Fill gaps"
						icon={CalendarPlus}
						tone="primary"
					/>
					<Badge tone="outline">
						<CalendarDays data-icon="inline-start" />
						{summary?.avg}
					</Badge>
					<Badge tone="outline">Peak {summary?.peak}</Badge>
				</div>
			}
			contentClassName="flex h-full flex-col gap-3"
		>
				<div className="analytics-cadence-shell">
					<div className="analytics-cadence-grid" data-days={cadenceDays}>
						<div className="analytics-cadence-account-head">Account</div>
						{data.totals.map((cell, index) => (
							<div
								key={cell.key}
								className="analytics-cadence-day-head"
								title={cell.label}
							>
								{index % headerStep(cadenceDays) === 0
									? shortDay(cell.label)
									: ""}
							</div>
						))}
						<div className="analytics-cadence-row-head analytics-cadence-row-head-total">
							<span>{totalLabel}</span>
							<strong>{data.totalPosts}</strong>
						</div>
						{data.totals.map((cell) => (
							<CadenceSquare
								key={cell.key}
								cell={cell}
								maxCell={data.maxCell}
								total
							/>
						))}
						{data.rows.map((row) => (
							<CadenceRowView
								key={`${row.platform}:${row.accountId}`}
								row={row}
								maxCell={data.maxCell}
							/>
						))}
					</div>
				</div>
				<div className="flex flex-wrap items-center justify-between gap-3 text-[0.6875rem] text-muted-foreground">
					<span>
						{isAccountScope
							? "Cell intensity is posts published by the selected account that day."
							: "Rows show the busiest accounts in scope. Cell intensity is posts published that day."}
					</span>
					<span className="analytics-cadence-legend">
						<span>0</span>
						<i />
						<i data-level="1" />
						<i data-level="2" />
						<i data-level="3" />
						<span>High</span>
					</span>
				</div>
		</EvidenceCard>
	);
}

function CadenceRowView({
	row,
	maxCell,
}: {
	row: CadenceRow;
	maxCell: number;
}) {
	return (
		<>
			<div className="analytics-cadence-row-head">
				<span className="truncate">{row.handle}</span>
				<small>
					{row.platform === "instagram" ? "IG" : "TH"} · {row.total} posts
				</small>
			</div>
			{row.cells.map((cell) => (
				<CadenceSquare
					key={`${row.accountId}:${cell.key}`}
					cell={cell}
					maxCell={maxCell}
				/>
			))}
		</>
	);
}

function CadenceSquare({
	cell,
	maxCell,
	total = false,
}: {
	cell: CadenceCell;
	maxCell: number;
	total?: boolean | undefined;
}) {
	const pct =
		cell.count > 0 ? Math.max(0.18, cell.count / Math.max(1, maxCell)) : 0;
	const background =
		cell.count === 0
			? "color-mix(in srgb, var(--color-foreground) 4%, transparent)"
			: `color-mix(in srgb, var(--color-oxblood) ${Math.round(18 + pct * 58)}%, transparent)`;
	return (
		<div
			className={
				total ? "analytics-cadence-cell is-total" : "analytics-cadence-cell"
			}
			style={{ background }}
			title={`${cell.label} · ${cell.count} post${cell.count === 1 ? "" : "s"}`}
			role="img"
			aria-label={`${cell.label}: ${cell.count} posts`}
		>
			{cell.count > 1 ? <span>{cell.count}</span> : null}
		</div>
	);
}

function buildCadenceData(
	posts: PostRow[],
	accounts: ConnectedAccount[],
	days: number,
): CadenceData {
	const daysList = buildDays(days);
	const cellsByKey = new Map(daysList.map((cell) => [cell.key, cell]));
	const accountById = new Map(accounts.map((account) => [account.id, account]));
	const rows = new Map<
		string,
		{
			accountId: string;
			handle: string;
			platform: "threads" | "instagram";
			counts: Map<string, number>;
		}
	>();
	const totalCounts = new Map(daysList.map((cell) => [cell.key, 0]));

	for (const post of posts) {
		if (!post.published_at) continue;
		const platform = post.platform === "instagram" ? "instagram" : "threads";
		const accountId =
			platform === "instagram" ? post.instagram_account_id : post.account_id;
		if (!accountId) continue;
		const dayKey = toDateKey(new Date(post.published_at));
		if (!cellsByKey.has(dayKey)) continue;

		const rowKey = `${platform}:${accountId}`;
		const account = accountById.get(accountId);
		const row = rows.get(rowKey) ?? {
			accountId,
			handle: account?.handle ?? "Unnamed account",
			platform,
			counts: new Map<string, number>(),
		};
		row.counts.set(dayKey, (row.counts.get(dayKey) ?? 0) + 1);
		rows.set(rowKey, row);
		totalCounts.set(dayKey, (totalCounts.get(dayKey) ?? 0) + 1);
	}

	const mappedRows = [...rows.values()]
		.map((row): CadenceRow => {
			const cells = daysList.map((day) => ({
				...day,
				count: row.counts.get(day.key) ?? 0,
			}));
			const total = cells.reduce((sum, cell) => sum + cell.count, 0);
			const activeDays = cells.filter((cell) => cell.count > 0).length;
			return { ...row, cells, total, activeDays };
		})
		.sort((a, b) => b.total - a.total || b.activeDays - a.activeDays)
		.slice(0, ROW_LIMIT);

	const totals = daysList.map((day) => ({
		...day,
		count: totalCounts.get(day.key) ?? 0,
	}));
	const totalPosts = totals.reduce((sum, cell) => sum + cell.count, 0);
	const allCounts = [
		...totals.map((cell) => cell.count),
		...mappedRows.flatMap((row) => row.cells.map((cell) => cell.count)),
	];
	const maxCell = Math.max(1, ...allCounts);
	const peakCell = totals.reduce<CadenceCell | null>(
		(best, cell) => (!best || cell.count > best.count ? cell : best),
		null,
	);

	return {
		rows: mappedRows,
		totals,
		days,
		totalPosts,
		activeAccounts: rows.size,
		maxCell,
		peak:
			peakCell && peakCell.count > 0
				? { label: peakCell.label, count: peakCell.count }
				: null,
	};
}

function normalizeCadenceDays(days: number) {
	if (days >= 90) return 90;
	if (days >= 60) return 60;
	if (days >= 30) return 30;
	if (days >= 14) return 14;
	return 7;
}

function buildDays(days: number): CadenceCell[] {
	const start = startOfLocalDay(Date.now() - (days - 1) * DAY_MS);
	return Array.from({ length: days }, (_, index) => {
		const date = new Date(start.getTime() + index * DAY_MS);
		return {
			key: toDateKey(date),
			label: date.toLocaleDateString(undefined, {
				month: "short",
				day: "numeric",
			}),
			weekday: WEEKDAYS[date.getDay()] ?? "",
			count: 0,
		};
	});
}

function startOfLocalDay(value: number) {
	const date = new Date(value);
	date.setHours(0, 0, 0, 0);
	return date;
}

function toDateKey(date: Date) {
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, "0");
	const day = String(date.getDate()).padStart(2, "0");
	return `${year}-${month}-${day}`;
}

async function hydrateHistoricalAccountLabels(
	posts: PostRow[],
	accounts: ConnectedAccount[],
	userId: string,
) {
	const known = new Set(accounts.map((account) => account.id));
	const threadIds = new Set<string>();
	const instagramIds = new Set<string>();

	for (const post of posts) {
		if (post.platform === "instagram") {
			if (post.instagram_account_id && !known.has(post.instagram_account_id)) {
				instagramIds.add(post.instagram_account_id);
			}
		} else if (post.account_id && !known.has(post.account_id)) {
			threadIds.add(post.account_id);
		}
	}

	const [threadsRes, instagramRes] = await Promise.all([
		threadIds.size > 0
			? supabase
					.from("accounts")
					.select("id, username, display_name")
					.eq("user_id", userId)
					.in("id", [...threadIds])
			: Promise.resolve({ data: [], error: null }),
		instagramIds.size > 0
			? supabase
					.from("instagram_accounts")
					.select("id, username, display_name")
					.eq("user_id", userId)
					.in("id", [...instagramIds])
			: Promise.resolve({ data: [], error: null }),
	]);

	if (threadsRes.error) throw threadsRes.error;
	if (instagramRes.error) throw instagramRes.error;

	return [
		...accounts,
		...((threadsRes.data ?? []) as AccountLabelRow[]).map((row) =>
			toConnectedAccount(row, "threads"),
		),
		...((instagramRes.data ?? []) as AccountLabelRow[]).map((row) =>
			toConnectedAccount(row, "instagram"),
		),
	];
}

interface AccountLabelRow {
	id: string;
	username: string | null;
	display_name: string | null;
}

function toConnectedAccount(
	row: AccountLabelRow,
	platform: "threads" | "instagram",
): ConnectedAccount {
	const handle = row.username ? `@${row.username}` : `@${row.id.slice(0, 8)}`;
	return {
		id: row.id,
		handle,
		displayName: row.display_name || row.username || handle,
		platform,
		groupId: null,
		groupName: "Historical",
		groupColor: "#6B6B70",
	};
}

function shortDay(label: string) {
	return label.replace(" ", "\n");
}

function headerStep(days: number) {
	if (days >= 90) return 7;
	if (days >= 60) return 5;
	return 3;
}
