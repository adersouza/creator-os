import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import {
	ArrowDownRight,
	ArrowRight,
	ArrowUpRight,
	BarChart3,
	CalendarClock,
	CheckCircle2,
	Clock3,
	ExternalLink,
	Eye,
	FileText,
	MessageCircle,
	MousePointerClick,
	Plus,
	RefreshCw,
	Sparkles,
	TrendingUp,
	TriangleAlert,
	Users,
	type LucideIcon,
} from "lucide-react";
import { useAuthUser } from "@/hooks/useAuthUser";
import { useFleetTotals } from "@/hooks/useFleetTotals";
import { useFleetKpiData } from "@/hooks/useFleetKpiData";
import { useFleetMetrics } from "@/hooks/useFleetMetrics";
import { useNeedsAttention } from "@/hooks/useNeedsAttention";
import { useNextUpPosts } from "@/hooks/useNextUpPosts";
import { usePendingRepliesQueue } from "@/hooks/usePendingRepliesQueue";
import { useTopPosts, type TopPostRow } from "@/hooks/useTopPosts";
import { useComposer } from "@/contexts/ComposerContext";
import {
	DASHBOARD_TIMEFRAMES,
	dashboardTimeframeToFleetMetrics,
	dashboardTimeframeToTopPosts,
	useDashboardUrlState,
	type DashboardTimeframe,
} from "@/lib/dashboardUrlState";
import { invalidateDashboardQueries } from "@/lib/dashboardQueryInvalidation";
import { DASHBOARD_QUERY_PREFIXES } from "@/lib/dashboardQueryRoots";
import { buildScopeCopy } from "@/lib/scopeLabels";
import { scopedRoute } from "@/lib/scopedRoutes";
import { SfPlus } from "@/components/ui/icons/sf";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { MatrixLoader } from "@/components/ui/MatrixLoader";
import { Skeleton } from "@/components/ui/Skeleton";
import {
	NovaCard,
	NovaDataPanel,
	NovaEmpty,
	NovaHeader,
	NovaListRow,
	NovaMiniStat,
	NovaSection,
} from "@/components/ui/NovaPrimitives";
import { PillSegmented } from "@/components/ui/PillSegmented";
import { JunoBarChart } from "@/components/ui/JunoChart";
import { MobileOverview } from "@/components/dashboard/MobileOverview";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import { useAccountGroups } from "@/hooks/useAccountGroups";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { TileErrorBoundary } from "@/components/ui/ErrorBoundary";
import { PublishingStartCard } from "@/components/publishing/PublishingStartCard";
import {
	buildContentOperations,
	discoveryScore,
	engagementTotal,
} from "@/lib/contentOperations";

import { PLATFORMS, type Platform } from "./shared";
import { HeroTile } from "./tiles/HeroTile";
import {
	GhostCountTile,
	NonFollowerReachTile,
} from "./tiles/SmallTiles";
import { FundamentalsRibbon } from "./FundamentalsRibbon";
import { StreakTile } from "./tiles/StreakTile";
import { ConversationQualityTile } from "./tiles/ConversationQualityTile";
import { ReplyDepthLeadersTile } from "./tiles/ReplyDepthLeadersTile";
import { StoriesFunnelTile } from "./tiles/StoriesFunnelTile";
import {
	ConversationWinnerTile,
	HeldRepliesQueueTile,
	SuppressionDarkTile,
	ViewsBySourceStripTile,
} from "./tiles/ThreadsTiles";
import {
	SendsPerReachBulletDarkTile,
	SendsPerReachLeadersTile,
	WatchPerViewTile,
	QualitySignalBulletsTile,
	SaveRateTopBottomTile,
	ContentMixHealthTile,
	VanityFlagTile,
} from "./tiles/IgV2Tiles";
import { HookStrengthTile } from "./tiles/HookStrengthTile";
import { AICostMetricsTile } from "./tiles/AICostMetricsTile";

function BandHeader({ label, title }: { label: string; title: string }) {
	return (
		<div className="mt-6 flex min-w-0 flex-col gap-1">
			<div className="text-sm font-medium text-primary">{label}</div>
			<div className="text-lg font-semibold tracking-[-0.02em] text-foreground">
				{title}
			</div>
		</div>
	);
}

function TimeframeSegmented({
	value,
	onChange,
}: {
	value: DashboardTimeframe;
	onChange: (next: DashboardTimeframe) => void;
}) {
	return (
		<PillSegmented
			ariaLabel="Dashboard timeframe"
			options={DASHBOARD_TIMEFRAMES}
			value={value}
			onChange={onChange}
			size="md"
		/>
	);
}

function formatCompact(value: number | null | undefined) {
	const safeValue = Number(value ?? 0);
	return new Intl.NumberFormat("en", {
		notation: "compact",
		maximumFractionDigits: safeValue >= 1000 ? 1 : 0,
	}).format(safeValue);
}

function formatPercent(value: number | null | undefined) {
	if (value == null || Number.isNaN(value)) return "Unavailable";
	return `${Math.round(value * 10) / 10}%`;
}

function formatDelta(value: number | null | undefined) {
	if (value == null || Number.isNaN(value)) return "No prior";
	const rounded = Math.round(value * 10) / 10;
	return `${rounded > 0 ? "+" : ""}${rounded}%`;
}

function deltaDirection(value: number | null | undefined): "up" | "down" | "flat" {
	if (value == null || Math.abs(value) < 0.1) return "flat";
	return value > 0 ? "up" : "down";
}

function progressFromDelta(value: number | null | undefined) {
	if (value == null || Number.isNaN(value)) return 0;
	return Math.max(8, Math.min(100, Math.abs(value)));
}

function platformToFleet(platform: Platform): "all" | "threads" | "instagram" {
	return platform === "ig" ? "instagram" : platform;
}

function platformToTopPosts(platform: Platform): "all" | "threads" | "ig" {
	return platform === "ig" ? "ig" : platform;
}

function timeframeToAttention(timeframe: DashboardTimeframe): "7" | "30" | "90" {
	if (timeframe === "7d") return "7";
	if (timeframe === "90d") return "90";
	return "30";
}

function postDateLabel(value: string) {
	if (!value) return "Published";
	return new Intl.DateTimeFormat(undefined, {
		month: "short",
		day: "numeric",
	}).format(new Date(value));
}

function dashboardPlatformOptions(
	accounts: { id: string; platform: string }[],
	accountIds: string[] | undefined,
	scopedAccount: { platform: "threads" | "instagram" } | null | undefined,
): Array<{ id: Platform; label: string }> {
	if (scopedAccount?.platform === "instagram") return [{ id: "ig", label: "Instagram" }];
	if (scopedAccount?.platform === "threads") return [{ id: "threads", label: "Threads" }];
	if (!accountIds || accountIds.length === 0) return PLATFORMS;

	const scopedIds = new Set(accountIds);
	const scopedPlatforms = new Set(
		accounts
			.filter((account) => scopedIds.has(account.id))
			.map((account) => account.platform),
	);
	const hasThreads = scopedPlatforms.has("threads");
	const hasInstagram = scopedPlatforms.has("instagram");
	if (hasThreads && hasInstagram) return PLATFORMS;
	if (hasInstagram) return [{ id: "ig", label: "Instagram" }];
	if (hasThreads) return [{ id: "threads", label: "Threads" }];
	return PLATFORMS;
}

function DashboardKpiCard({
	label,
	value,
	description,
	trendValue,
	icon: Icon,
	footerLabel,
	footerValue,
	loading = false,
}: {
	label: string;
	value: string;
	description: string;
	trendValue: number | null | undefined;
	icon: LucideIcon;
	footerLabel: string;
	footerValue: string;
	loading?: boolean;
}) {
	const direction = deltaDirection(trendValue);
	const trendTone = direction === "down" ? "danger" : direction === "up" ? "oxblood" : "secondary";
	const TrendIcon = direction === "down" ? ArrowDownRight : direction === "up" ? ArrowUpRight : ArrowRight;

	return (
		<NovaCard
			variant="compact"
			className="h-full"
			contentClassName="flex h-full flex-col gap-4"
			footer={
				<div className="flex w-full items-center justify-between gap-3 text-xs">
					<span className="truncate text-muted-foreground">{footerLabel}</span>
					<span className="shrink-0 font-semibold tabular-nums text-foreground">{footerValue}</span>
				</div>
			}
		>
			<div className="flex min-w-0 items-start justify-between gap-3">
				<div className="min-w-0">
					<div className="text-sm font-medium text-muted-foreground">{label}</div>
					{loading ? (
						<Skeleton className="mt-3 h-9 w-28" />
					) : (
						<div className="mt-2 truncate text-4xl font-semibold tracking-normal text-foreground tabular-nums">
							{value}
						</div>
					)}
				</div>
				<div className="nova-icon-box flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
					<Icon aria-hidden="true" />
				</div>
			</div>
			<p className="text-sm leading-relaxed text-muted-foreground">{description}</p>
			<div className="mt-auto grid gap-2">
				<div className="h-1.5 overflow-hidden rounded-full bg-muted">
					<div
						className="h-full rounded-full bg-primary"
						style={{ width: `${progressFromDelta(trendValue)}%` }}
					/>
				</div>
				<Badge tone={trendTone} className="w-fit gap-1">
					<TrendIcon data-icon="inline-start" aria-hidden="true" />
					{formatDelta(trendValue)}
				</Badge>
			</div>
		</NovaCard>
	);
}

/**
 * Dashboard v2 — three-view bento surface (All / Threads / IG).
 *
 * Tile selection and spans are owned here. Keep the dashboard focused on
 * operator attention: summary in the hero/all-view ribbon, platform-specific
 * evidence in the Threads and Instagram drilldowns.
 */
export function DashboardV2() {
	const [urlState, updateUrlState] = useDashboardUrlState();
	const { platform: urlPlatform, timeframe } = urlState;
	const [searchParams, setSearchParams] = useSearchParams();
	const setPlatform = useCallback(
		(next: Platform) => updateUrlState({ platform: next }),
		[updateUrlState],
	);
	const setTimeframe = useCallback(
		(next: DashboardTimeframe) => updateUrlState({ timeframe: next }),
		[updateUrlState],
	);
	// Bento stays active for tablet-width and narrow desktop windows so the
	// dashboard doesn't become a different product when the app window is
	// resized. Phones keep the compact MobileOverview.
	const [showMobileOverview, setShowMobileOverview] = useState(() =>
		typeof window !== "undefined"
			? window.matchMedia("(max-width: 767px)").matches
			: false,
	);
	useEffect(() => {
		if (typeof window === "undefined") return;
		const mql = window.matchMedia("(max-width: 767px)");
		const update = () => setShowMobileOverview(mql.matches);
		mql.addEventListener("change", update);
		return () => mql.removeEventListener("change", update);
	}, []);
	const navigate = useNavigate();
	const composer = useComposer();
	const authUser = useAuthUser();
	const fleet = useFleetTotals();
	const { accounts } = useConnectedAccounts();
	const scopedHandle = useAccountScopeStore((s) => s.scopedAccount);
	const setAccountScope = useAccountScopeStore((s) => s.setScope);
	const selectedGroupId = useWorkspaceStore((s) => s.selectedGroupId);
	const setSelectedGroupId = useWorkspaceStore((s) => s.setSelectedGroupId);
	const { groups } = useAccountGroups();

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

	const scopedGroupAccountIds = useMemo(() => {
		if (scopedHandle || !selectedGroupId) return undefined;
		const ids =
			groups.find((group) => group.id === selectedGroupId)?.accountIds ?? [];
		return ids.length > 0 ? ids : undefined;
	}, [groups, scopedHandle, selectedGroupId]);
	const scopedGroupId = scopedHandle ? null : selectedGroupId;
	const platformOptions = useMemo(
		() => dashboardPlatformOptions(accounts, scopedGroupAccountIds, scopedHandle),
		[accounts, scopedGroupAccountIds, scopedHandle],
	);
	const platform: Platform = scopedHandle
		? scopedHandle.platform === "instagram"
			? "ig"
			: "threads"
		: platformOptions.some((option) => option.id === urlPlatform)
			? urlPlatform
			: (platformOptions[0]?.id ?? "all");

	useEffect(() => {
		if (scopedHandle) return;
		if (platformOptions.some((option) => option.id === urlPlatform)) return;
		const fallback = platformOptions[0]?.id ?? "all";
		updateUrlState({ platform: fallback });
	}, [platformOptions, scopedHandle, updateUrlState, urlPlatform]);
	const selectedGroup = useMemo(
		() =>
			!scopedHandle && selectedGroupId
				? groups.find((group) => group.id === selectedGroupId) ?? null
				: null,
		[groups, scopedHandle, selectedGroupId],
	);
	const queryClient = useQueryClient();
	const dashboardFetching = useIsFetching({
		predicate: (query) => {
			const root = query.queryKey[0];
			return (
				typeof root === "string" &&
				DASHBOARD_QUERY_PREFIXES.includes(
					root as (typeof DASHBOARD_QUERY_PREFIXES)[number],
				)
			);
		},
	});
	const syncResetTimerRef = useRef<number | null>(null);

	const [isSyncing, setIsSyncing] = useState(false);
	const handleSyncNow = useCallback(async () => {
		if (isSyncing) return;
		setIsSyncing(true);
		try {
			await invalidateDashboardQueries(queryClient);
		} finally {
			// Tiny minimum so the spinner isn't a flash and the button click
			// feels acknowledged even on cache hits.
			if (syncResetTimerRef.current) {
				window.clearTimeout(syncResetTimerRef.current);
			}
			syncResetTimerRef.current = window.setTimeout(() => {
				setIsSyncing(false);
				syncResetTimerRef.current = null;
			}, 600);
		}
	}, [isSyncing, queryClient]);

	useEffect(
		() => () => {
			if (syncResetTimerRef.current) {
				window.clearTimeout(syncResetTimerRef.current);
			}
		},
		[],
	);

	// `P` cycles platform All → Threads → IG → All (spec §12).
	useEffect(() => {
		const h = (e: KeyboardEvent) => {
			if (
				e.target instanceof HTMLInputElement ||
				e.target instanceof HTMLTextAreaElement
			)
				return;
			if (e.metaKey || e.ctrlKey || e.altKey) return;
			if (e.key === "p" || e.key === "P") {
				if (scopedHandle) return;
				if (platformOptions.length <= 1) return;
				const currentIndex = platformOptions.findIndex(
					(option) => option.id === platform,
				);
				const next =
					platformOptions[(currentIndex + 1) % platformOptions.length]?.id ??
					platformOptions[0]?.id;
				if (next) setPlatform(next);
			}
		};
		window.addEventListener("keydown", h);
		return () => window.removeEventListener("keydown", h);
	}, [platform, platformOptions, scopedHandle, setPlatform]);

	useEffect(() => {
		if (scopedHandle) return;
		if (platformOptions.some((option) => option.id === urlPlatform)) return;
		const fallback = platformOptions[0]?.id;
		if (fallback) setPlatform(fallback);
	}, [platformOptions, scopedHandle, setPlatform, urlPlatform]);

	const [now, setNow] = useState(() => new Date());
	useEffect(() => {
		const t = window.setInterval(() => setNow(new Date()), 60_000);
		return () => window.clearInterval(t);
	}, []);
	const timeStr = now.toLocaleTimeString("en-US", {
		hour: "numeric",
		minute: "2-digit",
		hour12: false,
	});
	const tzStr =
		new Intl.DateTimeFormat("en-US", { timeZoneName: "short" })
			.formatToParts(now)
			.find((p) => p.type === "timeZoneName")?.value ?? "";
	const fleetPlatform = platformToFleet(platform);
	const dashboardRange = dashboardTimeframeToFleetMetrics(timeframe);
	const topPostsRange = dashboardTimeframeToTopPosts(timeframe);
	const attentionRange = timeframeToAttention(timeframe);
	const kpiData = useFleetKpiData(
		dashboardRange,
		fleetPlatform,
		scopedHandle,
		scopedGroupAccountIds,
		scopedGroupId,
	);
	const fleetMetrics = useFleetMetrics(
		dashboardRange,
		fleetPlatform,
		scopedHandle,
		{ accountIds: scopedGroupAccountIds, groupId: scopedGroupId },
	);
	const topPosts = useTopPosts(
		topPostsRange,
		platformToTopPosts(platform),
		scopedHandle,
		scopedGroupAccountIds,
		scopedGroupId,
	);
	const contentOps = useMemo(
		() => buildContentOperations(topPosts.posts),
		[topPosts.posts],
	);
	const nextUp = useNextUpPosts(
		platformToTopPosts(platform),
		attentionRange,
		scopedHandle,
		scopedGroupAccountIds,
		scopedGroupId,
	);
	const needsAttention = useNeedsAttention(
		platformToTopPosts(platform),
		attentionRange,
		scopedHandle,
		scopedGroupAccountIds,
		scopedGroupId,
	);
	const pendingReplies = usePendingRepliesQueue(
		scopedHandle?.platform === "threads" ? scopedHandle.id : null,
	);
	const dashboardTrend = useMemo(
		() =>
			fleetMetrics.series.slice(-14).map((point) => ({
				label: point.date.slice(5),
				name: point.date,
				value: point.reach,
			})),
		[fleetMetrics.series],
	);
	const topContent = contentOps.winningPosts.slice(0, 4);
	const reviewContent = contentOps.reviewPosts.slice(0, 2);

	if (!authUser) return null;
	if (
		!showMobileOverview &&
		!fleet.isLoading &&
		!fleet.hasError &&
		fleet.accounts === 0
	) {
		return (
			<NovaScreen className="hidden md:flex" width="default">
				<div className="flex flex-col gap-3">
					<PublishingStartCard surface="dashboard_empty" />
					<NovaEmpty
						icon={<Plus data-icon aria-hidden="true" />}
						title="Connect your first account to see your fleet"
						description="Juno33 needs at least one Threads or Instagram account to render the dashboard."
					>
						<div className="flex flex-col items-center gap-3">
							<Badge tone="outline">First run</Badge>
							<Button type="button" onClick={() => navigate("/accounts")}>
								Connect account
							</Button>
						</div>
					</NovaEmpty>
				</div>
			</NovaScreen>
		);
	}

	const scopeCopy = buildScopeCopy({
		scopedAccount: scopedHandle,
		group: selectedGroup,
		accountCount:
			scopedGroupAccountIds?.length ?? (fleet.hasError ? null : fleet.accounts),
		platformLabel: "All accounts",
	});
	const isDashboardProcessing = isSyncing || fleet.isLoading;
	const processingLabel = isSyncing
		? "Refreshing dashboard"
		: fleet.isLoading
			? "Loading accounts"
			: dashboardFetching > 0
				? dashboardFetching > 5
					? "Loading all views"
					: "Updating live data"
				: "Dashboard settled";
	const processingDetail = isSyncing
		? "Requesting fresh metrics while the current dashboard stays visible."
		: fleet.isLoading
			? `Loading account totals, scheduled posts, and ${scopeCopy.emptySubject} context.`
			: dashboardFetching > 0
				? dashboardFetching > 5
					? "All, Threads, and Instagram are loading in the background. Cached data stays visible."
					: `${scopeCopy.header} tiles are updating. Cached data stays visible until the new numbers land.`
				: "Live data is stable. Background syncs will update these tiles automatically.";

	return (
		<>
			{/* Phone-only overview. Tablet and narrow desktop windows keep the
          same Dashboard V2 surface as fullscreen. */}
			{showMobileOverview ? (
				<MobileOverview
					scopedAccount={scopedHandle}
					accountIds={scopedGroupAccountIds}
					groupId={scopedGroupId}
				/>
			) : null}

			<NovaScreen
				className="dashboard-rebuild-screen dv3-root hidden md:flex"
				width="default"
				density="compact"
			>
				<h1 className="sr-only">Dashboard overview</h1>
				<NovaHeader
					eyebrow="Dashboard"
					title="Dashboard"
					description={`Monitor ${scopeCopy.noun}, rebalance attention, and jump into the evidence behind the current ${timeframe.toUpperCase()} window.`}
					meta={`${timeStr} ${tzStr}`}
					variant="board"
					filters={
						<>
							<Badge tone="oxblood">{scopeCopy.chip}</Badge>
							<Badge tone="secondary">
								<BrandLogo
									name={platform === "ig" ? "instagram" : platform === "threads" ? "threads" : "meta"}
									size="xs"
									className="mr-1.5"
								/>
								{platform === "all"
									? "Threads + Instagram"
									: platform === "ig"
										? "Instagram"
										: "Threads"}
							</Badge>
						</>
					}
					actions={
						<div className="flex flex-wrap items-center gap-3">
							<Badge tone="outline" className="hidden xl:inline-flex">Latest · {timeframe.toUpperCase()} rolling</Badge>
							<Button
								type="button"
								variant="outline"
								size="icon"
								onClick={handleSyncNow}
								disabled={isSyncing}
								aria-label="Refresh dashboard data"
							>
								<RefreshCw
									className={isSyncing ? "animate-spin" : undefined}
									aria-hidden="true"
								/>
							</Button>
							<Button
								type="button"
								variant="outline"
								onClick={() =>
									navigate(
										scopedRoute(
											"/analytics",
											{
												scopedAccount: scopedHandle,
												groupId: scopedGroupId,
												accountIds: scopedGroupAccountIds,
												platform,
												timeframe,
											},
											{ source: "dashboard" },
										),
									)
								}
							>
								Analytics
							</Button>
							<Button type="button" onClick={composer.open}>
								<SfPlus size={12} aria-hidden="true" />
								Compose
							</Button>
						</div>
					}
				>
					<div className="flex flex-wrap items-center gap-2">
						{scopedHandle ? (
							<Badge tone="outline">
								{scopedHandle.platform === "instagram" ? "Instagram" : "Threads"}
							</Badge>
						) : (
							<PillSegmented
								ariaLabel="Dashboard platform"
								options={platformOptions}
								value={platform}
								onChange={setPlatform}
							/>
						)}
						<TimeframeSegmented value={timeframe} onChange={setTimeframe} />
					</div>
				</NovaHeader>

				{isDashboardProcessing ? (
					<div
						className="flex flex-col gap-3 rounded-xl border border-primary/35 bg-primary/5 p-3 shadow-sm xl:flex-row xl:items-center xl:justify-between"
						role="status"
						aria-live="polite"
						aria-busy="true"
					>
						<div className="flex min-w-0 items-center gap-3">
							<MatrixLoader
								label={processingLabel}
								size="sm"
								tone={isSyncing ? "default" : "muted"}
								className="mr-1"
							/>
							<div className="min-w-0">
								<div className="truncate text-sm font-semibold text-foreground">{processingLabel}</div>
								<div className="truncate text-sm text-muted-foreground">{processingDetail}</div>
							</div>
						</div>
						<div className="hidden flex-wrap items-center gap-2 xl:flex" aria-hidden="true">
							<ProcessingPhase
								label="Accounts"
								active={fleet.isLoading}
								done={!fleet.isLoading && !fleet.hasError}
							/>
							<ProcessingPhase
								label="Metrics"
								active={dashboardFetching > 0 || isSyncing}
								done={false}
							/>
							<ProcessingPhase
								label="Insights"
								active={dashboardFetching > 2}
								done={false}
							/>
						</div>
					</div>
				) : null}

				{/* Dashboard bands keep the existing real data tiles and footprints;
				    the dv3 scope only changes the color/material language. */}
				<section aria-label="Dashboard tiles">
					{/* === ALL VIEW (10 tiles) === */}
					{platform === "all" && (
							<DailyDashboardAllView
								kpiData={kpiData}
								fleetMetrics={fleetMetrics}
								needsAttention={needsAttention}
							pendingReplies={pendingReplies}
							nextUp={nextUp}
							topPosts={topPosts}
							contentOps={contentOps}
							topContent={topContent}
							reviewContent={reviewContent}
								dashboardTrend={dashboardTrend}
								timeframe={timeframe}
								scopeLabel={scopeCopy.header}
								onOpenContent={() => navigate("/content")}
								onOpenCalendar={() => navigate("/calendar")}
								onOpenInbox={() => navigate("/inbox")}
								onOpenAccounts={() => navigate("/accounts")}
							onCompose={composer.open}
						/>
					)}

					{/* === THREADS VIEW (8 tiles) === */}
					{platform === "threads" && (
						<>
							{/* Band 0 — Hero (12, full-width) per mockup line 565 */}
							<div className="grid gap-4 lg:grid-cols-12">
								<div className="lg:col-span-12">
									<TileErrorBoundary scope="dv2:hero">
										<HeroTile
											platform={platform}
											timeframe={timeframe}
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
											scopeLabel={scopeCopy.header}
										/>
									</TileErrorBoundary>
								</div>
							</div>
							<FundamentalsRibbon
								platform={platform}
								timeframe={timeframe}
								scopedAccount={scopedHandle}
								accountIds={scopedGroupAccountIds}
								groupId={scopedGroupId}
							/>
							<BandHeader
								label="Conversation attention"
								title="Conversation quality · ghost count"
							/>
							<div className="grid gap-4 lg:grid-cols-12">
								<div className="lg:col-span-8">
									<TileErrorBoundary scope="dv2:conversation-quality">
										<ConversationQualityTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
								<div className="lg:col-span-4">
									<TileErrorBoundary scope="dv2:ghost-count">
										<GhostCountTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
							</div>
							{/* Band 2 — Reply-depth leaders (12, Mosseri-confirmed) */}
							<BandHeader
								label="Conversation leaders"
								title="Reply-depth leaders"
							/>
							<div className="grid gap-4 lg:grid-cols-12">
								<div className="lg:col-span-12">
									<TileErrorBoundary scope="dv2:reply-depth-leaders">
										<ReplyDepthLeadersTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
							</div>
							{/* Band 3 — Conv winner (4) + Held replies (4) + Suppression (4) */}
							<BandHeader
								label="Operations"
								title="Deepest thread · moderation · reach drops"
							/>
							<div className="grid gap-4 lg:grid-cols-12">
								<div className="lg:col-span-6">
									<TileErrorBoundary scope="dv2:conversation-winner">
										<ConversationWinnerTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
								<div className="flex flex-col gap-4 lg:col-span-6">
									<div className="min-h-0">
										<TileErrorBoundary scope="dv2:ai-costs">
											<AICostMetricsTile />
										</TileErrorBoundary>
									</div>
									<div className="min-h-0">
										<TileErrorBoundary scope="dv2:held-replies">
											<HeldRepliesQueueTile
												scopedAccount={scopedHandle}
												accountIds={scopedGroupAccountIds}
												groupId={scopedGroupId}
											/>
										</TileErrorBoundary>
									</div>
									<div className="min-h-0">
										<TileErrorBoundary scope="dv2:suppression-dark-threads">
											<SuppressionDarkTile
												variant="threads"
												scopedAccount={scopedHandle}
												accountIds={scopedGroupAccountIds}
												groupId={scopedGroupId}
											/>
										</TileErrorBoundary>
									</div>
								</div>
							</div>
							{/* Band 4 — Views source provenance + Streak[Threads] */}
							<BandHeader
								label="Source evidence"
								title="Views provenance · streak"
							/>
							<div className="grid gap-4 lg:grid-cols-12">
								<div className="lg:col-span-8">
									<TileErrorBoundary scope="dv2:views-by-source">
										<ViewsBySourceStripTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
								<div className="lg:col-span-4">
									<TileErrorBoundary scope="dv2:streak-threads">
										<StreakTile
											platform="threads"
											variant="compact"
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
							</div>
						</>
					)}

					{/* === IG VIEW (11 tiles) === */}
					{platform === "ig" && (
						<>
							{/* Band 0 — Hero (12, full-width) per mockup line 594 */}
							<div className="grid gap-4 lg:grid-cols-12">
								<div className="lg:col-span-12">
									<TileErrorBoundary scope="dv2:hero">
										<HeroTile
											platform={platform}
											timeframe={timeframe}
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
											scopeLabel={scopeCopy.header}
										/>
									</TileErrorBoundary>
								</div>
							</div>
							<FundamentalsRibbon
								platform={platform}
								timeframe={timeframe}
								scopedAccount={scopedHandle}
								accountIds={scopedGroupAccountIds}
								groupId={scopedGroupId}
							/>
							<BandHeader
								label="Share attention"
								title="Share rate · watch-time · non-follower"
							/>
							<div className="grid gap-4 lg:grid-cols-12">
								<div className="lg:col-span-3">
									<TileErrorBoundary scope="dv2:sends-per-reach-bullet">
										<SendsPerReachBulletDarkTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
								<div className="lg:col-span-4">
									<TileErrorBoundary scope="dv2:watch-per-view">
										<WatchPerViewTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
								<div className="lg:col-span-5">
									<TileErrorBoundary scope="dv2:non-follower-reach-ig">
										<NonFollowerReachTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
							</div>
							{/* Band 2 — Sends-per-reach leaders (12, Mosseri #1 leaderboard) */}
							<BandHeader
								label="Performance leaders"
								title="Sends-per-reach leaders · save rate"
							/>
							<div className="grid gap-4 lg:grid-cols-12">
								<div className="lg:col-span-8">
									<TileErrorBoundary scope="dv2:sends-per-reach-leaders">
										<SendsPerReachLeadersTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
								<div className="lg:col-span-4">
									<TileErrorBoundary scope="dv2:save-rate-top-bottom">
										<SaveRateTopBottomTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
							</div>
							{/* Band 3 — IG trio: content mix (4) + stories funnel (4) + hook strength (4). */}
							<BandHeader
								label="Content signals"
								title="Content mix · stories funnel · hook strength"
							/>
							<div className="grid gap-4 lg:grid-cols-12">
								<div className="lg:col-span-4">
									<TileErrorBoundary scope="dv2:content-mix-health">
										<ContentMixHealthTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
								<div className="lg:col-span-4">
									<TileErrorBoundary scope="dv2:stories-funnel">
										<StoriesFunnelTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
								<div className="lg:col-span-4">
									<TileErrorBoundary scope="dv2:hook-strength">
										<HookStrengthTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
							</div>
							{/* Band 4 — lower-priority research checks. Profile visits stays off-dashboard until prod captures non-zero profile_activity. */}
							<BandHeader
								label="What to review"
								title="Performance signals · vanity gap · streak"
							/>
							<div className="grid gap-4 lg:grid-cols-12">
								<div className="lg:col-span-5">
									<TileErrorBoundary scope="dv2:quality-signal-bullets">
										<QualitySignalBulletsTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
								<div className="lg:col-span-4">
									<TileErrorBoundary scope="dv2:vanity-flag">
										<VanityFlagTile
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
								<div className="lg:col-span-3">
									<TileErrorBoundary scope="dv2:streak-ig">
										<StreakTile
											platform="ig"
											variant="compact"
											scopedAccount={scopedHandle}
											accountIds={scopedGroupAccountIds}
											groupId={scopedGroupId}
										/>
									</TileErrorBoundary>
								</div>
							</div>
						</>
					)}
				</section>
			</NovaScreen>
		</>
	);
}

function ProcessingPhase({
	label,
	active,
	done,
}: {
	label: string;
	active: boolean;
	done: boolean;
}) {
	return (
		<Badge tone={active ? "oxblood" : done ? "secondary" : "outline"}>
			{label}
		</Badge>
	);
}

function DailyDashboardAllView({
	kpiData,
	fleetMetrics,
	needsAttention,
	pendingReplies,
	nextUp,
	topPosts,
	topContent,
	reviewContent,
	dashboardTrend,
	timeframe,
	scopeLabel,
	onOpenContent,
	onOpenCalendar,
	onOpenInbox,
	onOpenAccounts,
	onCompose,
}: {
	kpiData: ReturnType<typeof useFleetKpiData>;
	fleetMetrics: ReturnType<typeof useFleetMetrics>;
	needsAttention: ReturnType<typeof useNeedsAttention>;
	pendingReplies: ReturnType<typeof usePendingRepliesQueue>;
	nextUp: ReturnType<typeof useNextUpPosts>;
	topPosts: ReturnType<typeof useTopPosts>;
	contentOps: ReturnType<typeof buildContentOperations>;
	topContent: TopPostRow[];
	reviewContent: TopPostRow[];
	dashboardTrend: Array<{ label: string; name: string; value: number }>;
	timeframe: DashboardTimeframe;
	scopeLabel: string;
	onOpenContent: () => void;
	onOpenCalendar: () => void;
	onOpenInbox: () => void;
	onOpenAccounts: () => void;
	onCompose: () => void;
}) {
	const isMetricLoading = kpiData.isLoading || fleetMetrics.isLoading;
	const primaryViews = kpiData.reach || fleetMetrics.totalReach;
	const attentionCount =
		needsAttention.totalCount +
		needsAttention.gapsCount +
		pendingReplies.needsReview +
		(fleetMetrics.scheduleCompliance != null && fleetMetrics.scheduleCompliance < 100 ? 1 : 0);
	const inboxTone = pendingReplies.needsReview > 0 ? "danger" : pendingReplies.pending > 0 ? "warning" : "default";
	const topPost = topContent[0] ?? null;
	const likelyDriver =
		topPost && primaryViews > 0
			? `${topPost.accountHandle ? `@${topPost.accountHandle}` : "A top post"} is carrying the strongest content signal in this window.`
			: "Publish more posts or widen the date range to identify the strongest driver.";

	return (
		<>
			<NovaSection
				aria-label="Daily performance"
				className="grid gap-3 md:grid-cols-2 xl:grid-cols-5"
			>
				<DashboardKpiCard
					label="Views"
					value={formatCompact(primaryViews)}
					description="Best available views or reach across the selected accounts."
					trendValue={kpiData.reachDelta ?? fleetMetrics.reachDeltaPct}
					icon={Eye}
					footerLabel="Window"
					footerValue={timeframe.toUpperCase()}
					loading={isMetricLoading}
				/>
				<DashboardKpiCard
					label="People reached"
					value={formatCompact(kpiData.reach || fleetMetrics.totalReach)}
					description="Reach-backed audience movement for this scope."
					trendValue={kpiData.reachDelta ?? fleetMetrics.reachDeltaPct}
					icon={Users}
					footerLabel="Scope"
					footerValue={scopeLabel}
					loading={isMetricLoading}
				/>
				<DashboardKpiCard
					label="Engagement rate"
					value={formatPercent(kpiData.engagementRate)}
					description={`${formatCompact(kpiData.totalInteractions)} likes, replies, saves, sends, and shares.`}
					trendValue={kpiData.engagementRateDelta}
					icon={TrendingUp}
					footerLabel="Interactions"
					footerValue={formatCompact(kpiData.totalInteractions)}
					loading={kpiData.isLoading}
				/>
				<DashboardKpiCard
					label="New followers"
					value={formatPercent(fleetMetrics.followerGrowthPct)}
					description="Follower growth compared with the previous window."
					trendValue={fleetMetrics.followerGrowthDeltaPct}
					icon={Sparkles}
					footerLabel="Growth"
					footerValue={formatPercent(fleetMetrics.followerGrowthPct)}
					loading={fleetMetrics.isLoading}
				/>
				<DashboardKpiCard
					label="Link clicks"
					value={formatCompact(kpiData.totalClicks)}
					description="Website and smart-link activity from published content."
					trendValue={kpiData.totalClicksDelta}
					icon={MousePointerClick}
					footerLabel="Smart links"
					footerValue={formatCompact(kpiData.totalClicks)}
					loading={kpiData.isLoading}
				/>
			</NovaSection>

			<NovaSection className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
				<NovaDataPanel
					title="What needs attention"
					description={`Priority work for ${scopeLabel.toLowerCase()} before the next post goes out.`}
					toolbar={
						<Badge tone={attentionCount > 0 ? "danger" : "secondary"}>
							{attentionCount > 0 ? `${attentionCount} items` : "Clear"}
						</Badge>
					}
					footer={
						<div className="flex w-full flex-wrap items-center gap-2">
							<Button type="button" variant="outline" size="sm" onClick={onOpenInbox}>
								Open inbox
							</Button>
							<Button type="button" variant="outline" size="sm" onClick={onOpenCalendar}>
								Review schedule
							</Button>
							<Button type="button" size="sm" onClick={onOpenAccounts}>
								Fix accounts
							</Button>
						</div>
					}
					loading={needsAttention.isLoading || pendingReplies.isLoading}
					empty={
						<NovaEmpty
							title="No urgent work right now"
							description="Accounts, replies, and posting gaps look clear for this window."
							icon={<CheckCircle2 aria-hidden="true" />}
						/>
					}
				>
					<div className="grid gap-3 lg:grid-cols-2">
						<NovaMiniStat
							label="Waiting for reply"
							value={formatCompact(pendingReplies.pending)}
							description={`${formatCompact(pendingReplies.needsReview)} need review`}
							tone={inboxTone}
						/>
						<NovaMiniStat
							label="Days with no posts scheduled"
							value={formatCompact(needsAttention.gapsCount)}
							description="Accounts without near-term scheduled posts"
							tone={needsAttention.gapsCount > 0 ? "warning" : "default"}
						/>
						<NovaMiniStat
							label="Failed posts"
							value={
								fleetMetrics.scheduleCompliance == null
									? "Unavailable"
									: fleetMetrics.scheduleCompliance < 100
										? "Review"
										: "0"
							}
							description="Uses published / attempted signal"
							tone={
								fleetMetrics.scheduleCompliance != null && fleetMetrics.scheduleCompliance < 100
									? "danger"
									: "default"
							}
						/>
						<NovaMiniStat
							label="Posts scheduled this week"
							value={formatCompact(nextUp.totalQueue)}
							description="Upcoming scheduled queue"
							tone={nextUp.totalQueue > 0 ? "success" : "warning"}
						/>
					</div>
					{needsAttention.items.length > 0 ? (
						<div className="mt-4 grid gap-2">
							{needsAttention.items.slice(0, 3).map((item) => (
								<NovaListRow
									key={`${item.platform}-${item.id}`}
									leading={
										<BrandLogo
											name={item.platform === "instagram" ? "instagram" : "threads"}
											size="xs"
											monochrome
										/>
									}
									title={item.handle}
									description={item.issue}
									meta={<Badge tone={item.severity === "crit" ? "danger" : "outline"}>{item.action}</Badge>}
									action={
										<Button type="button" variant="ghost" size="sm" onClick={onOpenAccounts}>
											Open
										</Button>
									}
									tone={item.severity === "crit" ? "danger" : "warning"}
								/>
							))}
						</div>
					) : null}
				</NovaDataPanel>

				<NovaCard
					title="Inbox queue"
					description="Replies and conversations that may need a human pass."
					action={<Badge tone={inboxTone === "danger" ? "danger" : "outline"}>{formatCompact(pendingReplies.pending)} waiting</Badge>}
					footer={
						<Button type="button" variant="outline" size="sm" onClick={onOpenInbox}>
							Open inbox
							<ExternalLink data-icon="inline-end" aria-hidden="true" />
						</Button>
					}
				>
					<div className="grid gap-3">
						<NovaMiniStat
							label="Waiting for reply"
							value={formatCompact(pendingReplies.pending)}
							description={`${formatCompact(pendingReplies.total)} total queued conversations`}
							tone={inboxTone}
						/>
						<NovaMiniStat
							label="Needs review"
							value={formatCompact(pendingReplies.needsReview)}
							description="Safety or routing checks"
							tone={pendingReplies.needsReview > 0 ? "danger" : "default"}
						/>
						{pendingReplies.accounts.slice(0, 2).map((account) => (
							<NovaListRow
								key={account.accountId}
								leading={<MessageCircle aria-hidden="true" />}
								title={account.username ? `@${account.username}` : "Account"}
								description={account.topReason ?? "Pending conversation"}
								meta={<Badge tone="secondary">{formatCompact(account.pending)}</Badge>}
							/>
						))}
					</div>
				</NovaCard>
			</NovaSection>

			<NovaSection className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
				<NovaCard
					title="What changed"
					description={`Views, interactions, and follower movement across the current ${timeframe.toUpperCase()} window.`}
					action={<Badge tone="outline">{timeframe.toUpperCase()}</Badge>}
					footer={
						<div className="grid w-full gap-3 sm:grid-cols-3">
							<NovaMiniStat
								label="Views"
								value={formatCompact(primaryViews)}
								trend={formatDelta(kpiData.reachDelta ?? fleetMetrics.reachDeltaPct)}
							/>
							<NovaMiniStat
								label="Engagement rate"
								value={formatPercent(kpiData.engagementRate)}
								trend={formatDelta(kpiData.engagementRateDelta)}
							/>
							<NovaMiniStat
								label="New followers"
								value={formatPercent(fleetMetrics.followerGrowthPct)}
								trend={formatDelta(fleetMetrics.followerGrowthDeltaPct)}
							/>
						</div>
					}
				>
					{fleetMetrics.isLoading ? (
						<NovaEmpty
							title="Loading trend"
							description="The latest daily performance series is still updating."
							icon={<BarChart3 aria-hidden="true" />}
						/>
					) : dashboardTrend.length > 0 ? (
						<div className="grid gap-4">
							<JunoBarChart
								ariaLabel="Views trend"
								data={dashboardTrend}
								valueLabel="Views"
								valueFormatter={formatCompact}
							/>
							<div className="rounded-lg border border-border bg-muted/35 p-3 text-sm leading-relaxed text-muted-foreground">
								<span className="font-medium text-foreground">Likely driver: </span>
								{likelyDriver}
							</div>
						</div>
					) : (
						<NovaEmpty
							title="No trend yet"
							description="Publish posts or widen the date range to compare movement."
							icon={<BarChart3 aria-hidden="true" />}
						/>
					)}
				</NovaCard>

				<NovaCard
					title="Publishing runway"
					description="What is scheduled next and where gaps may slow momentum."
					action={<Badge tone={nextUp.totalQueue > 0 ? "secondary" : "outline"}>{formatCompact(nextUp.totalQueue)} scheduled</Badge>}
					footer={
						<div className="flex w-full flex-wrap gap-2">
							<Button type="button" variant="outline" size="sm" onClick={onOpenCalendar}>
								Open calendar
							</Button>
							<Button type="button" size="sm" onClick={onCompose}>
								Create post
							</Button>
						</div>
					}
				>
					{nextUp.isLoading ? (
						<NovaEmpty
							title="Checking schedule"
							description="Looking for the next posts in queue."
							icon={<CalendarClock aria-hidden="true" />}
						/>
					) : nextUp.items.length > 0 ? (
						<div className="grid gap-2">
							{nextUp.items.map((item) => (
								<NovaListRow
									key={item.id}
									leading={
										<BrandLogo
											name={item.platform === "instagram" ? "instagram" : "threads"}
											size="xs"
											monochrome
										/>
									}
									title={item.text || "Scheduled post"}
									description={`${item.handle} · ${item.time}`}
									meta={<Badge tone={item.isAccent ? "oxblood" : "secondary"}>{item.platform === "instagram" ? "IG" : "Threads"}</Badge>}
								/>
							))}
						</div>
					) : (
						<NovaEmpty
							title="No posts scheduled soon"
							description="Create or schedule the next post before the runway goes cold."
							icon={<Clock3 aria-hidden="true" />}
							action={<Button type="button" onClick={onCompose}>Create post</Button>}
						/>
					)}
				</NovaCard>
			</NovaSection>

			<NovaSection className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
				<NovaDataPanel
					title="Top posts"
					description="The strongest mature content signals in this scope."
					toolbar={
						<Button type="button" variant="outline" size="sm" onClick={onOpenContent}>
							View all content
							<ExternalLink data-icon="inline-end" aria-hidden="true" />
						</Button>
					}
					loading={topPosts.isLoading}
					empty={
						<NovaEmpty
							title="No top posts yet"
							description="Published content will appear here once synced metrics are available."
							icon={<FileText aria-hidden="true" />}
						/>
					}
				>
					<div className="grid gap-2">
						{topContent.map((post) => (
							<DashboardPostRow key={post.id} post={post} />
						))}
					</div>
				</NovaDataPanel>

				<NovaCard
					title="Posts to review"
					description="Mature posts below this window's baseline."
					action={<Badge tone={reviewContent.length > 0 ? "outline" : "secondary"}>{reviewContent.length > 0 ? `${reviewContent.length} review` : "Clear"}</Badge>}
				>
					{reviewContent.length > 0 ? (
						<div className="grid gap-2">
							{reviewContent.map((post) => (
								<NovaListRow
									key={post.id}
									leading={<TriangleAlert aria-hidden="true" />}
									title={post.caption || "Untitled post"}
									description={`${post.accountHandle ? `@${post.accountHandle}` : "Account"} · ${formatCompact(post.reach)} views · ${formatCompact(engagementTotal(post))} engagements`}
									meta={<Badge tone="outline">Review</Badge>}
									tone="warning"
								/>
							))}
						</div>
					) : (
						<NovaEmpty
							title="No obvious underperformers"
							description="The current sample has no mature posts below the review threshold."
							icon={<CheckCircle2 aria-hidden="true" />}
						/>
					)}
				</NovaCard>
			</NovaSection>

		</>
	);
}

function DashboardPostRow({ post }: { post: TopPostRow }) {
	const platformName = post.platform === "instagram" ? "instagram" : "threads";
	return (
		<NovaListRow
			leading={
				post.mediaUrl ? (
					<img
						src={post.mediaUrl}
						alt=""
						loading="lazy"
						decoding="async"
						className="size-full rounded-md object-cover"
					/>
				) : (
					<BrandLogo name={platformName} size="xs" monochrome />
				)
			}
			title={post.caption || "Untitled post"}
			description={`${post.accountHandle ? `@${post.accountHandle}` : "Account"} · ${postDateLabel(post.publishedAt)} · ${formatCompact(post.reach)} views · ${formatCompact(engagementTotal(post))} engagements`}
			meta={
				<div className="flex items-center gap-2">
					<Badge tone={post.platform === "instagram" ? "oxblood" : "secondary"}>
						{post.platform === "instagram" ? "IG" : "Threads"}
					</Badge>
					<Badge tone="outline">{formatCompact(discoveryScore(post))} signal</Badge>
				</div>
			}
			progress={Math.min(100, Math.max(4, engagementTotal(post)))}
			progressLabel="Engagement signal"
		/>
	);
}
