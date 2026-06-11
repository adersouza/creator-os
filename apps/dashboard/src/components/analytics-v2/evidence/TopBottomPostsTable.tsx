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
import {
	type TopBottomPost,
	useTopBottomPosts,
} from "@/hooks/useTopBottomPosts";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";
import { formatCompact } from "../shared";

interface Props {
	days: number;
	platform: "all" | "instagram" | "threads";
	scopedAccount?: AccountScopeValue | null | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
}

type View = "top" | "bottom";

/**
 * §15 Top / bottom posts table. Composes a direct Supabase posts-table query
 * (sort by engagement) — no new API endpoint required. Toggle between
 * top + bottom for triage. Each row includes the post permalink.
 */
export function TopBottomPostsTable({
	days,
	platform,
	scopedAccount: scopedAccountProp,
	accountIds,
	groupId,
}: Props) {
	const storeScopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const scopedAccount =
		scopedAccountProp !== undefined ? scopedAccountProp : storeScopedAccount;
	const [view, setView] = useState<View>("top");
	const scopeCopy = scopedAccount?.handle
		? scopedAccount.handle.startsWith("@")
			? scopedAccount.handle
			: `@${scopedAccount.handle}`
		: groupId
			? "selected group"
			: accountIds && accountIds.length > 0
				? `${accountIds.length} selected account${accountIds.length === 1 ? "" : "s"}`
				: "all accounts";
	const { top, bottom, isLoading, hasError } = useTopBottomPosts({
		days,
		platform,
		scopedAccount,
		accountIds,
		groupId,
		limit: 8,
	});
	const rows = view === "top" ? top : bottom;
	const maxReach = useMemo(
		() => Math.max(1, ...rows.map((post) => post.reach || post.views || 0)),
		[rows],
	);
	const maxEngagement = useMemo(
		() => Math.max(1, ...rows.map((post) => post.engagement || 0)),
		[rows],
	);
	const columns = useMemo<ColumnDef<TopBottomPost>[]>(
		() => [
			{
				accessorKey: "username",
				header: "Account",
				cell: ({ row }) => <PostAccountCell post={row.original} />,
				sortingFn: (a, b) =>
					(a.original.username ?? "").localeCompare(b.original.username ?? ""),
				meta: {
					headerClassName: "analytics-col-account px-6",
					cellClassName: "analytics-col-account px-6 py-2",
				},
			},
			{
				accessorKey: "content",
				header: "Content",
				cell: ({ row }) => (
					<div className="line-clamp-2">
						{row.original.content || "(no caption)"}
					</div>
				),
				meta: {
					headerClassName: "analytics-col-content",
					cellClassName: "analytics-col-content px-3 py-2 text-foreground",
				},
			},
			{
				id: "reach",
				header: "Reach",
				accessorFn: (post) => post.reach || post.views || 0,
				cell: ({ row }) => {
					const reach = row.original.reach || row.original.views || 0;
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
						"analytics-col-reach px-3 py-2 text-right tabular-nums text-muted-foreground",
				},
			},
			{
				accessorKey: "engagement",
				header: "Engagement",
				cell: ({ row }) => {
					const engagementPct = Math.max(
						4,
						Math.min(100, ((row.original.engagement || 0) / maxEngagement) * 100),
					);
					return (
						<div className="analytics-inline-metric">
							<span>{formatCompact(row.original.engagement)}</span>
							<span
								className="analytics-inline-bar analytics-inline-bar-gold"
								aria-hidden="true"
							>
								<span style={{ width: `${engagementPct}%` }} />
							</span>
						</div>
					);
				},
				meta: {
					headerClassName: "analytics-col-engagement text-right",
					cellClassName:
						"analytics-col-engagement px-3 py-2 text-right tabular-nums text-foreground",
				},
			},
			{
				accessorKey: "engagementRate",
				header: "ER",
				cell: ({ row }) => <EngagementRateCell post={row.original} view={view} />,
				sortUndefined: "last",
				meta: {
					headerClassName: "analytics-col-er px-6 text-right",
					cellClassName: "analytics-col-er px-6 py-2 text-right tabular-nums",
				},
			},
		],
		[maxEngagement, maxReach, view],
	);

	if (isLoading && rows.length === 0) {
		return (
			<EvidenceCard
				state="loading"
				title="Top + bottom posts"
				description={`Last ${days}d · ranked by engagement`}
			>
				<div className="flex flex-col gap-3" role="status" aria-label="Loading top and bottom posts">
					<Skeleton className="h-9 w-full rounded-lg" />
					<Skeleton className="h-9 w-full rounded-lg" />
					<Skeleton className="h-9 w-4/5 rounded-lg" />
				</div>
			</EvidenceCard>
		);
	}

	if (hasError && top.length === 0 && bottom.length === 0) {
		return (
			<EvidenceCard
				state="empty"
				eyebrow="Posts"
				title="Top + bottom posts"
			>
				<NovaEmpty
					title="Post ranking unavailable"
					description="The post-ranking query did not return a usable payload. The table will stay empty until published posts with reach and engagement metrics are available."
				/>
			</EvidenceCard>
		);
	}

	if (top.length === 0 && bottom.length === 0) {
		return (
			<EvidenceCard
				state="empty"
				eyebrow="Posts"
				title="Top + bottom posts"
				description={`No posts in ${scopeCopy}`}
			>
				<NovaEmpty
					title="No posts in this window"
					description={`No published posts landed in the last ${days} days for ${scopeCopy}. The table fills as soon as posts publish with reach and engagement metrics.`}
				/>
			</EvidenceCard>
		);
	}

	return (
		<EvidenceCard
			title="Top + bottom posts"
			description={`Last ${days}d · sort by engagement (likes + comments + saves + shares)`}
			action={
				<div className="flex flex-wrap items-center justify-end gap-2">
					<InvestigateButton
						accountId={scopedAccount?.id ?? rows[0]?.accountId ?? null}
						metric="engagement"
						metricLabel={`${view === "top" ? "Top" : "Bottom"} posts`}
						periodDays={days}
					/>
					<AnalyticsActionLink
						to={scopedRoute(
							"/ideas",
							{
								scopedAccount,
								accountIds,
								groupId,
								platform,
								timeframe: `${days}d`,
							},
							{ source: "rough" },
						)}
						label={view === "top" ? "Remix winner" : "Fix weak post"}
						icon={Lightbulb}
						tone={view === "top" ? "primary" : "neutral"}
					/>
					<ToggleGroup
						type="single"
						value={view}
						onValueChange={(value) => {
							if (value === "top" || value === "bottom") setView(value);
						}}
						aria-label="Post ranking view"
					>
						<ToggleGroupItem value="top" sizeVariant="sm">
							Top
						</ToggleGroupItem>
						<ToggleGroupItem value="bottom" sizeVariant="sm">
							Bottom
						</ToggleGroupItem>
					</ToggleGroup>
				</div>
			}
			contentClassName="flex min-h-0 flex-1 flex-col p-0"
		>
			<DataTable
				data={rows}
				columns={columns}
				ariaLabel="Top and bottom posts"
				className="flex-1 overflow-hidden"
				tableClassName="analytics-post-table"
				isRowInteractive={(post) => !!post.permalink}
				onRowClick={(post) => {
					if (post.permalink) window.open(post.permalink, "_blank", "noopener");
				}}
				rowClassName={(post) =>
					post.permalink
						? "hover:bg-[color-mix(in_srgb,var(--color-foreground)_3%,transparent)]"
						: undefined
				}
			/>
		</EvidenceCard>
	);
}

function PostAccountCell({ post }: { post: TopBottomPost }) {
	return (
		<div className="flex flex-col gap-0.5">
			<span className="text-foreground">@{post.username ?? "—"}</span>
			<span className="text-[0.625rem] text-muted-foreground uppercase tracking-[0.04em]">
				{post.platform}
			</span>
		</div>
	);
}

function EngagementRateCell({ post, view }: { post: TopBottomPost; view: View }) {
	const er = post.engagementRate ?? 0;
	const erTone =
		view === "bottom" || er < 1
			? "var(--color-critical)"
			: er > 5
				? "var(--color-health-good)"
				: "var(--color-warning)";

	return (
		<span style={{ color: erTone }}>{er > 0 ? `${er.toFixed(2)}%` : "—"}</span>
	);
}
