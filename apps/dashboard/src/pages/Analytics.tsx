import { useEffect, useMemo, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { ColumnDef } from "@tanstack/react-table";
import {
	ArrowUpRight,
	BarChart3,
	Bookmark,
	Download,
	GitCompareArrows,
	MapPin,
	MessageCircle,
	RefreshCw,
	Share2,
	Sparkles,
	TrendingUp,
	UserRound,
	Users,
} from "lucide-react";
import { SmartLinksAnalytics } from "@/components/analytics/widgets/system/SmartLinksAnalytics";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { DataTable } from "@/components/ui/DataTable";
import {
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuRoot,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/DropdownMenu";
import { JunoBarChart } from "@/components/ui/JunoChart";
import {
	NovaCard,
	NovaDataPanel,
	NovaEmpty,
	NovaHeader,
	NovaListRow,
	NovaMiniStat,
	NovaSection,
	NovaStat,
} from "@/components/ui/NovaPrimitives";
import { PillSegmented } from "@/components/ui/PillSegmented";
import { Separator } from "@/components/ui/Separator";
import { Skeleton } from "@/components/ui/Skeleton";
import {
	Tabs,
	TabsContent,
	TabsList,
	TabsTrigger,
} from "@/components/ui/Tabs";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import {
	useFleetKpiData,
	type FleetKpiPlatform,
} from "@/hooks/useFleetKpiData";
import {
	useFleetMetrics,
	type FleetAccountAggregate,
} from "@/hooks/useFleetMetrics";
import {
	useTopBottomPosts,
	type TopBottomPost,
} from "@/hooks/useTopBottomPosts";
import {
	useTopPosts,
	type TopPostRow,
	type TopPostsPlatform,
} from "@/hooks/useTopPosts";
import { useSelectedGroupAccountIds } from "@/hooks/useSelectedGroupAccountIds";
import { useAudienceDemographics } from "@/hooks/useAudienceDemographics";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import {
	buildAccountAggregatesCsv,
	buildDailySeriesCsv,
	buildKpiSnapshotCsv,
	downloadCsv,
} from "@/services/analyticsCsv";
import {
	dateRangeLabel,
	dateRangeToDays,
	type AnalyticsCompareMode,
	type AnalyticsPlatform,
	type AnalyticsTab,
	useAnalyticsUrlState,
} from "@/lib/analyticsUrlState";
import {
	buildContentOperations,
	discoveryScore,
	engagementTotal,
} from "@/lib/contentOperations";
import { calendarPostPath } from "@/lib/deepLinks";

type AnalyticsPlatformUi = "all" | "threads" | "ig";

const PLATFORM_OPTIONS: Array<{ id: AnalyticsPlatformUi; label: string }> = [
	{ id: "all", label: "Fleet" },
	{ id: "threads", label: "Threads" },
	{ id: "ig", label: "Instagram" },
];

const RANGE_OPTIONS: Array<{
	id: "7d" | "14d" | "30d" | "90d";
	label: string;
}> = [
	{ id: "7d", label: "7D" },
	{ id: "14d", label: "14D" },
	{ id: "30d", label: "30D" },
	{ id: "90d", label: "90D" },
];

const ANALYTICS_TABS: Array<{ id: AnalyticsTab; label: string }> = [
	{ id: "overview", label: "Overview" },
	{ id: "posts", label: "Posts" },
	{ id: "accounts", label: "Accounts" },
	{ id: "audience", label: "Audience" },
	{ id: "links", label: "Links" },
	{ id: "compare", label: "Compare" },
];

const COMPARE_OPTIONS: Array<{ id: AnalyticsCompareMode; label: string }> = [
	{ id: "prev", label: "Prior period" },
	{ id: "year", label: "Year ago" },
	{ id: "peer", label: "Peer set" },
	{ id: "cohort", label: "Cohort" },
	{ id: "off", label: "Off" },
];

function toFleetPlatform(platform: AnalyticsPlatform): FleetKpiPlatform {
	return platform === "ig" ? "instagram" : platform;
}

function toTopBottomPlatform(
	platform: AnalyticsPlatform,
): "all" | "threads" | "instagram" {
	return platform === "ig" ? "instagram" : platform;
}

function formatCompact(value: number | null | undefined) {
	const safeValue = Number(value ?? 0);
	return new Intl.NumberFormat("en", {
		notation: "compact",
		maximumFractionDigits: safeValue >= 1000 ? 1 : 0,
	}).format(safeValue);
}

function formatPercent(value: number | null | undefined) {
	if (value == null || Number.isNaN(value)) return "Pending";
	return `${Math.round(value * 10) / 10}%`;
}

function formatAvailablePercent(value: number | null | undefined) {
	if (value == null || Number.isNaN(value)) return "Unavailable";
	return `${Math.round(value * 10) / 10}%`;
}

function formatDelta(value: number | null | undefined) {
	if (value == null || Number.isNaN(value)) return "No prior";
	const rounded = Math.round(value * 10) / 10;
	return `${rounded > 0 ? "+" : ""}${rounded}%`;
}

function deltaDirection(
	value: number | null | undefined,
): "up" | "down" | "flat" {
	if (value == null || Math.abs(value) < 0.1) return "flat";
	return value > 0 ? "up" : "down";
}

function postIsReadyForReview(post: TopBottomPost) {
	return isMaturePublishedAt(post.publishedAt);
}

function isMaturePublishedAt(value: string) {
	const publishedAt = new Date(value).getTime();
	if (!Number.isFinite(publishedAt)) return false;
	return Date.now() - publishedAt >= 72 * 60 * 60 * 1000;
}

function formatPostTitle(post: TopBottomPost) {
	const compact = post.content.replace(/\s+/g, " ").trim();
	return compact || "Untitled post";
}

function accountEngagement(account: FleetAccountAggregate) {
	return account.likes + account.comments + account.sends + account.saves;
}

function topPostEngagementRate(post: TopPostRow) {
	if (post.reach <= 0) return null;
	return Math.round((engagementTotal(post) / post.reach) * 10000) / 100;
}

function topPostNeedsReview(post: TopPostRow, reviewThreshold: number) {
	return isMaturePublishedAt(post.publishedAt) && post.reach < reviewThreshold;
}

function formatPublishedAt(value: string) {
	if (!value) return "Published";
	return new Intl.DateTimeFormat(undefined, {
		month: "short",
		day: "numeric",
		hour: "numeric",
		minute: "2-digit",
	}).format(new Date(value));
}

function topPostPlatformLabel(post: TopPostRow) {
	return post.platform === "instagram" ? "Instagram" : "Threads";
}

function topPostPlatformLogo(post: TopPostRow) {
	return post.platform === "instagram" ? "instagram" : "threads";
}

function previousFromDelta(current: number, delta: number | null | undefined) {
	if (delta == null || Number.isNaN(delta)) return null;
	const denominator = 1 + delta / 100;
	if (denominator <= 0) return null;
	return current / denominator;
}

function previousFromPointDelta(
	current: number | null | undefined,
	delta: number | null | undefined,
) {
	if (current == null || delta == null || Number.isNaN(delta)) return null;
	return current - delta;
}

function platformLabel(platform: "threads" | "instagram") {
	return platform === "instagram" ? "Instagram" : "Threads";
}

function accountEngagementRate(account: FleetAccountAggregate) {
	if (account.reach <= 0) return null;
	return Math.round((accountEngagement(account) / account.reach) * 10000) / 100;
}

function aggregatePlatformAccounts(accounts: FleetAccountAggregate[]) {
	return (["threads", "instagram"] as const).map((platform) => {
		const rows = accounts.filter((account) => account.platform === platform);
		const reach = rows.reduce((sum, account) => sum + account.reach, 0);
		const posts = rows.reduce((sum, account) => sum + account.posts, 0);
		const engagements = rows.reduce(
			(sum, account) => sum + accountEngagement(account),
			0,
		);
		return {
			platform,
			reach,
			posts,
			engagements,
			engagementRate:
				reach > 0 ? Math.round((engagements / reach) * 10000) / 100 : null,
		};
	});
}

export function Analytics() {
	const { accounts } = useConnectedAccounts();
	const [searchParams, setSearchParams] = useSearchParams();
	const scopedAccount = useAccountScopeStore((state) => state.scopedAccount);
	const setAccountScope = useAccountScopeStore((state) => state.setScope);
	const setSelectedGroupId = useWorkspaceStore(
		(state) => state.setSelectedGroupId,
	);
	const { accountIds: scopedGroupAccountIds, groupId: scopedGroupId } =
		useSelectedGroupAccountIds(scopedAccount);
	const [state, updateState] = useAnalyticsUrlState();
	const days = dateRangeToDays(state.dateRange);
	const fleetPlatform = toFleetPlatform(state.platform);
	const timeRange =
		state.dateRange.kind === "preset" ? state.dateRange.preset : { days };
	const fleetMetrics = useFleetMetrics(
		timeRange,
		fleetPlatform,
		scopedAccount,
		{ accountIds: scopedGroupAccountIds, groupId: scopedGroupId },
	);
	const kpiData = useFleetKpiData(
		timeRange,
		fleetPlatform,
		scopedAccount,
		scopedGroupAccountIds,
		scopedGroupId,
	);
	const topBottomPosts = useTopBottomPosts({
		days,
		platform: toTopBottomPlatform(state.platform),
		scopedAccount,
		accountIds: scopedGroupAccountIds,
		groupId: scopedGroupId,
		limit: 5,
	});
	const analyticsPosts = useTopPosts(
		timeRange,
		state.platform as TopPostsPlatform,
		scopedAccount,
		scopedGroupAccountIds,
		scopedGroupId,
	);
	const audienceDemographics = useAudienceDemographics(scopedAccount?.id ?? null);

	useEffect(() => {
		const accountId = searchParams.get("accountId");
		const groupId = searchParams.get("group");
		let consumed = false;

		if (accountId) {
			const account = accounts.find((row) => row.id === accountId);
			if (account) {
				setAccountScope({
					id: account.id,
					handle: account.handle,
					platform: account.platform,
				});
				consumed = true;
			}
		} else if (groupId) {
			setAccountScope(null);
			setSelectedGroupId(groupId);
			consumed = true;
		}

		if (consumed) {
			const cleaned = new URLSearchParams(searchParams);
			cleaned.delete("accountId");
			cleaned.delete("account");
			cleaned.delete("group");
			cleaned.delete("accounts");
			cleaned.delete("platform");
			cleaned.delete("timeframe");
			setSearchParams(cleaned, { replace: true });
		}
	}, [
		accounts,
		searchParams,
		setAccountScope,
		setSearchParams,
		setSelectedGroupId,
	]);

	const scopeLabel = scopedAccount ? `@${scopedAccount.handle}` : "Fleet";
	const recentSeries = fleetMetrics.series.slice(-14);
	const maxReach = Math.max(1, ...recentSeries.map((point) => point.reach || 0));
	const topAccounts = fleetMetrics.accounts.slice(0, 10);
	const bestPosts = topBottomPosts.top.slice(0, 3);
	const reviewPosts = topBottomPosts.bottom.filter(postIsReadyForReview).slice(0, 3);
	const platformComparison = useMemo(
		() => aggregatePlatformAccounts(fleetMetrics.accounts),
		[fleetMetrics.accounts],
	);
	const accountMovers = useMemo(
		() =>
			[...fleetMetrics.accounts]
				.filter(
					(account) =>
						account.posts > 0 &&
						(account.reach > 0 || account.followerGrowthPct != null),
				)
				.sort((a, b) => {
					const aDelta = a.reachDeltaPct ?? Number.NEGATIVE_INFINITY;
					const bDelta = b.reachDeltaPct ?? Number.NEGATIVE_INFINITY;
					return bDelta - aDelta;
				})
				.slice(0, 5),
		[fleetMetrics.accounts],
	);
	const contentOperations = useMemo(
		() => buildContentOperations(analyticsPosts.posts),
		[analyticsPosts.posts],
	);
	const views = kpiData.reach || fleetMetrics.totalReach;
	const viewsDelta = kpiData.reachDelta ?? fleetMetrics.reachDeltaPct;
	const engagementRate =
		views > 0
			? Math.round((kpiData.totalInteractions / views) * 10000) / 100
			: null;
	const comparisonRows = useMemo(
		() => [
			{
				label: "Views",
				current: formatCompact(views),
				previous: formatCompact(previousFromDelta(views, viewsDelta)),
				delta: viewsDelta,
				description: "Reach-backed views for the selected window.",
			},
			{
				label: "Engagements",
				current: formatCompact(kpiData.totalInteractions),
				previous: formatCompact(
					previousFromDelta(
						kpiData.totalInteractions,
						kpiData.totalInteractionsDelta,
					),
				),
				delta: kpiData.totalInteractionsDelta,
				description: "Likes, replies, saves, shares, reposts, and quotes.",
			},
			{
				label: "Saves + shares",
				current: formatCompact(kpiData.saves + kpiData.shares),
				previous: formatCompact(
					(previousFromDelta(kpiData.saves, kpiData.savesDelta) ?? 0) +
						(previousFromDelta(kpiData.shares, kpiData.sharesDelta) ?? 0),
				),
				delta:
					kpiData.saves + kpiData.shares > 0
						? fleetMetrics.sendsPlusSavesDeltaPct
						: null,
				description: "Quality actions that usually outlast likes.",
			},
			{
				label: "Engagement rate",
				current: formatAvailablePercent(engagementRate),
				previous: formatAvailablePercent(
					previousFromPointDelta(engagementRate, kpiData.engagementRateDelta),
				),
				delta: kpiData.engagementRateDelta,
				deltaSuffix: "pp",
				description: "Engagements divided by people reached.",
			},
			{
				label: "Publishing reliability",
				current: formatAvailablePercent(fleetMetrics.scheduleCompliance),
				previous: formatAvailablePercent(
					previousFromPointDelta(
						fleetMetrics.scheduleCompliance,
						fleetMetrics.scheduleComplianceDelta,
					),
				),
				delta: fleetMetrics.scheduleComplianceDelta,
				deltaSuffix: "pp",
				description: "Published posts as a share of attempted posts.",
			},
		],
		[
			engagementRate,
			fleetMetrics.scheduleCompliance,
			fleetMetrics.scheduleComplianceDelta,
			fleetMetrics.sendsPlusSavesDeltaPct,
			kpiData.engagementRateDelta,
			kpiData.saves,
			kpiData.savesDelta,
			kpiData.shares,
			kpiData.sharesDelta,
			kpiData.totalInteractions,
			kpiData.totalInteractionsDelta,
			views,
			viewsDelta,
		],
	);
	const evidenceTrendData = useMemo(
		() =>
			recentSeries.map((point) => ({
				label: point.date.slice(5),
				name: point.date,
				value: point.reach,
			})),
		[recentSeries],
	);
	const changeNotes = useMemo(() => {
		const notes: Array<{
			title: string;
			description: string;
			tone?: "default" | "success" | "warning" | "danger";
		}> = [];
		const reachDelta = kpiData.reachDelta ?? fleetMetrics.reachDeltaPct;
		if (reachDelta != null) {
			notes.push({
				title: reachDelta >= 0 ? "Views are up" : "Views are down",
				description: `${formatDelta(reachDelta)} vs. the prior window.`,
				tone: reachDelta >= 0 ? "success" : "danger",
			});
		}
		if (kpiData.totalInteractionsDelta != null) {
			notes.push({
				title:
					kpiData.totalInteractionsDelta >= 0
						? "Engagement improved"
						: "Engagement softened",
				description: `${formatDelta(kpiData.totalInteractionsDelta)} total interactions vs. prior.`,
				tone: kpiData.totalInteractionsDelta >= 0 ? "success" : "warning",
			});
		}
		if (bestPosts[0]) {
			notes.push({
				title: "Top post to learn from",
				description: `${formatCompact(bestPosts[0].views || bestPosts[0].reach)} views · ${formatCompact(bestPosts[0].engagement)} engagements.`,
				tone: "default",
			});
		}
		if (reviewPosts.length > 0) {
			notes.push({
				title: "Posts ready to review",
				description: `${reviewPosts.length} mature post${reviewPosts.length === 1 ? "" : "s"} underperformed after 72 hours.`,
				tone: "warning",
			});
		}
		return notes.slice(0, 4);
	}, [
		bestPosts,
		fleetMetrics.reachDeltaPct,
		kpiData.reachDelta,
		kpiData.totalInteractionsDelta,
		reviewPosts,
	]);
	const accountColumns = useMemo<ColumnDef<FleetAccountAggregate>[]>(
		() => [
			{
				accessorKey: "username",
				header: "Account",
				cell: ({ row }) => (
					<span className="inline-flex min-w-0 items-center gap-2 font-medium text-foreground">
						<BrandLogo name={row.original.platform} size="xs" monochrome />
						<span className="truncate">
							{row.original.username
								? `@${row.original.username}`
								: row.original.accountId}
						</span>
					</span>
				),
			},
			{
				accessorKey: "platform",
				header: "Platform",
				cell: ({ row }) => (
					<span className="inline-flex items-center gap-2 text-muted-foreground">
						<BrandLogo name={row.original.platform} size="xs" monochrome />
						{row.original.platform}
					</span>
				),
			},
			{
				accessorKey: "reach",
				header: "Views / reach",
				cell: ({ row }) => formatCompact(row.original.reach),
				meta: {
					headerClassName: "text-right",
					cellClassName: "text-right tabular-nums",
				},
			},
			{
				id: "engagements",
				header: "Engagements",
				cell: ({ row }) => formatCompact(accountEngagement(row.original)),
				meta: {
					headerClassName: "text-right",
					cellClassName: "text-right tabular-nums",
				},
			},
			{
				id: "engagementRate",
				header: "Engagement rate",
				cell: ({ row }) =>
					row.original.reach > 0
						? formatPercent(
								(accountEngagement(row.original) / row.original.reach) * 100,
							)
						: "Pending",
				meta: {
					headerClassName: "text-right",
					cellClassName: "text-right tabular-nums",
				},
			},
			{
				accessorKey: "posts",
				header: "Posts",
				cell: ({ row }) => row.original.posts,
				meta: {
					headerClassName: "text-right",
					cellClassName: "text-right tabular-nums",
				},
			},
			{
				accessorKey: "reachDeltaPct",
				header: "Vs. prior",
				cell: ({ row }) => formatDelta(row.original.reachDeltaPct),
				meta: {
					headerClassName: "text-right",
					cellClassName: "text-right tabular-nums",
				},
			},
		],
		[],
	);
	const postColumns = useMemo<ColumnDef<TopPostRow>[]>(
		() => [
			{
				accessorKey: "caption",
				header: "Preview",
				cell: ({ row }) => {
					const post = row.original;
					return (
						<div className="flex min-w-[260px] items-center gap-3">
							<div className="flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted text-muted-foreground">
								{post.mediaUrl ? (
									<img
										src={post.mediaUrl}
										alt=""
										className="size-full object-cover"
										loading="lazy"
										decoding="async"
									/>
								) : (
									<MessageCircle className="size-4" aria-hidden />
								)}
							</div>
							<div className="min-w-0">
								<div className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
									{post.caption || "Untitled post"}
								</div>
								<div className="mt-1 text-xs text-muted-foreground">
									{post.groupName}
								</div>
							</div>
						</div>
					);
				},
			},
			{
				accessorKey: "publishedAt",
				header: "Published",
				cell: ({ row }) => formatPublishedAt(row.original.publishedAt),
			},
			{
				accessorKey: "accountHandle",
				header: "Account",
				cell: ({ row }) => (
					<span className="inline-flex min-w-0 items-center gap-2 font-medium text-foreground">
						<BrandLogo
							name={topPostPlatformLogo(row.original)}
							size="xs"
							monochrome
						/>
						<span className="truncate">@{row.original.accountHandle}</span>
					</span>
				),
			},
			{
				accessorKey: "platform",
				header: "Platform",
				cell: ({ row }) => (
					<Badge
						tone={row.original.platform === "instagram" ? "oxblood" : "secondary"}
					>
						<BrandLogo
							name={topPostPlatformLogo(row.original)}
							size="xs"
							monochrome
						/>
						{topPostPlatformLabel(row.original)}
					</Badge>
				),
			},
			{
				accessorKey: "reach",
				header: "Views / reach",
				cell: ({ row }) => formatCompact(row.original.reach),
				meta: {
					headerClassName: "text-right",
					cellClassName: "text-right tabular-nums",
				},
			},
			{
				id: "engagements",
				accessorFn: (post) => engagementTotal(post),
				header: "Engagements",
				cell: ({ row }) => formatCompact(engagementTotal(row.original)),
				meta: {
					headerClassName: "text-right",
					cellClassName: "text-right tabular-nums",
				},
			},
			{
				id: "engagementRate",
				accessorFn: (post) => topPostEngagementRate(post) ?? -1,
				header: "Engagement rate",
				cell: ({ row }) => formatPercent(topPostEngagementRate(row.original)),
				meta: {
					headerClassName: "text-right",
					cellClassName: "text-right tabular-nums",
				},
			},
			{
				accessorKey: "saves",
				header: "Saves",
				cell: ({ row }) => formatCompact(row.original.saves),
				meta: {
					headerClassName: "text-right",
					cellClassName: "text-right tabular-nums",
				},
			},
			{
				accessorKey: "sends",
				header: "Shares / sends",
				cell: ({ row }) => formatCompact(row.original.sends),
				meta: {
					headerClassName: "text-right",
					cellClassName: "text-right tabular-nums",
				},
			},
			{
				accessorKey: "comments",
				header: "Replies / comments",
				cell: ({ row }) => formatCompact(row.original.comments),
				meta: {
					headerClassName: "text-right",
					cellClassName: "text-right tabular-nums",
				},
			},
			{
				id: "status",
				accessorFn: (post) =>
					topPostNeedsReview(post, contentOperations.reviewThreshold)
						? 0
						: discoveryScore(post),
				header: "Status",
				cell: ({ row }) => {
					const post = row.original;
					if (topPostNeedsReview(post, contentOperations.reviewThreshold)) {
						return <Badge tone="danger">Review</Badge>;
					}
					if (discoveryScore(post) > 0) {
						return <Badge tone="outline">Signal</Badge>;
					}
					return <Badge tone="secondary">Tracking</Badge>;
				},
			},
		],
		[contentOperations.reviewThreshold],
	);

	return (
		<NovaScreen width="wide" density="default">
			<NovaHeader
				eyebrow="Analytics"
				title="Performance"
				description={`Understand ${scopeLabel.toLowerCase()} views, reach, engagement, audience movement, links, and post performance.`}
				meta={
					<div className="flex flex-wrap items-center gap-2">
						<Badge tone="secondary">{accounts.length} accounts</Badge>
						<Badge tone="outline">{dateRangeLabel(state.dateRange)}</Badge>
					</div>
				}
				actions={
					<div className="flex flex-wrap items-center gap-2">
						<Button
							variant="outline"
							size="sm"
							onClick={() => window.location.reload()}
						>
							<RefreshCw data-icon="inline-start" aria-hidden />
							Refresh
						</Button>
						<AnalyticsExportMenu
							fleet={fleetMetrics}
							kpi={kpiData}
							scopeLabel={scopeLabel}
						/>
					</div>
				}
				filters={
					<div className="flex flex-wrap items-center gap-2">
						<PillSegmented
							ariaLabel="Platform"
							options={PLATFORM_OPTIONS}
							value={state.platform as AnalyticsPlatformUi}
							onChange={(platform: AnalyticsPlatformUi) =>
								updateState({ platform })
							}
						/>
						<PillSegmented
							ariaLabel="Date range"
							options={RANGE_OPTIONS}
							value={
								state.dateRange.kind === "preset"
									? state.dateRange.preset
									: "30d"
							}
							onChange={(preset: "7d" | "14d" | "30d" | "90d") =>
								updateState({ dateRange: { kind: "preset", preset } })
							}
							size="sm"
						/>
					</div>
				}
			/>

			<Tabs
				value={state.tab}
				onValueChange={(tab) => updateState({ tab: tab as AnalyticsTab })}
				className="flex min-w-0 flex-col gap-4"
			>
				<TabsList className="w-full justify-start overflow-x-auto">
					{ANALYTICS_TABS.map((tab) => (
						<TabsTrigger key={tab.id} value={tab.id}>
							{tab.label}
						</TabsTrigger>
					))}
				</TabsList>

				<TabsContent value="overview" className="mt-0 flex flex-col gap-4">
					<NovaSection className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
						<NovaStat
							label="Views"
							value={formatCompact(views)}
							description="Reach-backed total until dedicated views aggregation lands."
							trend={{
								direction: deltaDirection(
									kpiData.reachDelta ?? fleetMetrics.reachDeltaPct,
								),
								label: formatDelta(
									kpiData.reachDelta ?? fleetMetrics.reachDeltaPct,
								),
							}}
							icon={<TrendingUp aria-hidden />}
							loading={kpiData.isLoading || fleetMetrics.isLoading}
						/>
						<NovaStat
							label="People reached"
							value={formatCompact(kpiData.reach || fleetMetrics.totalReach)}
							description={`${formatCompact(fleetMetrics.postCount)} posts sampled`}
							trend={{
								direction: deltaDirection(
									kpiData.reachDelta ?? fleetMetrics.reachDeltaPct,
								),
								label: formatDelta(
									kpiData.reachDelta ?? fleetMetrics.reachDeltaPct,
								),
							}}
							icon={<Users aria-hidden />}
							loading={kpiData.isLoading || fleetMetrics.isLoading}
						/>
						<NovaStat
							label="Engagements"
							value={formatCompact(kpiData.totalInteractions)}
							description="Likes, comments, replies, saves, shares, reposts."
							trend={{
								direction: deltaDirection(kpiData.totalInteractionsDelta),
								label: formatDelta(kpiData.totalInteractionsDelta),
							}}
							icon={<Sparkles aria-hidden />}
							loading={kpiData.isLoading}
						/>
						<NovaStat
							label="Engagement rate"
							value={formatPercent(engagementRate)}
							description="Engagements divided by people reached."
							trend={{
								direction: deltaDirection(kpiData.engagementRateDelta),
								label: formatDelta(kpiData.engagementRateDelta),
							}}
							icon={<BarChart3 aria-hidden />}
							loading={kpiData.isLoading}
						/>
					</NovaSection>

					<NovaSection className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
						<NovaStat
							label="Saves"
							value={formatCompact(kpiData.saves)}
							description={formatPercent(kpiData.saveRate)}
							trend={{
								direction: deltaDirection(kpiData.savesDelta),
								label: formatDelta(kpiData.savesDelta),
							}}
							icon={<Bookmark aria-hidden />}
							loading={kpiData.isLoading}
							variant="compact"
						/>
						<NovaStat
							label="Shares"
							value={formatCompact(kpiData.shares)}
							description={formatPercent(kpiData.sendRate)}
							trend={{
								direction: deltaDirection(kpiData.sharesDelta),
								label: formatDelta(kpiData.sharesDelta),
							}}
							icon={<Share2 aria-hidden />}
							loading={kpiData.isLoading}
							variant="compact"
						/>
						<NovaStat
							label="Replies"
							value={formatCompact(kpiData.replies)}
							description="Comments and reply volume."
							trend={{
								direction: deltaDirection(kpiData.repliesDelta),
								label: formatDelta(kpiData.repliesDelta),
							}}
							icon={<MessageCircle aria-hidden />}
							loading={kpiData.isLoading}
							variant="compact"
						/>
						<NovaStat
							label="Net followers"
							value={formatPercent(fleetMetrics.followerGrowthPct)}
							description="Growth across the selected window."
							trend={{
								direction: deltaDirection(fleetMetrics.followerGrowthDeltaPct),
								label: formatDelta(fleetMetrics.followerGrowthDeltaPct),
							}}
							icon={<ArrowUpRight aria-hidden />}
							loading={fleetMetrics.isLoading}
							variant="compact"
						/>
					</NovaSection>

					<NovaSection className="grid gap-4 xl:grid-cols-[1.45fr_1fr]">
						<NovaCard
							title="Views trend"
							description="Daily views/reach for the selected platform and scope."
							footer={
								<div className="grid w-full gap-3 sm:grid-cols-3">
										<NovaMiniStat
											label="Views"
											value={formatCompact(views)}
											description="vs. prior window"
											trend={formatDelta(viewsDelta)}
											tone={
												viewsDelta == null
													? "default"
													: viewsDelta >= 0
														? "success"
														: "danger"
											}
									/>
									<NovaMiniStat
										label="Engagements"
										value={formatCompact(kpiData.totalInteractions)}
										description="vs. prior window"
										trend={formatDelta(kpiData.totalInteractionsDelta)}
										tone={
											kpiData.totalInteractionsDelta == null
												? "default"
												: kpiData.totalInteractionsDelta >= 0
													? "success"
													: "danger"
										}
									/>
									<NovaMiniStat
										label="Peak day"
										value={formatCompact(maxReach)}
										description="highest daily reach"
									/>
								</div>
							}
						>
							{fleetMetrics.isLoading ? (
								<div className="flex min-h-72 flex-col justify-end gap-4">
									<Skeleton className="h-[268px] w-full rounded-lg" />
									<Separator />
									<div className="grid gap-2 sm:grid-cols-3">
										<Skeleton className="h-12" />
										<Skeleton className="h-12" />
										<Skeleton className="h-12" />
									</div>
								</div>
							) : recentSeries.length > 0 ? (
								<div className="flex min-h-72 flex-col justify-end gap-4">
									<JunoBarChart
										ariaLabel="Daily views trend"
										data={evidenceTrendData}
										valueLabel="Views"
										valueFormatter={formatCompact}
									/>
									<Separator />
									<div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
										<span>Synced account and post performance.</span>
										<Badge tone="outline">{formatCompact(maxReach)} peak</Badge>
									</div>
								</div>
							) : (
								<NovaEmpty
									title="No analytics sample yet"
									description="Publish posts or widen the date range to populate the views trend."
								/>
							)}
						</NovaCard>

						<NovaDataPanel
							title="What changed"
							description="The quick read before opening deeper tabs."
							loading={fleetMetrics.isLoading || kpiData.isLoading}
							empty={
								<NovaEmpty
									title="No change signals yet"
									description="Widen the date range or publish more posts to compare movement."
								/>
							}
						>
							<div className="flex flex-col gap-2">
								{changeNotes.map((note) => (
									<NovaListRow
										key={`${note.title}-${note.description}`}
										title={note.title}
										description={note.description}
										meta={
											note.tone && note.tone !== "default" ? (
													<Badge
														tone={
															note.tone === "danger"
																? "oxblood"
																: note.tone === "success"
																	? "outline"
																	: "secondary"
														}
												>
													{note.tone}
												</Badge>
											) : null
										}
									/>
								))}
							</div>
						</NovaDataPanel>
					</NovaSection>

					<NovaSection className="grid gap-4 xl:grid-cols-2">
						<PostStrip
							title="Best posts"
							description="Top performers in the selected window."
							posts={bestPosts}
							loading={topBottomPosts.isLoading}
							empty="No top posts for this filter yet."
						/>
						<PostStrip
							title="Posts to review"
							description="Mature posts older than 72 hours that underperformed."
							posts={reviewPosts}
							loading={topBottomPosts.isLoading}
							empty="No mature underperformers to review."
						/>
					</NovaSection>
				</TabsContent>

				<TabsContent value="posts" className="mt-0">
					<NovaDataPanel
						title="Posts"
						description="Ranked published posts for this analytics window. Mature underperformers are marked after 72 hours."
						loading={analyticsPosts.isLoading}
						empty={
							<NovaEmpty
								title="No published posts in this sample"
								description="Try a wider date range, switch platform, or open Content to inspect the broader library."
								action={
									<Button asChild>
										<Link to="/content">Open Content</Link>
									</Button>
								}
							/>
						}
						toolbar={
							<Button asChild variant="outline">
								<Link to="/content">
									Open Content
									<ArrowUpRight data-icon="inline-end" aria-hidden />
								</Link>
							</Button>
						}
					>
						<DataTable
							data={analyticsPosts.posts}
							columns={postColumns}
							empty={
								<NovaEmpty
									title="No published posts in this sample"
									description="Try a wider date range, switch platform, or open Content to inspect the broader library."
									action={
										<Button asChild>
											<Link to="/content">Open Content</Link>
										</Button>
									}
								/>
							}
							ariaLabel="Post performance analytics"
							getRowHref={(post) => calendarPostPath(post.id, post.publishedAt)}
							className="overflow-x-auto"
							tableClassName="min-w-[1180px]"
						/>
					</NovaDataPanel>
				</TabsContent>

				<TabsContent value="accounts" className="mt-0">
					<NovaDataPanel
						title="Accounts"
						description="Account rollup by views/reach, engagement, posts, and movement."
						loading={fleetMetrics.isLoading}
						empty={
							<NovaEmpty
								title="No accounts in this sample"
								description="Try a wider range or a different platform filter."
							/>
						}
					>
						<DataTable
							data={topAccounts}
							columns={accountColumns}
							ariaLabel="Account analytics rollup"
							className="overflow-x-auto"
							tableClassName="min-w-[820px]"
						/>
					</NovaDataPanel>
				</TabsContent>

				<TabsContent value="audience" className="mt-0">
					<NovaSection className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
						<NovaSection className="grid gap-4 md:grid-cols-2 xl:grid-cols-1">
							<NovaStat
								label="Net followers"
								value={formatAvailablePercent(fleetMetrics.followerGrowthPct)}
								description={
									fleetMetrics.followerGrowthPct == null
										? "Unavailable until follower history exists for this scope."
										: "Follower movement across the selected window."
								}
								trend={{
									direction: deltaDirection(fleetMetrics.followerGrowthDeltaPct),
									label: formatDelta(fleetMetrics.followerGrowthDeltaPct),
								}}
								icon={<Users aria-hidden />}
								loading={fleetMetrics.isLoading}
							/>
							<NovaStat
								label="Non-follower reach"
								value={
									kpiData.igNonFollowerReachAvailable
										? formatAvailablePercent(kpiData.igNonFollowerReachPct)
										: "Unavailable"
								}
								description={
									kpiData.igNonFollowerReachAvailable
										? "Instagram audience discovery share."
										: "Available only when Instagram daily analytics include non-follower reach."
								}
								trend={{
									direction: deltaDirection(kpiData.igNonFollowerReachPctDelta),
									label: formatDelta(kpiData.igNonFollowerReachPctDelta),
								}}
								icon={<UserRound aria-hidden />}
								loading={kpiData.isLoading}
							/>
							<NovaStat
								label="People reached"
								value={formatCompact(kpiData.reach || fleetMetrics.totalReach)}
								description="Audience size proxy for this filter."
								trend={{
									direction: deltaDirection(
										kpiData.reachDelta ?? fleetMetrics.reachDeltaPct,
									),
									label: formatDelta(
										kpiData.reachDelta ?? fleetMetrics.reachDeltaPct,
									),
								}}
								icon={<TrendingUp aria-hidden />}
								loading={kpiData.isLoading || fleetMetrics.isLoading}
							/>
						</NovaSection>

						<NovaDataPanel
							title="Audience profile"
							description={
								scopedAccount
									? `Demographic reads for @${scopedAccount.handle}.`
									: "Select one account to request Meta demographic buckets."
							}
							loading={audienceDemographics.loading}
							toolbar={
								scopedAccount ? (
									<Badge tone="outline">@{scopedAccount.handle}</Badge>
								) : (
									<Badge tone="secondary">Account required</Badge>
								)
							}
							empty={
								<NovaEmpty
									title="Audience profile unavailable"
									description={
										scopedAccount
											? "Meta only returns demographic buckets when the account clears API privacy thresholds."
											: "Use the account scope control to select a single Threads or Instagram account."
									}
								/>
							}
						>
							{audienceDemographics.hasRealData && audienceDemographics.data ? (
								<div className="grid gap-4 lg:grid-cols-3">
									<NovaCard
										variant="panel"
										title="Gender"
										description="Normalized share of available audience data."
									>
										<div className="grid gap-3">
											<NovaMiniStat
												label="Women"
												value={formatAvailablePercent(
													audienceDemographics.data.gender.women,
												)}
												size="compact"
											/>
											<NovaMiniStat
												label="Men"
												value={formatAvailablePercent(
													audienceDemographics.data.gender.men,
												)}
												size="compact"
											/>
											<NovaMiniStat
												label="Other"
												value={formatAvailablePercent(
													audienceDemographics.data.gender.other,
												)}
												size="compact"
											/>
										</div>
									</NovaCard>
									<AudienceBucketCard
										title="Age"
										description="Largest age buckets."
										rows={audienceDemographics.data.ages.map((age) => ({
											label: age.bucket,
											value: age.pct,
										}))}
									/>
									<AudienceBucketCard
										title="Locations"
										description="Top available places."
										rows={audienceDemographics.data.locations.map((location) => ({
											label: location.place,
											value: location.pct,
										}))}
										icon={<MapPin aria-hidden />}
									/>
								</div>
							) : null}
						</NovaDataPanel>
					</NovaSection>
				</TabsContent>

				<TabsContent value="links" className="mt-0">
					<NovaSection className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
						<NovaDataPanel
							title="Links"
							description="Smart Link click performance and attribution summaries."
						>
							<NovaEmpty
								title="Smart Links summary"
								description="Top clicked links render alongside this panel when active links have traffic."
							/>
						</NovaDataPanel>
						<SmartLinksAnalytics />
					</NovaSection>
				</TabsContent>

				<TabsContent value="compare" className="mt-0">
					<NovaSection className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
						<NovaDataPanel
							title="Period comparison"
							description="Current window compared with the selected comparison mode."
							loading={kpiData.isLoading || fleetMetrics.isLoading}
							toolbar={
								<PillSegmented
									ariaLabel="Compare mode"
									options={COMPARE_OPTIONS}
									value={state.compare}
									onChange={(compare: AnalyticsCompareMode) =>
										updateState({ compare })
									}
									size="sm"
								/>
							}
						>
							{state.compare === "prev" ? (
								<div className="grid gap-3">
									{comparisonRows.map((row) => (
										<CompareMetricRow key={row.label} row={row} />
									))}
								</div>
							) : (
								<NovaEmpty
									title={`${COMPARE_OPTIONS.find((option) => option.id === state.compare)?.label ?? "This compare mode"} is not ready yet`}
									description="The first compare pass supports prior-period comparison. Peer, cohort, and year-over-year views need deeper source data before they should be shown."
									icon={<GitCompareArrows aria-hidden />}
								/>
							)}
						</NovaDataPanel>

						<NovaSection className="grid gap-4">
							<NovaDataPanel
								title="Platform split"
								description="Which surface is carrying the selected window."
								loading={fleetMetrics.isLoading}
								empty={
									<NovaEmpty
										title="No platform split yet"
										description="Publish posts in this window to compare platforms."
									/>
								}
							>
								<div className="grid gap-3">
									{platformComparison.map((platform) => (
										<NovaListRow
											key={platform.platform}
											leading={
												<BrandLogo
													name={platform.platform}
													size="sm"
													monochrome
												/>
											}
											title={platformLabel(platform.platform)}
											description={`${formatCompact(platform.reach)} views/reach · ${formatCompact(platform.engagements)} engagements`}
											meta={<Badge tone="outline">{platform.posts} posts</Badge>}
											progress={
												views > 0 ? Math.round((platform.reach / views) * 100) : 0
											}
											progressLabel={`${platformLabel(platform.platform)} share of views`}
										/>
									))}
								</div>
							</NovaDataPanel>

							<NovaDataPanel
								title="Account movers"
								description="Accounts with the strongest available movement."
								loading={fleetMetrics.isLoading}
								empty={
									<NovaEmpty
										title="No account movers yet"
										description="Try a wider date range or publish more posts."
									/>
								}
							>
								<div className="grid gap-2">
									{accountMovers.map((account) => (
										<NovaListRow
											key={`${account.platform}-${account.accountId}`}
											leading={
												<BrandLogo
													name={account.platform}
													size="sm"
													monochrome
												/>
											}
											title={
												account.username
													? `@${account.username}`
													: account.accountId
											}
											description={`${formatCompact(account.reach)} views/reach · ${formatAvailablePercent(accountEngagementRate(account))} engagement rate`}
											meta={
												<Badge tone={deltaDirection(account.reachDeltaPct) === "down" ? "danger" : "outline"}>
													{formatDelta(account.reachDeltaPct)}
												</Badge>
											}
										/>
									))}
								</div>
							</NovaDataPanel>
						</NovaSection>
					</NovaSection>
				</TabsContent>
			</Tabs>
		</NovaScreen>
	);
}

function AudienceBucketCard({
	title,
	description,
	rows,
	icon,
}: {
	title: string;
	description: string;
	rows: Array<{ label: string; value: number }>;
	icon?: ReactNode;
}) {
	const topValue = Math.max(1, ...rows.map((row) => row.value));
	return (
		<NovaCard
			variant="panel"
			title={
				<span className="inline-flex items-center gap-2">
					{icon}
					{title}
				</span>
			}
			description={description}
		>
			{rows.length > 0 ? (
				<div className="grid gap-2">
					{rows.slice(0, 5).map((row) => (
						<NovaListRow
							key={row.label}
							title={row.label}
							description={`${formatAvailablePercent(row.value)} of available data`}
							meta={<Badge tone="outline">{formatAvailablePercent(row.value)}</Badge>}
							progress={Math.round((row.value / topValue) * 100)}
							progressLabel={`${row.label} audience share`}
						/>
					))}
				</div>
			) : (
				<NovaEmpty
					title={`${title} unavailable`}
					description="Meta did not return enough data for this bucket."
				/>
			)}
		</NovaCard>
	);
}

function CompareMetricRow({
	row,
}: {
	row: {
		label: string;
		current: string;
		previous: string;
		delta: number | null | undefined;
		deltaSuffix?: string | undefined;
		description: string;
	};
}) {
	const direction = deltaDirection(row.delta);
	const deltaLabel =
		row.delta == null
			? "No prior"
			: row.deltaSuffix === "pp"
				? `${row.delta >= 0 ? "+" : ""}${Math.round(row.delta * 10) / 10}pp`
				: formatDelta(row.delta);
	const tone =
		direction === "down" ? "danger" : direction === "up" ? "primary" : "default";
	return (
		<div className="rounded-lg border border-border bg-muted/35 p-3">
			<div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
				<div className="min-w-0">
					<div className="font-semibold text-foreground">{row.label}</div>
					<div className="mt-1 text-sm text-muted-foreground">
						{row.description}
					</div>
				</div>
				<Badge
					tone={
						direction === "down"
							? "danger"
							: direction === "up"
								? "oxblood"
								: "secondary"
					}
				>
					{deltaLabel}
				</Badge>
			</div>
			<div className="mt-3 grid gap-2 sm:grid-cols-2">
				<NovaMiniStat
					label="Current"
					value={row.current}
					description="selected window"
					tone={tone}
					size="compact"
				/>
				<NovaMiniStat
					label="Previous"
					value={row.previous}
					description="comparison window"
					size="compact"
				/>
			</div>
		</div>
	);
}

function PostStrip({
	title,
	description,
	posts,
	loading,
	empty,
}: {
	title: string;
	description: string;
	posts: TopBottomPost[];
	loading: boolean;
	empty: string;
}) {
	return (
		<NovaDataPanel
			title={title}
			description={description}
			loading={loading}
			empty={<NovaEmpty title={empty} description="Change the date or platform filter to inspect more posts." />}
		>
			<div className="flex flex-col gap-2">
				{posts.map((post) => (
					<NovaListRow
						key={post.id}
						leading={<BrandLogo name={post.platform} size="xs" monochrome />}
						title={formatPostTitle(post)}
						description={`${post.username ? `@${post.username} · ` : ""}${formatCompact(post.views || post.reach)} views · ${formatCompact(post.engagement)} engagements`}
						meta={
							<Badge tone="outline">
								{post.engagementRate == null
									? "ER pending"
									: `${post.engagementRate}% ER`}
							</Badge>
						}
					/>
				))}
			</div>
		</NovaDataPanel>
	);
}

function AnalyticsExportMenu({
	fleet,
	kpi,
	scopeLabel,
}: {
	fleet: ReturnType<typeof useFleetMetrics>;
	kpi: ReturnType<typeof useFleetKpiData>;
	scopeLabel: string;
}) {
	const ts = new Date().toISOString().slice(0, 10);
	const slug =
		scopeLabel
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, "-")
			.replace(/(^-|-$)/g, "") || "fleet";
	const disabled =
		fleet.isLoading ||
		(fleet.accounts.length === 0 && fleet.series.length === 0);

	return (
		<DropdownMenuRoot>
			<DropdownMenuTrigger asChild>
				<Button variant="outline" size="sm" disabled={disabled}>
					<Download data-icon="inline-start" aria-hidden />
					Export
				</Button>
			</DropdownMenuTrigger>
			<DropdownMenuContent align="end">
				<DropdownMenuLabel>Export CSV</DropdownMenuLabel>
				<DropdownMenuSeparator />
				<DropdownMenuItem
					disabled={fleet.accounts.length === 0}
					onSelect={() =>
						downloadCsv(
							`juno33-accounts-${slug}-${ts}.csv`,
							buildAccountAggregatesCsv(fleet),
						)
					}
				>
					Per-account rollup
				</DropdownMenuItem>
				<DropdownMenuItem
					disabled={fleet.series.length === 0}
					onSelect={() =>
						downloadCsv(
							`juno33-daily-${slug}-${ts}.csv`,
							buildDailySeriesCsv(fleet),
						)
					}
				>
					Daily views trend
				</DropdownMenuItem>
				<DropdownMenuItem
					disabled={kpi.isLoading}
					onSelect={() =>
						downloadCsv(
							`juno33-kpis-${slug}-${ts}.csv`,
							buildKpiSnapshotCsv(kpi),
						)
					}
				>
					KPI snapshot
				</DropdownMenuItem>
			</DropdownMenuContent>
		</DropdownMenuRoot>
	);
}
