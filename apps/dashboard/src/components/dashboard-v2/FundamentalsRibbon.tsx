// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useEffect, useMemo, useState } from "react";
import { useFleetMetrics } from "@/hooks/useFleetMetrics";
import { useFollowerAttribution } from "@/hooks/useFollowerAttribution";
import { useQuoteReplyRatio } from "@/hooks/useQuoteReplyRatio";
import { useGhostPostCount } from "@/hooks/useGhostPostCount";
import { useStoryActivity } from "@/hooks/useStoryActivity";
import { useFollowerTotals } from "@/hooks/useFollowerTotals";
import { Skeleton } from "@/components/ui/Skeleton";
import {
	EMPTY_THREAD_TOTALS,
	useThreadsPostTotals,
} from "@/hooks/useThreadsPostTotals";
import {
	dashboardTimeframeToDays,
	dashboardTimeframeToFleetMetrics,
	type DashboardTimeframe,
} from "@/lib/dashboardUrlState";
import { pct } from "@/lib/displayValue";
import { cn } from "@/lib/utils";
import {
	fleetPlatformFor,
	formatCompact,
	formatReachDeltaLabel,
	isTinyBaselineDelta,
	type Platform,
} from "./shared";
import type { DashboardScopeProps } from "./scope";

interface Props extends DashboardScopeProps {
	platform: Platform;
	timeframe: DashboardTimeframe;
}

interface RibbonCard {
	label: string;
	value: string;
	/** Optional secondary line — short delta or status hint. */
	hint: string;
	/** When set, the hint renders in success/warning/error tone. */
	hintTone?: "pos" | "warn" | "bad" | "neutral" | undefined;
	/** Lead tile gets an oxblood top-underline (mockup pattern). */
	lead?: boolean | undefined;
	/**
	 * No data yet (loading, error, no posts in window, no follows recorded,
	 * etc.). Renders the tile muted, but with an explicit value/hint so the
	 * ribbon does not look broken when a window has no usable rows. Positive-zero
	 * states (`ghosts === 0` → 'fleet clean') are NOT empty — they show the real
	 * `0` and keep the success word.
	 */
	isEmpty?: boolean | undefined;
	emptyValue?: string | undefined;
	emptyHint?: string | undefined;
}

/**
 * Fundamentals ribbon — ONE unified bento card capped at 5 internal-divider
 * tiles. This follows the validated mockup correction: the old 8-cell row
 * overfilled the first viewport and made secondary metrics look more
 * important than the actual decision signals.
 *
 * Per-platform metrics:
 *   ALL:     Engagements · Followers · Posts · Share rate · Reactions
 *   THREADS: Views 30d · Followers · Reply depth · Quote/reply · Ghosts
 *   IG:      Reach 30d · Followers · Share rate · Saves/reach · Story views
 */
export function FundamentalsRibbon({
	platform,
	timeframe,
	scopedAccount = null,
	accountIds,
	groupId,
}: Props) {
	const [skeletonReleased, setSkeletonReleased] = useState(false);
	const fleetPlatform = fleetPlatformFor(platform);
	const days = dashboardTimeframeToDays(timeframe);
	const timeframeLabel = timeframe.toUpperCase();
	const metricsTimeframe = dashboardTimeframeToFleetMetrics(timeframe);
	const metrics = useFleetMetrics(
		metricsTimeframe,
		fleetPlatform,
		scopedAccount,
		{ accountIds, groupId },
	);
	const scopedIds = useMemo(
		() => (scopedAccount ? [scopedAccount.id] : accountIds),
		[accountIds, scopedAccount],
	);
	const threadScopedIds = useMemo(
		() =>
			scopedAccount
				? scopedAccount.platform === "threads"
					? [scopedAccount.id]
					: []
				: accountIds,
		[accountIds, scopedAccount],
	);
	const igScopedIds = useMemo(
		() =>
			scopedAccount
				? scopedAccount.platform === "instagram"
					? [scopedAccount.id]
					: []
				: accountIds,
		[accountIds, scopedAccount],
	);
	const followerAttr = useFollowerAttribution(
		days,
		platform === "threads" ? "threads" : platform === "ig" ? "instagram" : null,
		scopedAccount,
		accountIds,
		groupId,
	);
	const followerTotals = useFollowerTotals(
		platform === "threads"
			? "threads"
			: platform === "ig"
				? "instagram"
				: "all",
		scopedIds,
	);
	const qr = useQuoteReplyRatio(
		days,
		scopedAccount?.platform === "threads" ? scopedAccount.id : null,
		threadScopedIds,
	);
	const ghosts = useGhostPostCount(threadScopedIds);
	const story = useStoryActivity(days, igScopedIds);
	const threadPostTotals = useThreadsPostTotals(days, threadScopedIds);
	const isCrossPlatform = platform === "all";

	const totals = useMemo(() => {
		const t = {
			views: 0,
			likes: 0,
			comments: 0,
			posts: 0,
			saves: 0,
			sends: 0,
			reposts: 0,
			quotes: 0,
		};
		for (const a of metrics.accounts) {
			t.views += a.reach;
			t.likes += a.likes;
			t.comments += a.comments;
			t.posts += a.posts;
			t.saves += a.saves;
			t.sends += a.sends;
			const r = (a as { reposts?: number | undefined }).reposts ?? 0;
			const q = (a as { quotes?: number | undefined }).quotes ?? 0;
			t.reposts += r;
			t.quotes += q;
		}
		// `useFleetMetrics` exposes both fleet totals and per-account aggregates.
		// The ribbon should prefer the richer per-account breakdown, but the 30d
		// RPC can still return usable aggregate totals before every account row is
		// hydrated. Do not collapse the KPI ribbon to dashes in that case.
		if (t.views === 0 && t.posts === 0) {
			t.views = metrics.totalReach;
			t.posts = metrics.postCount;
			t.sends = metrics.sendsPlusSaves;
		}
		return t;
	}, [metrics.accounts, metrics.postCount, metrics.sendsPlusSaves, metrics.totalReach]);

	const todaysFollows =
		followerAttr.days.length > 0
			? followerAttr.days[followerAttr.days.length - 1]!.followerGrowth
			: 0;
	const cumulativeFollowers = followerTotals.total;

	const sendsPerReach =
		totals.views > 0 ? (totals.sends / totals.views) * 100 : null;
	const saveRate =
		totals.views > 0 ? (totals.saves / totals.views) * 100 : null;

	const cards: RibbonCard[] = useMemo(() => {
		const metricsUnavailable = metrics.isLoading || metrics.hasError;
		const threadFallback = threadPostTotals.data ?? EMPTY_THREAD_TOTALS;
		const hasThreadFallback =
			platform === "threads" && threadFallback.posts > 0;
		const effectiveTotals = hasThreadFallback
			? {
					...totals,
					views: threadFallback.views,
					comments: threadFallback.replies,
					likes: threadFallback.likes,
					reposts: threadFallback.reposts,
					quotes: threadFallback.quotes,
					posts: threadFallback.posts,
				}
			: totals;
		// Fleet-wide "no data yet" — covers loading, error, and zero-posts-in-window.
		// Each card layers its own secondary empty checks (e.g., qr.fleetRatio == null)
		// on top of this. All collapse to the unified isEmpty path:
		// explicit empty values/hints. Positive-zero states (ghosts === 0 →
		// 'fleet clean') stay loud — they're positive empty, not data-missing.
		const fleetNoData =
			!hasThreadFallback &&
			(metricsUnavailable ||
				(effectiveTotals.views === 0 && effectiveTotals.posts === 0));
		const emptyReason = metrics.hasError ? "metrics retry needed" : "no posts in window";

		const reachDeltaStr =
			!metricsUnavailable &&
			!hasThreadFallback &&
			effectiveTotals.views > 0 &&
			metrics.reachDeltaPct != null &&
			Number.isFinite(metrics.reachDeltaPct)
				? formatReachDeltaLabel(metrics.reachDeltaPct, 1)
				: null;
		const reachDeltaTone: RibbonCard["hintTone"] | undefined =
			metrics.reachDeltaPct == null
				? undefined
				: metrics.reachDeltaPct > 0
					? "pos"
					: metrics.reachDeltaPct < 0
						? "bad"
						: "neutral";

		const reachCard: RibbonCard = {
			label:
				platform === "threads"
					? `Views ${timeframeLabel}`
					: `Reach ${timeframeLabel}`,
			value: fleetNoData ? (metrics.hasError ? "Retry" : "0") : formatCompact(effectiveTotals.views),
			hint: reachDeltaStr
				? isTinyBaselineDelta(metrics.reachDeltaPct)
					? reachDeltaStr
					: `${reachDeltaStr}% vs ${timeframeLabel}`
				: hasThreadFallback
					? `${threadFallback.posts.toLocaleString()} posts`
					: `vs ${timeframeLabel}`,
			hintTone: hasThreadFallback ? "neutral" : reachDeltaTone,
			lead: true,
			isEmpty: fleetNoData,
			emptyValue: metrics.hasError ? "Retry" : "0",
			emptyHint: emptyReason,
		};

		const followsEmpty =
			followerTotals.isLoading ||
			followerTotals.hasError ||
			(cumulativeFollowers <= 0 && todaysFollows === 0);
		const followsCard: RibbonCard = {
			label: "Followers",
			value:
				cumulativeFollowers > 0
					? formatCompact(cumulativeFollowers)
					: todaysFollows !== 0
						? `${todaysFollows >= 0 ? "+" : ""}${todaysFollows.toLocaleString()}`
						: "0",
			hint:
				todaysFollows !== 0
					? `${todaysFollows >= 0 ? "+" : ""}${todaysFollows.toLocaleString()} today`
					: followerAttr.hasError
						? "synced total"
						: "no change today",
			hintTone:
				todaysFollows > 0 ? "pos" : todaysFollows < 0 ? "bad" : "neutral",
			isEmpty: followsEmpty,
			emptyValue: "0",
			emptyHint: followerTotals.hasError ? "sync needed" : "no follower snapshot",
		};

		if (platform === "threads") {
			const replyDepth =
				effectiveTotals.posts > 0 && effectiveTotals.comments > 0
					? effectiveTotals.comments / effectiveTotals.posts
					: null;
			return [
				reachCard,
				followsCard,
				{
					label: "Avg replies / post",
					value: replyDepth != null ? replyDepth.toFixed(1) : "0.0",
					hint: "replies ÷ posts",
					hintTone: replyDepth != null && replyDepth > 2 ? "pos" : "neutral",
					isEmpty: replyDepth == null,
					emptyValue: "0.0",
					emptyHint: "no replies yet",
				},
				{
					label: "Quote/reply",
					value: qr.fleetRatio != null ? `${qr.fleetRatio.toFixed(2)}×` : "0.00×",
					hint: "quotes ÷ replies",
					hintTone: "neutral",
					isEmpty: qr.fleetRatio == null,
					emptyValue: "0.00×",
					emptyHint: "no quote/reply sample",
				},
				{
					// Positive-zero: ghosts.total === 0 is "fleet clean", NOT empty.
					label: "Ghosts",
					value: ghosts.isLoading ? "Sync" : ghosts.total.toString(),
					hint:
						ghosts.total === 0
							? "fleet clean"
							: `${effectiveTotals.posts > 0 ? `${Math.round((ghosts.total / effectiveTotals.posts) * 100)}% of posts · ` : ""}${
									ghosts.weekOverWeekDelta < 0
										? `${ghosts.weekOverWeekDelta} weekly`
										: `+${ghosts.weekOverWeekDelta} weekly`
								}`,
					hintTone:
						ghosts.total === 0
							? "pos"
							: ghosts.weekOverWeekDelta > 0
								? "bad"
								: "warn",
					isEmpty: ghosts.isLoading,
					emptyValue: "0",
					emptyHint: "checking",
				},
			];
		}

		if (platform === "ig") {
			return [
				reachCard,
				followsCard,
				{
					label: "Share rate",
					value: pct(sendsPerReach, 2),
					hint:
						sendsPerReach == null
							? "sends ÷ reach"
							: sendsPerReach >= 1
								? "strong"
								: sendsPerReach >= 0.5
									? "active"
									: "low",
					hintTone:
						sendsPerReach != null && sendsPerReach >= 1 ? "pos" : "neutral",
					isEmpty: sendsPerReach == null,
					emptyValue: "0.00%",
					emptyHint: "no sends yet",
				},
				{
					label: "Saves/reach",
					value: pct(saveRate, 2),
					hint:
						saveRate == null
							? "quality signal"
							: saveRate > 4
								? "strong"
								: saveRate > 1
									? "active"
									: "low",
					hintTone: saveRate != null && saveRate > 1 ? "pos" : "neutral",
					isEmpty: saveRate == null,
					emptyValue: "0.00%",
					emptyHint: "no saves yet",
				},
				{
					label: "Story views",
					value:
						story.totalImpressions > 0
							? formatCompact(story.totalImpressions)
							: "0",
					hint: `last ${timeframeLabel}`,
					isEmpty: story.isLoading || story.totalImpressions === 0,
					emptyValue: story.isLoading ? "Syncing" : "0",
					emptyHint: story.isLoading ? "story sync" : "no story views",
				},
			];
		}

		// ALL view — fleet-wide metrics
		const engagementTotal =
			effectiveTotals.likes +
			effectiveTotals.comments +
			effectiveTotals.saves +
			effectiveTotals.sends;
		return [
			{
				label: "Engagements",
				value: engagementTotal > 0 ? formatCompact(engagementTotal) : "0",
				hint: "likes + replies + saves + sends",
				hintTone: engagementTotal > 0 ? "pos" : "neutral",
				lead: true,
				isEmpty: fleetNoData || engagementTotal === 0,
				emptyValue: metrics.hasError ? "Retry" : "0",
				emptyHint: metrics.hasError ? "metrics retry needed" : "no engagement yet",
			},
			followsCard,
			{
				label: "Posts",
				value: effectiveTotals.posts > 0 ? formatCompact(effectiveTotals.posts) : "0",
				hint: `${timeframeLabel} sample size`,
				hintTone: effectiveTotals.posts > 0 ? "neutral" : "warn",
				isEmpty: fleetNoData || effectiveTotals.posts === 0,
				emptyValue: "0",
				emptyHint: metrics.hasError ? "metrics retry needed" : `${timeframeLabel} sample size`,
			},
			{
				label: "Share rate",
				value: pct(sendsPerReach, 2),
				hint:
					sendsPerReach == null
						? `sends ÷ reach${isCrossPlatform ? " · cross-platform" : ""}`
						: sendsPerReach >= 1
							? `strong${isCrossPlatform ? " · cross-platform" : ""}`
							: sendsPerReach >= 0.5
								? `active${isCrossPlatform ? " · cross-platform" : ""}`
								: `low${isCrossPlatform ? " · cross-platform" : ""}`,
				hintTone:
					sendsPerReach != null && sendsPerReach >= 1 ? "pos" : "neutral",
				isEmpty: sendsPerReach == null,
				emptyValue: "0.00%",
				emptyHint: "no sends yet",
			},
			{
				label: "Reactions",
				value: effectiveTotals.likes > 0 ? formatCompact(effectiveTotals.likes) : "0",
				hint: "likes captured",
				hintTone: effectiveTotals.likes > 0 ? "pos" : "neutral",
				isEmpty: fleetNoData || effectiveTotals.likes === 0,
				emptyValue: "0",
				emptyHint: metrics.hasError ? "metrics retry needed" : "no likes yet",
			},
		];
	}, [
		platform,
		metrics.isLoading,
		metrics.hasError,
		metrics.reachDeltaPct,
		totals,
		cumulativeFollowers,
		todaysFollows,
		followerAttr.hasError,
		followerTotals.isLoading,
		followerTotals.hasError,
		qr.fleetRatio,
		ghosts.isLoading,
		ghosts.total,
		ghosts.weekOverWeekDelta,
		saveRate,
		sendsPerReach,
		story.totalImpressions,
		story.isLoading,
		timeframeLabel,
		threadPostTotals.data,
		isCrossPlatform,
	]);

	const hasPrimaryMetrics =
		totals.views > 0 || metrics.postCount > 0 || metrics.accounts.length > 0;
	useEffect(() => {
		setSkeletonReleased(false);
		const timeout = window.setTimeout(() => setSkeletonReleased(true), 950);
		return () => window.clearTimeout(timeout);
	}, []);

	useEffect(() => {
		if (!metrics.isLoading || hasPrimaryMetrics) setSkeletonReleased(true);
	}, [hasPrimaryMetrics, metrics.isLoading]);

	const ribbonHydrating =
		!skeletonReleased &&
		((metrics.isLoading && !hasPrimaryMetrics) ||
			(followerTotals.isLoading && cumulativeFollowers <= 0) ||
			(platform === "threads" &&
				(qr.isLoading || ghosts.isLoading) &&
				!hasPrimaryMetrics) ||
			(platform === "ig" && story.isLoading && story.totalImpressions === 0));

	if (ribbonHydrating) {
		return (
			<div
				className="grid overflow-hidden rounded-lg border border-border bg-card shadow-sm sm:grid-cols-2 xl:grid-cols-5"
				role="status"
				aria-busy="true"
				aria-label={`${platform} fundamentals loading`}
			>
				{cards.map((card, i) => (
					<RibbonStatSkeleton key={`${card.label}-${i}`} lead={i === 0} />
				))}
			</div>
		);
	}

	return (
		<div className="grid overflow-hidden rounded-lg border border-border bg-card shadow-sm sm:grid-cols-2 xl:grid-cols-5">
			{cards.map((card, i) => (
				<RibbonStat key={`${card.label}-${i}`} card={card} />
			))}
		</div>
	);
}

function RibbonStatSkeleton({ lead }: { lead?: boolean | undefined }) {
	return (
		<div className="relative min-w-0 border-b border-border p-5 last:border-b-0 xl:border-b-0 xl:border-r xl:last:border-r-0">
			{lead ? <span className="absolute inset-x-0 top-0 h-1 bg-primary" aria-hidden="true" /> : null}
			<Skeleton className="h-3 w-24 rounded" />
			<Skeleton className="mt-3 h-9 w-20 rounded" />
			<Skeleton className="mt-2 h-3 w-32 rounded" />
		</div>
	);
}

function RibbonStat({ card }: { card: RibbonCard }) {
	// Empty cells stay visibly informative. A bare em dash made the 30d ribbon
	// look broken when a window had no usable rows or a metrics retry was needed.
	const isEmpty = card.isEmpty === true;
	const displayValue = isEmpty ? (card.emptyValue ?? card.value) : card.value;
	const displayHint = isEmpty ? (card.emptyHint ?? card.hint) : card.hint;
	const title =
		!isEmpty &&
		card.label === "Share rate" &&
		card.hint.includes("cross-platform")
			? "Cross-platform share rate: Threads views are used as the reach proxy."
			: undefined;
	const hintClass = isEmpty
		? "text-muted-foreground"
		: card.hintTone === "pos"
			? "text-[color:var(--color-success)]"
			: card.hintTone === "warn"
				? "text-[color:var(--color-warning)]"
				: card.hintTone === "bad"
					? "text-destructive"
					: "text-muted-foreground";
	return (
		<div
			className={cn(
				"relative min-w-0 border-b border-border p-5 last:border-b-0 xl:border-b-0 xl:border-r xl:last:border-r-0",
				isEmpty && "opacity-70",
			)}
			title={title}
		>
			{card.lead ? <span className="absolute inset-x-0 top-0 h-1 bg-primary" aria-hidden="true" /> : null}
			<div className="truncate text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">{card.label}</div>
			<div className="mt-3 truncate text-4xl font-semibold tracking-[-0.045em] text-foreground tabular-nums">{displayValue}</div>
			<div className={cn("mt-2 truncate text-sm", hintClass)}>
				{displayHint}
			</div>
		</div>
	);
}
