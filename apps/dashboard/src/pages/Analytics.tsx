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
	DropdownMenuGroup,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuRoot,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/DropdownMenu";
import {
	JunoBarChart,
	JunoComparisonBarChart,
	JunoShareBarChart,
} from "@/components/ui/JunoChart";
import { MotionReveal } from "@/components/ui/Motion";
import {
	NovaCard,
	NovaDataPanel,
	NovaEmpty,
	NovaHeader,
	NovaInset,
	NovaListRow,
	NovaMiniStat,
	NovaSection,
	NovaStat,
} from "@/components/ui/NovaPrimitives";
import { PillSegmented } from "@/components/ui/PillSegmented";
import { Progress } from "@/components/ui/Progress";
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
	type AnalyticsState,
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
import {
	KPI_PRESENTATION,
	deltaDirection,
	formatCompact,
	formatDelta,
	formatPercent,
} from "@/lib/kpiPresentation";

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

type AnalyticsSavedView = {
	id:
		| "performance-pulse"
		| "post-review"
		| "audience-readiness"
		| "compare-movement";
	label: string;
	description: string;
	patch: Partial<AnalyticsState>;
};

const SAVED_ANALYTICS_VIEWS: AnalyticsSavedView[] = [
	{
		id: "performance-pulse",
		label: "Performance pulse",
		description: "Overview, fleet-wide, last 30 days.",
		patch: {
			tab: "overview",
			platform: "all",
			dateRange: { kind: "preset", preset: "30d" },
			compare: "prev",
		},
	},
	{
		id: "post-review",
		label: "Post review",
		description: "Rank mature posts and find what needs review.",
		patch: {
			tab: "posts",
			platform: "all",
			dateRange: { kind: "preset", preset: "30d" },
		},
	},
	{
		id: "audience-readiness",
		label: "Audience readiness",
		description: "Check follower movement and demographic availability.",
		patch: {
			tab: "audience",
			platform: "ig",
			dateRange: { kind: "preset", preset: "30d" },
		},
	},
	{
		id: "compare-movement",
		label: "Compare movement",
		description: "Current window against the prior window.",
		patch: {
			tab: "compare",
			platform: "all",
			dateRange: { kind: "preset", preset: "30d" },
			compare: "prev",
		},
	},
];

function toFleetPlatform(platform: AnalyticsPlatform): FleetKpiPlatform {
	return platform === "ig" ? "instagram" : platform;
}

function toTopBottomPlatform(
	platform: AnalyticsPlatform,
): "all" | "threads" | "instagram" {
	return platform === "ig" ? "instagram" : platform;
}

function savedViewMatches(state: AnalyticsState, view: AnalyticsSavedView) {
	if (view.patch.tab && state.tab !== view.patch.tab) return false;
	if (view.patch.platform && state.platform !== view.patch.platform) return false;
	if (view.patch.compare && state.compare !== view.patch.compare) return false;
	if (view.patch.dateRange) {
		return dateRangeLabel(state.dateRange) === dateRangeLabel(view.patch.dateRange);
	}
	return true;
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

function changeToneLabel(tone: "default" | "success" | "warning" | "danger" | undefined) {
	if (tone === "success") return "Up";
	if (tone === "danger") return "Down";
	if (tone === "warning") return "Review";
	return "Insight";
}

function changeToneForPanel(tone: "default" | "success" | "warning" | "danger" | undefined) {
	if (tone === "success") return "success";
	if (tone === "danger") return "danger";
	if (tone === "warning") return "warning";
	return "default";
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
	const reachSparkline = recentSeries
		.map((point) => point.reach)
		.filter((value) => Number.isFinite(value));
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
				label: KPI_PRESENTATION.views.label,
				current: formatCompact(views),
				previous: formatCompact(previousFromDelta(views, viewsDelta)),
				delta: viewsDelta,
				description: KPI_PRESENTATION.views.description,
			},
			{
				label: KPI_PRESENTATION.engagements.label,
				current: formatCompact(kpiData.totalInteractions),
				previous: formatCompact(
					previousFromDelta(
						kpiData.totalInteractions,
						kpiData.totalInteractionsDelta,
					),
				),
				delta: kpiData.totalInteractionsDelta,
				description: KPI_PRESENTATION.engagements.description,
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
				label: KPI_PRESENTATION.engagementRate.label,
				current: formatPercent(engagementRate),
				previous: formatPercent(
					previousFromPointDelta(engagementRate, kpiData.engagementRateDelta),
				),
				delta: kpiData.engagementRateDelta,
				deltaSuffix: "pp",
				description: KPI_PRESENTATION.engagementRate.description,
			},
			{
				label: "Publishing reliability",
				current: formatPercent(fleetMetrics.scheduleCompliance),
				previous: formatPercent(
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
	const comparisonChartRows = useMemo(
		() => [
			{
				label: KPI_PRESENTATION.views.label,
				current: views,
				previous: previousFromDelta(views, viewsDelta) ?? 0,
			},
			{
				label: KPI_PRESENTATION.engagements.label,
				current: kpiData.totalInteractions,
				previous:
					previousFromDelta(
						kpiData.totalInteractions,
						kpiData.totalInteractionsDelta,
					) ?? 0,
			},
			{
				label: "Saves + shares",
				current: kpiData.saves + kpiData.shares,
				previous:
					(previousFromDelta(kpiData.saves, kpiData.savesDelta) ?? 0) +
					(previousFromDelta(kpiData.shares, kpiData.sharesDelta) ?? 0),
			},
		],
		[
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
	const platformShareData = useMemo(
		() =>
			platformComparison.map((platform) => ({
				label: platformLabel(platform.platform),
				pct:
					views > 0
						? Math.round((platform.reach / views) * 1000) / 10
						: 0,
				color:
					platform.platform === "instagram"
						? "var(--color-chart-1)"
						: "var(--color-chart-2)",
			})),
		[platformComparison, views],
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
	const activeSavedView = SAVED_ANALYTICS_VIEWS.find((view) =>
		savedViewMatches(state, view),
	);
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
						<AnalyticsSavedViewsMenu
							activeView={activeSavedView}
							onSelect={(view) => updateState(view.patch)}
						/>
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
				<TabsList className="w-full justify-start overflow-visible max-sm:flex max-sm:flex-wrap max-sm:rounded-2xl sm:overflow-x-auto">
					{ANALYTICS_TABS.map((tab) => (
						<TabsTrigger
							key={tab.id}
							value={tab.id}
							className="max-sm:basis-[31%] max-sm:shrink max-sm:px-2"
						>
							{tab.label}
						</TabsTrigger>
					))}
				</TabsList>

				<TabsContent value="overview" className="mt-0 flex flex-col gap-4">
					<NovaSection className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
						<NovaStat
							label={KPI_PRESENTATION.views.label}
							value={formatCompact(views)}
							description={KPI_PRESENTATION.views.description}
							trend={{
								direction: deltaDirection(
									kpiData.reachDelta ?? fleetMetrics.reachDeltaPct,
								),
								label: formatDelta(
									kpiData.reachDelta ?? fleetMetrics.reachDeltaPct,
								),
							}}
							icon={<TrendingUp aria-hidden />}
							sparkline={{ points: reachSparkline, label: "Views trend" }}
							loading={kpiData.isLoading || fleetMetrics.isLoading}
							variant="compact"
							className="h-full max-sm:[&_.nova-card-footer]:hidden max-sm:[&_.nova-stat-description]:hidden max-sm:[&_.nova-stat-sparkline]:hidden max-sm:[&_.nova-icon-box]:size-8 sm:[&_.nova-card-footer]:flex sm:[&_.nova-stat-description]:line-clamp-2"
							footer={
								<div className="flex w-full items-center justify-between gap-3 text-xs">
									<span className="text-muted-foreground">Window</span>
									<span className="font-semibold text-foreground">{dateRangeLabel(state.dateRange)}</span>
								</div>
							}
						/>
						<NovaStat
							label={KPI_PRESENTATION.peopleReached.label}
							value={formatCompact(kpiData.reach || fleetMetrics.totalReach)}
							description={KPI_PRESENTATION.peopleReached.description}
							trend={{
								direction: deltaDirection(
									kpiData.reachDelta ?? fleetMetrics.reachDeltaPct,
								),
								label: formatDelta(
									kpiData.reachDelta ?? fleetMetrics.reachDeltaPct,
								),
							}}
							icon={<Users aria-hidden />}
							sparkline={{ points: reachSparkline, label: "People reached trend" }}
							loading={kpiData.isLoading || fleetMetrics.isLoading}
							variant="compact"
							className="h-full max-sm:[&_.nova-card-footer]:hidden max-sm:[&_.nova-stat-description]:hidden max-sm:[&_.nova-stat-sparkline]:hidden max-sm:[&_.nova-icon-box]:size-8 sm:[&_.nova-card-footer]:flex sm:[&_.nova-stat-description]:line-clamp-2"
							footer={
								<div className="flex w-full items-center justify-between gap-3 text-xs">
									<span className="text-muted-foreground">Scope</span>
									<span className="truncate font-semibold text-foreground">{scopeLabel}</span>
								</div>
							}
						/>
						<NovaStat
							label={KPI_PRESENTATION.engagements.label}
							value={formatCompact(kpiData.totalInteractions)}
							description={KPI_PRESENTATION.engagements.description}
							trend={{
								direction: deltaDirection(kpiData.totalInteractionsDelta),
								label: formatDelta(kpiData.totalInteractionsDelta),
							}}
							icon={<Sparkles aria-hidden />}
							loading={kpiData.isLoading}
							variant="compact"
							className="h-full max-sm:[&_.nova-card-footer]:hidden max-sm:[&_.nova-stat-description]:hidden max-sm:[&_.nova-icon-box]:size-8 sm:[&_.nova-card-footer]:flex sm:[&_.nova-stat-description]:line-clamp-2"
							footer={
								<div className="flex w-full items-center justify-between gap-3 text-xs">
									<span className="text-muted-foreground">Rate</span>
									<span className="font-semibold text-foreground">{formatPercent(engagementRate)}</span>
								</div>
							}
						/>
						<NovaStat
							label={KPI_PRESENTATION.engagementRate.label}
							value={formatPercent(engagementRate)}
							description={KPI_PRESENTATION.engagementRate.description}
							trend={{
								direction: deltaDirection(kpiData.engagementRateDelta),
								label: formatDelta(kpiData.engagementRateDelta),
							}}
							icon={<BarChart3 aria-hidden />}
							loading={kpiData.isLoading}
							variant="compact"
							className="h-full max-sm:[&_.nova-card-footer]:hidden max-sm:[&_.nova-stat-description]:hidden max-sm:[&_.nova-icon-box]:size-8 sm:[&_.nova-card-footer]:flex sm:[&_.nova-stat-description]:line-clamp-2"
							footer={
								<div className="flex w-full items-center justify-between gap-3 text-xs">
									<span className="text-muted-foreground">Interactions</span>
									<span className="font-semibold text-foreground">{formatCompact(kpiData.totalInteractions)}</span>
								</div>
							}
						/>
					</NovaSection>

					<NovaSection className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
						<NovaStat
							label={KPI_PRESENTATION.saves.label}
							value={formatCompact(kpiData.saves)}
							description={formatPercent(kpiData.saveRate)}
							trend={{
								direction: deltaDirection(kpiData.savesDelta),
								label: formatDelta(kpiData.savesDelta),
							}}
							icon={<Bookmark aria-hidden />}
							loading={kpiData.isLoading}
							variant="compact"
							className="h-full max-sm:[&_.nova-stat-description]:hidden max-sm:[&_.nova-icon-box]:size-8"
						/>
						<NovaStat
							label={KPI_PRESENTATION.shares.label}
							value={formatCompact(kpiData.shares)}
							description={formatPercent(kpiData.sendRate)}
							trend={{
								direction: deltaDirection(kpiData.sharesDelta),
								label: formatDelta(kpiData.sharesDelta),
							}}
							icon={<Share2 aria-hidden />}
							loading={kpiData.isLoading}
							variant="compact"
							className="h-full max-sm:[&_.nova-stat-description]:hidden max-sm:[&_.nova-icon-box]:size-8"
						/>
						<NovaStat
							label={KPI_PRESENTATION.replies.label}
							value={formatCompact(kpiData.replies)}
							description={KPI_PRESENTATION.replies.description}
							trend={{
								direction: deltaDirection(kpiData.repliesDelta),
								label: formatDelta(kpiData.repliesDelta),
							}}
							icon={<MessageCircle aria-hidden />}
							loading={kpiData.isLoading}
							variant="compact"
							className="h-full max-sm:[&_.nova-stat-description]:hidden max-sm:[&_.nova-icon-box]:size-8"
						/>
						<NovaStat
							label={KPI_PRESENTATION.followerGrowth.label}
							value={formatPercent(fleetMetrics.followerGrowthPct)}
							description={KPI_PRESENTATION.followerGrowth.description}
							trend={{
								direction: deltaDirection(fleetMetrics.followerGrowthDeltaPct),
								label: formatDelta(fleetMetrics.followerGrowthDeltaPct),
							}}
							icon={<ArrowUpRight aria-hidden />}
							loading={fleetMetrics.isLoading}
							variant="compact"
							className="h-full max-sm:[&_.nova-stat-description]:hidden max-sm:[&_.nova-icon-box]:size-8"
						/>
					</NovaSection>

					<MotionReveal delay={0.04}>
						<NovaSection className="grid gap-4 xl:grid-cols-[1.45fr_1fr]">
						<NovaCard
							title={KPI_PRESENTATION.views.chartTitle ?? KPI_PRESENTATION.views.label}
							description={KPI_PRESENTATION.views.chartDescription}
							action={<Badge tone="outline">{dateRangeLabel(state.dateRange)}</Badge>}
							contentClassName="grid gap-3"
							footer={
								<div className="flex w-full flex-col gap-2 text-sm leading-snug text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
									<span className="min-w-0">
										Daily movement rolls up synced account and post signals.
									</span>
									<div className="flex flex-wrap items-center gap-2">
										<Badge tone={viewsDelta == null ? "outline" : viewsDelta >= 0 ? "secondary" : "danger"}>
											{formatDelta(viewsDelta)}
										</Badge>
										<Badge tone="outline">{formatCompact(maxReach)} peak day</Badge>
									</div>
								</div>
							}
						>
							{fleetMetrics.isLoading ? (
								<div className="grid min-h-72 gap-4">
									<Skeleton className="h-[268px] w-full rounded-lg" />
									<Separator />
									<div className="grid gap-2 sm:grid-cols-3">
										<Skeleton className="h-12" />
										<Skeleton className="h-12" />
										<Skeleton className="h-12" />
									</div>
								</div>
							) : recentSeries.length > 0 ? (
								<>
									<JunoBarChart
										ariaLabel="Daily views trend"
										data={evidenceTrendData}
										height={190}
										valueLabel="Views"
										valueFormatter={formatCompact}
									/>
									<Separator className="hidden sm:block" />
									<div className="hidden flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground sm:flex">
										<span>Synced account and post performance.</span>
										<Badge tone="outline">{formatCompact(maxReach)} peak</Badge>
									</div>
								</>
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
							toolbar={<Badge tone="outline">{dateRangeLabel(state.dateRange)}</Badge>}
							loading={fleetMetrics.isLoading || kpiData.isLoading}
						>
							{changeNotes.length > 0 ? (
								<div className="flex flex-col gap-3">
									<NovaInset tone={changeToneForPanel(changeNotes[0]?.tone)}>
										<div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
											<div className="min-w-0">
												<Badge tone="outline">{changeToneLabel(changeNotes[0]?.tone)}</Badge>
												<div className="mt-3 text-lg font-semibold leading-tight text-foreground">
													{changeNotes[0]?.title}
												</div>
												<p className="mt-2 text-sm leading-relaxed text-muted-foreground">
													{changeNotes[0]?.description}
												</p>
											</div>
											<TrendingUp aria-hidden className="mt-1 text-muted-foreground" />
										</div>
									</NovaInset>
									{changeNotes.slice(1).map((note) => (
										<NovaListRow
											key={`${note.title}-${note.description}`}
											title={note.title}
											description={note.description}
											meta={<Badge tone="outline">{changeToneLabel(note.tone)}</Badge>}
										/>
									))}
								</div>
							) : (
								<NovaEmpty
									title="No change signals yet"
									description="Widen the date range or publish more posts to compare movement."
								/>
							)}
						</NovaDataPanel>
						</NovaSection>
					</MotionReveal>

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
					<MotionReveal delay={0.04}>
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
							toolbar={
								<>
									<div className="flex flex-wrap items-center gap-2">
										<Badge tone="outline">
											{analyticsPosts.posts.length.toLocaleString()} posts
										</Badge>
										<Badge tone="secondary">Review after 72h</Badge>
										<Badge tone="secondary">{dateRangeLabel(state.dateRange)}</Badge>
									</div>
									<Button asChild variant="outline" size="sm">
										<Link to="/content">
											Open Content
											<ArrowUpRight data-icon="inline-end" aria-hidden />
										</Link>
									</Button>
								</>
							}
							footer={
								<>
									<span>
										Showing {analyticsPosts.posts.length.toLocaleString()} ranked posts for the active filters.
									</span>
									<span>Mature underperformers are marked only after the 72-hour read window.</span>
								</>
							}
							className="min-w-0"
							frameClassName="max-h-[560px] overflow-auto sm:max-h-[640px] xl:max-h-[720px]"
							tableClassName="min-w-[980px] lg:min-w-[1180px]"
						/>
						</NovaDataPanel>
					</MotionReveal>
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
							className="min-w-0"
							frameClassName="overflow-auto"
							tableClassName="min-w-[820px]"
						/>
					</NovaDataPanel>
				</TabsContent>

				<TabsContent value="audience" className="mt-0">
					<NovaSection className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
						<NovaSection className="grid gap-4 md:grid-cols-2 xl:grid-cols-1">
							<NovaStat
								label={KPI_PRESENTATION.followerGrowth.label}
								value={formatPercent(fleetMetrics.followerGrowthPct)}
								description={
									fleetMetrics.followerGrowthPct == null
										? "Unavailable until follower history exists for this scope."
										: KPI_PRESENTATION.followerGrowth.description
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
										? formatPercent(kpiData.igNonFollowerReachPct)
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
								label={KPI_PRESENTATION.peopleReached.label}
								value={formatCompact(kpiData.reach || fleetMetrics.totalReach)}
								description={KPI_PRESENTATION.peopleReached.description}
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
							<AudienceAvailabilityCard
								selectedAccountHandle={scopedAccount?.handle ?? null}
								profileAvailable={audienceDemographics.hasRealData}
								profileLoading={audienceDemographics.loading}
								nonFollowerAvailable={kpiData.igNonFollowerReachAvailable}
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
												value={formatPercent(
													audienceDemographics.data.gender.women,
												)}
												size="compact"
											/>
											<NovaMiniStat
												label="Men"
												value={formatPercent(
													audienceDemographics.data.gender.men,
												)}
												size="compact"
											/>
											<NovaMiniStat
												label="Other"
												value={formatPercent(
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
							) : (
								<NovaEmpty
									title="Audience profile unavailable"
									description={
										scopedAccount
											? "Meta only returns demographic buckets after the account clears privacy and sample-size thresholds. This is not a zero-read."
											: "Select a single account before reading demographic buckets. Fleet and group scopes can still use movement and reach signals."
									}
									action={
										scopedAccount ? undefined : (
											<Button asChild variant="outline">
												<Link to="/accounts">Choose account</Link>
											</Button>
										)
									}
								/>
							)}
						</NovaDataPanel>
					</NovaSection>
				</TabsContent>

				<TabsContent value="links" className="mt-0">
					<SmartLinksAnalytics />
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
								<div className="grid gap-4">
									<JunoComparisonBarChart
										ariaLabel="Current period compared with prior period"
										data={comparisonChartRows}
										height={220}
										currentLabel="Current"
										previousLabel="Prior"
										valueFormatter={formatCompact}
									/>
									<Separator />
									{comparisonRows.map((row) => (
										<CompareMetricRow key={row.label} row={row} />
									))}
								</div>
							) : (
								<NovaEmpty
									title={`${COMPARE_OPTIONS.find((option) => option.id === state.compare)?.label ?? "This compare mode"} is not ready yet`}
									description="The first compare pass supports prior-period comparison. Peer, cohort, and year-over-year views need deeper source data before they should be shown."
									action={
										<Button
											variant="outline"
											onClick={() => updateState({ compare: "prev" })}
										>
											Use prior period
										</Button>
									}
									icon={<GitCompareArrows aria-hidden />}
								/>
							)}
						</NovaDataPanel>

						<NovaSection className="grid gap-4">
							<CompareReadinessPanel
								activeCompare={state.compare}
								onSelect={(compare) => updateState({ compare })}
							/>
							<NovaDataPanel
								title="Platform split"
								description="Which surface is carrying the selected window."
								loading={fleetMetrics.isLoading}
								toolbar={<Badge tone="outline">{dateRangeLabel(state.dateRange)}</Badge>}
								empty={
									<NovaEmpty
										title="No platform split yet"
										description="Publish posts in this window to compare platforms."
									/>
								}
							>
								<div className="grid gap-4">
									{platformShareData.some((row) => row.pct > 0) ? (
										<JunoShareBarChart
											ariaLabel="Platform share of views"
											data={platformShareData}
											height={132}
										/>
									) : null}
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
											description={`${formatCompact(account.reach)} views/reach · ${formatPercent(accountEngagementRate(account))} engagement rate`}
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

function AudienceAvailabilityCard({
	selectedAccountHandle,
	profileAvailable,
	profileLoading,
	nonFollowerAvailable,
}: {
	selectedAccountHandle: string | null;
	profileAvailable: boolean;
	profileLoading: boolean;
	nonFollowerAvailable: boolean;
}) {
	return (
		<NovaCard
			title="Audience data readiness"
			description="What can be read for the current scope."
			action={
				!selectedAccountHandle ? (
					<Button asChild variant="outline" size="sm">
						<Link to="/accounts">Choose account</Link>
					</Button>
				) : (
					<Badge tone="outline">{selectedAccountHandle}</Badge>
				)
			}
			contentClassName="grid gap-2"
		>
			<NovaListRow
				title="Profile buckets"
				description={
					selectedAccountHandle
						? profileAvailable
							? "Gender, age, and location buckets are available."
							: "Waiting on platform privacy and sample-size thresholds."
						: "Requires a single selected account."
				}
				meta={
					<Badge tone={profileAvailable ? "oxblood" : "secondary"}>
						{profileLoading
							? "Checking"
							: profileAvailable
								? "Ready"
								: "Unavailable"}
					</Badge>
				}
			/>
			<NovaListRow
				title="Non-follower reach"
				description={
					nonFollowerAvailable
						? "Instagram discovery share is present for this window."
						: "Only available when Instagram daily analytics include this metric."
				}
				meta={
					<Badge tone={nonFollowerAvailable ? "oxblood" : "secondary"}>
						{nonFollowerAvailable ? "Ready" : "Unavailable"}
					</Badge>
				}
			/>
		</NovaCard>
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
							description={`${formatPercent(row.value)} of available data`}
							meta={<Badge tone="outline">{formatPercent(row.value)}</Badge>}
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

function CompareReadinessPanel({
	activeCompare,
	onSelect,
}: {
	activeCompare: AnalyticsCompareMode;
	onSelect: (compare: AnalyticsCompareMode) => void;
}) {
	const rows: Array<{
		id: AnalyticsCompareMode;
		title: string;
		description: string;
		ready: boolean;
	}> = [
		{
			id: "prev",
			title: "Prior period",
			description: "Current window against the immediately previous window.",
			ready: true,
		},
		{
			id: "year",
			title: "Year ago",
			description: "Needs longer historical coverage before it should be trusted.",
			ready: false,
		},
		{
			id: "peer",
			title: "Peer set",
			description: "Requires cohort-safe peer normalization before release.",
			ready: false,
		},
		{
			id: "cohort",
			title: "Cohort",
			description: "Requires saved cohort definitions and enough accounts.",
			ready: false,
		},
	];

	return (
		<NovaCard
			title="Compare readiness"
			description="Only show comparisons when the source data is mature enough to trust."
			contentClassName="grid gap-2"
		>
			{rows.map((row) => (
				<NovaListRow
					key={row.id}
					title={row.title}
					description={row.description}
					meta={
						<Badge tone={row.ready ? "oxblood" : "secondary"}>
							{row.ready ? "Ready" : "Future"}
						</Badge>
					}
					action={
						row.ready ? (
							<Button
								variant={activeCompare === row.id ? "secondary" : "outline"}
								size="sm"
								onClick={() => onSelect(row.id)}
							>
								{activeCompare === row.id ? "Active" : "Use"}
							</Button>
						) : null
					}
				/>
			))}
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
				? formatDelta(row.delta, "pp")
				: formatDelta(row.delta);
	const tone =
		direction === "down" ? "danger" : direction === "up" ? "primary" : "default";
	const currentValue = parseFormattedMetric(row.current);
	const previousValue = parseFormattedMetric(row.previous);
	const largest = Math.max(currentValue, previousValue, 1);
	const currentProgress = Math.round((currentValue / largest) * 100);
	const previousProgress = Math.round((previousValue / largest) * 100);
	return (
		<NovaCard
			variant="panel"
			title={row.label}
			description={row.description}
			action={
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
			}
			contentClassName="grid gap-3"
		>
			<NovaInset tone={tone} className="grid gap-3">
			<ComparePeriodRail
					label="Current"
					value={row.current}
					progress={currentProgress}
					tone={tone === "danger" ? "critical" : "default"}
				/>
				<ComparePeriodRail
					label="Previous"
					value={row.previous}
					progress={previousProgress}
				/>
			</NovaInset>
		</NovaCard>
	);
}

function ComparePeriodRail({
	label,
	value,
	progress,
	tone = "default",
}: {
	label: string;
	value: string;
	progress: number;
	tone?: "default" | "good" | "warn" | "critical";
}) {
	return (
		<div className="grid gap-1.5">
			<div className="flex items-center justify-between gap-3 text-sm">
				<span className="text-muted-foreground">{label}</span>
				<span className="font-semibold tabular-nums text-foreground">{value}</span>
			</div>
			<Progress
				value={Math.max(0, Math.min(100, progress))}
				tone={tone}
				aria-label={`${label} comparison magnitude`}
			/>
		</div>
	);
}

function parseFormattedMetric(value: string) {
	if (value === "Pending" || value === "Unavailable" || value === "No prior") {
		return 0;
	}
	const normalized = value.replace(/[,+%]/g, "").trim().toLowerCase();
	const multiplier = normalized.endsWith("k")
		? 1_000
		: normalized.endsWith("m")
			? 1_000_000
			: normalized.endsWith("b")
				? 1_000_000_000
				: 1;
	const parsed = Number.parseFloat(normalized.replace(/[kmb]$/, ""));
	return Number.isFinite(parsed) ? parsed * multiplier : 0;
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

function AnalyticsSavedViewsMenu({
	activeView,
	onSelect,
}: {
	activeView: AnalyticsSavedView | undefined;
	onSelect: (view: AnalyticsSavedView) => void;
}) {
	return (
		<DropdownMenuRoot>
			<DropdownMenuTrigger asChild>
				<Button variant="outline" size="sm">
					<Bookmark data-icon="inline-start" aria-hidden />
					{activeView ? activeView.label : "Saved views"}
				</Button>
			</DropdownMenuTrigger>
			<DropdownMenuContent align="end" className="w-[280px]">
				<DropdownMenuLabel>Saved views</DropdownMenuLabel>
				<DropdownMenuSeparator />
				<DropdownMenuGroup>
					{SAVED_ANALYTICS_VIEWS.map((view) => (
						<DropdownMenuItem
							key={view.id}
							onSelect={() => onSelect(view)}
							className="items-start"
						>
							<div className="min-w-0 flex-1">
								<div className="flex min-w-0 items-center gap-2">
									<span className="truncate font-medium">{view.label}</span>
									{activeView?.id === view.id ? (
										<Badge tone="oxblood" className="shrink-0">
											Active
										</Badge>
									) : null}
								</div>
								<p className="mt-0.5 line-clamp-2 text-xs leading-snug text-muted-foreground">
									{view.description}
								</p>
							</div>
						</DropdownMenuItem>
					))}
				</DropdownMenuGroup>
			</DropdownMenuContent>
		</DropdownMenuRoot>
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
				<DropdownMenuGroup>
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
				</DropdownMenuGroup>
			</DropdownMenuContent>
		</DropdownMenuRoot>
	);
}
