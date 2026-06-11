import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useFleetMetrics } from "@/hooks/useFleetMetrics";
import {
	EMPTY_THREAD_TOTALS,
	useThreadsPostTotals,
} from "@/hooks/useThreadsPostTotals";
import {
	dashboardTimeframeToDays,
	dashboardTimeframeToFleetMetrics,
	type DashboardTimeframe,
} from "@/lib/dashboardUrlState";
import { scopedRoute } from "@/lib/scopedRoutes";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import {
	fleetPlatformFor,
	formatReachDeltaLabel,
	isTinyBaselineDelta,
	type Platform,
} from "../shared";
import type { DashboardScopeProps } from "../scope";

const FALLBACK_HEADING: Record<Platform, string> = {
	all: "Waiting for enough synced posts.",
	threads: "Waiting for enough Threads posts.",
	ig: "Waiting for enough Instagram posts.",
};

const LOADING_HEADING: Record<Platform, string> = {
	all: "Syncing the account read.",
	threads: "Syncing the Threads read.",
	ig: "Syncing the Instagram read.",
};

interface Props extends DashboardScopeProps {
	platform: Platform;
	timeframe: DashboardTimeframe;
}

export function HeroTile({
	platform,
	timeframe,
	scopedAccount,
	accountIds,
	groupId,
	scopeLabel,
}: Props) {
	const navigate = useNavigate();
	const fleetPlatform = fleetPlatformFor(platform);
	const days = dashboardTimeframeToDays(timeframe);
	const metricsTimeframe = dashboardTimeframeToFleetMetrics(timeframe);
	const metrics = useFleetMetrics(
		metricsTimeframe,
		fleetPlatform,
		scopedAccount,
		{ accountIds, groupId },
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
	const threadPostTotals = useThreadsPostTotals(days, threadScopedIds);
	const analyticsPath = scopedRoute("/analytics", {
		scopedAccount,
		accountIds,
		groupId,
		platform,
		timeframe,
	});
	const calendarPath = scopedRoute("/calendar", {
		scopedAccount,
		accountIds,
		groupId,
		platform,
		timeframe,
	});

	const totals = useMemo(() => {
		const t = { views: 0, likes: 0, comments: 0, posts: 0 };
		for (const account of metrics.accounts) {
			t.views += account.reach;
			t.likes += account.likes;
			t.comments += account.comments;
			t.posts += account.posts;
		}
		return t;
	}, [metrics.accounts]);
	const effectiveTotals = useMemo(() => {
		if (platform !== "threads") return totals;
		const fallback = threadPostTotals.data ?? EMPTY_THREAD_TOTALS;
		if (fallback.posts <= 0) return totals;
		return {
			views: fallback.views,
			likes: fallback.likes,
			comments: fallback.replies,
			posts: fallback.posts,
		};
	}, [platform, threadPostTotals.data, totals]);
	const hasThreadPostFallback =
		platform === "threads" && (threadPostTotals.data?.posts ?? 0) > 0;
	const metricsStillLoading = metrics.isLoading && !hasThreadPostFallback;
	const metricsUnavailable = metrics.isLoading || metrics.hasError;
	const hasFleetData =
		(!metricsUnavailable &&
			(effectiveTotals.views > 0 || effectiveTotals.posts > 0)) ||
		hasThreadPostFallback;
	const reachDeltaStr =
		!metricsUnavailable &&
		!hasThreadPostFallback &&
		metrics.reachDeltaPct != null &&
		Number.isFinite(metrics.reachDeltaPct)
			? formatReachDeltaLabel(metrics.reachDeltaPct, 1)
			: null;
	const hasTinyReachBaseline = isTinyBaselineDelta(metrics.reachDeltaPct);
	const isReachDown = !!reachDeltaStr?.startsWith("-");
	const isReachUp = !!reachDeltaStr && !isReachDown && !hasTinyReachBaseline;
	const platformLabel =
		platform === "threads" ? "Threads" : platform === "ig" ? "Instagram" : "All platforms";
	const briefingStatus = metricsStillLoading
		? "Syncing"
		: metrics.hasError
			? "Needs retry"
			: !hasFleetData
				? "Needs sample"
				: isReachDown
					? "Needs attention"
					: hasTinyReachBaseline
						? "New baseline"
						: "Live read";
	const briefingTone = metrics.hasError || isReachDown ? "bad" : hasFleetData ? "live" : "idle";
	const briefingTitle = (() => {
		if (metricsStillLoading) return LOADING_HEADING[platform];
		if (metrics.hasError) return "Metrics need a fresh compute.";
		if (!hasFleetData) return FALLBACK_HEADING[platform];
		if (hasTinyReachBaseline) {
			return "New baseline. Watch movement before changing strategy.";
		}
		if (isReachDown) {
			return "Reach dropped. Triage accounts before changing content.";
		}
		if (isReachUp) return "Reach is moving up. Protect the current rhythm.";
		return "Account movement is live. Review before changing strategy.";
	})();
	const briefingCopy = (() => {
		if (metrics.hasError) {
			return "Retry the live compute, then use analytics to find where the read broke.";
		}
		if (!hasFleetData) {
			return "Publish or sync posts first; the KPI ribbon will fill once the sample is usable.";
		}
		if (isReachDown) {
			return "Sort the weakest movers first, then compare publish windows and demand signals.";
		}
		if (hasTinyReachBaseline) {
			return "Treat this as a fresh baseline and wait for the next synced window before overreacting.";
		}
		return "Use the KPI ribbon for scale; use analytics for the account-level explanation.";
	})();
	const primaryActionLabel = isReachDown ? "Worst accounts" : "Open analytics";
	const scopeMeta = `${scopeLabel ?? "All accounts"} · ${platformLabel} · ${(timeframe ?? "30d").toUpperCase()}`;

	return (
		<NovaCard
			variant="default"
			className="h-full"
			contentClassName="p-5"
		>
			<div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
				<div className="min-w-0 max-w-4xl">
					<div className="mb-3 flex flex-wrap items-center gap-2">
						<Badge tone="oxblood">Dashboard briefing</Badge>
						<Badge tone={briefingTone === "bad" ? "danger" : briefingTone === "live" ? "secondary" : "outline"}>
							{briefingStatus}
						</Badge>
					</div>
					<div className="max-w-3xl text-xl font-semibold leading-tight text-foreground md:text-2xl">
						{briefingTitle}
					</div>
					<p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">
						{briefingCopy}
					</p>
					<div className="mt-3 text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">
						{scopeMeta}
					</div>
				</div>
				<div className="flex shrink-0 flex-wrap items-center gap-2">
					<Button type="button" onClick={() => navigate(analyticsPath)}>
						{primaryActionLabel}
					</Button>
					<Button
						type="button"
						variant="outline"
						onClick={() => navigate(calendarPath)}
					>
						Publish windows
					</Button>
				</div>
			</div>
		</NovaCard>
	);
}
