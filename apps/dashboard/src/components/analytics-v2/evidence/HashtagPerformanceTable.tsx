import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Lightbulb } from "lucide-react";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { AnalyticsActionLink } from "@/components/analytics-v2/AnalyticsActionLink";
import { DataTable } from "@/components/ui/DataTable";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup";
import { scopedRoute } from "@/lib/scopedRoutes";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import {
	type HashtagPerformanceRow,
	useHashtagPerformance,
} from "@/hooks/useHashtagPerformance";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";
import { formatCompact } from "../shared";

interface Props {
	/** Window in days. */
	days?: number | undefined;
	platform?: "all" | "instagram" | "threads" | undefined;
	scopedAccount?: AccountScopeValue | null | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
}

type SortKey = "totalReach" | "avgEngagementRate" | "postCount";

/**
 * §16 Hashtag performance — sortable table of `#tags` ranked by reach (default),
 * engagement rate, or post count. v1 ships the table form deliberately —
 * a co-occurrence matrix needs a new endpoint and rarely beats a sortable
 * table for triage.
 */
export function HashtagPerformanceTable({
	days = 30,
	platform = "instagram",
	scopedAccount: scopedAccountProp,
	accountIds: accountIdsProp,
	groupId,
}: Props) {
	const storeScopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const scopedAccount =
		scopedAccountProp !== undefined ? scopedAccountProp : storeScopedAccount;
	const { accounts } = useConnectedAccounts();
	const [sortKey, setSortKey] = useState<SortKey>("totalReach");

	const accountIds = useMemo<string[] | undefined>(() => {
		if (!scopedAccount && accountIdsProp && accountIdsProp.length > 0) {
			return accountIdsProp.filter((id) => {
				const account = accounts.find((a) => a.id === id);
				if (!account) return true;
				return platform === "all" || account.platform === platform;
			});
		}
		if (!scopedAccount && groupId) return undefined;
		if (scopedAccount?.id) {
			const wantPlatform =
				platform === "instagram"
					? "instagram"
					: platform === "threads"
						? "threads"
						: null; // 'all' takes any platform
			if (wantPlatform === null || scopedAccount.platform === wantPlatform) {
				return [scopedAccount.id];
			}
			return [];
		}
		return undefined;
	}, [scopedAccount, accountIdsProp, accounts, platform, groupId]);
	const hasUnsupportedScopedPlatform = accountIds?.length === 0;

	const { data, isLoading, hasError } = useHashtagPerformance({
		accountIds: hasUnsupportedScopedPlatform ? undefined : accountIds,
		groupId,
		periodDays: days,
		platform,
		limit: 25,
		enabled: !hasUnsupportedScopedPlatform,
	});

	const sorted = useMemo(() => {
		if (!data) return [];
		const rows = [...data.hashtags];
		rows.sort((a, b) => (b[sortKey] ?? 0) - (a[sortKey] ?? 0));
		return rows.slice(0, 12);
	}, [data, sortKey]);
	const maxReach = useMemo(
		() =>
			Math.max(
				1,
				...sorted.map((row) => row.totalReach || row.totalViews || 0),
			),
		[sorted],
	);
	const columns = useMemo<ColumnDef<HashtagPerformanceRow>[]>(
		() => [
			{
				accessorKey: "hashtag",
				header: "Hashtag",
				cell: ({ row }) => (
					<span className="block truncate">#{row.original.hashtag}</span>
				),
				meta: {
					headerClassName: "analytics-col-hashtag px-6",
					cellClassName: "analytics-col-hashtag px-6 py-2 text-foreground",
				},
			},
			{
				accessorKey: "postCount",
				header: "Posts",
				meta: {
					headerClassName: "analytics-col-posts text-right",
					cellClassName:
						"analytics-col-posts px-3 py-2 text-right tabular-nums text-muted-foreground",
				},
			},
			{
				id: "reach",
				header: "Reach",
				accessorFn: (row) => row.totalReach || row.totalViews || 0,
				cell: ({ row }) => {
					const reach = row.original.totalReach || row.original.totalViews || 0;
					const reachPct = Math.max(4, Math.min(100, (reach / maxReach) * 100));
					return (
						<div className="analytics-inline-metric">
							<span>{formatCompact(reach)}</span>
							<span className="analytics-inline-bar" aria-hidden="true">
								<span style={{ width: `${reachPct}%` }} />
							</span>
						</div>
					);
				},
				meta: {
					headerClassName: "analytics-col-reach text-right",
					cellClassName:
						"analytics-col-reach px-3 py-2 text-right tabular-nums text-foreground",
				},
			},
			{
				accessorKey: "totalLikes",
				header: "Likes",
				cell: ({ row }) => formatCompact(row.original.totalLikes),
				meta: {
					headerClassName: "analytics-col-likes text-right",
					cellClassName:
						"analytics-col-likes px-3 py-2 text-right tabular-nums text-muted-foreground",
				},
			},
			{
				accessorKey: "avgEngagementRate",
				header: "Avg ER",
				cell: ({ row }) =>
					row.original.avgEngagementRate
						? `${row.original.avgEngagementRate.toFixed(2)}%`
						: "—",
				meta: {
					headerClassName: "analytics-col-er px-6 text-right",
					cellClassName:
						"analytics-col-er px-6 py-2 text-right tabular-nums text-[var(--color-gold)]",
				},
			},
		],
		[maxReach],
	);

	if (hasUnsupportedScopedPlatform) {
		return (
			<EvidenceCard
				state="empty"
				eyebrow="Hashtags"
				title="Your posts by hashtag"
				description={`Your posts · last ${days} days`}
			>
				<NovaEmpty
					className="min-h-[260px]"
					title="No hashtag data yet"
					description="Connect accounts and publish posts with hashtags to populate your own hashtag table."
				/>
			</EvidenceCard>
		);
	}

	if (hasError) {
		return (
			<EvidenceCard
				state="empty"
				eyebrow="Hashtags"
				title="Your posts by hashtag"
				description="Hashtag performance did not return for this scope."
			>
				<NovaEmpty
					className="min-h-[260px]"
					title="Hashtag table unavailable"
					description="The table appears once the endpoint can aggregate tags, reach, and engagement from your selected accounts."
				/>
			</EvidenceCard>
		);
	}

	if (isLoading || !data) {
		return (
			<EvidenceCard
				state="loading"
				eyebrow="Hashtags"
				title="Your posts by hashtag"
				description={`Your posts · last ${days} days · ${platform === "instagram" ? "Instagram" : platform === "threads" ? "Threads" : "all platforms"}`}
				contentClassName="flex min-h-[320px] flex-col gap-3"
			>
				<Skeleton className="h-8 w-64" />
				{Array.from({ length: 6 }).map((_, index) => (
					<Skeleton key={index} className="h-10 w-full" />
				))}
			</EvidenceCard>
		);
	}

	if (sorted.length === 0) {
		return (
			<EvidenceCard
				state="empty"
				eyebrow="Hashtags"
				title="Your posts by hashtag"
				description={`Your posts · last ${days} days`}
			>
				<NovaEmpty
					className="min-h-[260px]"
					title="No tagged posts"
					description={`No hashtags were found in your posts from the last ${days} days for this scope. Tagged posts will appear here with reach, post count, and engagement once they publish.`}
				/>
			</EvidenceCard>
		);
	}

	return (
		<EvidenceCard
			eyebrow="Hashtags"
			title="Your posts by hashtag"
			description={`${sorted.length} hashtags from ${data.totalPosts.toLocaleString()} of your posts · last ${days}d`}
			action={
				<div className="flex flex-wrap items-center justify-end gap-2">
					<ToggleGroup
						type="single"
						value={sortKey}
						onValueChange={(value) => {
							if (value) setSortKey(value as SortKey);
						}}
						className="rounded-md"
					>
						<ToggleGroupItem value="totalReach" sizeVariant="sm">
							Reach
						</ToggleGroupItem>
						<ToggleGroupItem value="avgEngagementRate" sizeVariant="sm">
							ER
						</ToggleGroupItem>
						<ToggleGroupItem value="postCount" sizeVariant="sm">
							Posts
						</ToggleGroupItem>
					</ToggleGroup>
					<InvestigateButton
						accountId={scopedAccount?.id ?? null}
						metric="reach"
						metricLabel="Hashtag reach"
						periodDays={days}
					/>
					<AnalyticsActionLink
						to={scopedRoute(
							"/ideas",
							{ scopedAccount, accountIds, groupId, platform, timeframe: `${days}d` },
							{ source: "rough" },
						)}
						label="Use tags"
						icon={Lightbulb}
						tone="primary"
					/>
				</div>
			}
			contentClassName="flex h-full flex-col"
		>
			<DataTable
				data={sorted}
				columns={columns}
				ariaLabel="Hashtag performance"
				className="flex-1 overflow-hidden"
				tableClassName="analytics-hashtag-table"
			/>
		</EvidenceCard>
	);
}
