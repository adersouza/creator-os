import { useMemo } from "react";
import { useAnomalyFeed } from "@/hooks/useAnomalyFeed";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import {
	useFleetMetrics,
	type FleetMetricsState,
} from "@/hooks/useFleetMetrics";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import {
	daysToFleetTimeframe,
	toFleetPlatform,
} from "@/components/analytics/analyticsShared";
import { Badge } from "@/components/ui/Badge";
import { NovaDataPanel } from "@/components/ui/NovaPrimitives";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { Skeleton } from "@/components/ui/Skeleton";
import type { CompareMode, Platform } from "./shared";
import { formatCompact } from "./shared";

interface InsightsRailProps {
	platform: Platform;
	compare: CompareMode;
	accountCount: number;
	cohortLabel?: string | undefined;
	/** Real day count from the date range — used to label the snapshot. */
	days: number;
	/** Pre-fetched fleet metrics from the parent (Analytics page). When omitted
	 *  the rail fetches its own; when provided the inner hook is disabled. */
	fleet?: FleetMetricsState | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
}

/**
 * Right column for the top band — two stacked tiles (dark anomaly anchor +
 * filter context). The KPI strip used to live here (`statRowSlot`) but moved
 * to a full-width row above the hero so it can host 4/8/6 tiles per spec §3.
 */
export function InsightsRail({
	platform,
	compare,
	accountCount,
	cohortLabel = "All accounts",
	days,
	fleet: fleetProp,
	accountIds,
	groupId,
}: InsightsRailProps) {
	const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const { alerts, isLoading, hasError } = useAnomalyFeed(
		{ hours: 24 },
		"all",
		scopedAccount,
		accountIds,
		groupId,
	);
	// Match the platform tab so the "What changed · 24h" anchor doesn't show
	// IG alerts in the Threads view (or vice versa). InsightFeedRow uses the
	// same filter — keep them in sync.
	const filteredAlerts = useMemo(() => {
		if (platform === "all") return alerts;
		if (platform === "threads")
			return alerts.filter((a) => a.platform === "threads");
		return alerts.filter((a) => a.platform === "instagram");
	}, [alerts, platform]);
	const topAlerts = filteredAlerts.slice(0, 3);
	const { accounts } = useConnectedAccounts();
	// Mirror the InsightFeedRow drill: clicking an account-scoped alert pivots
	// the page to that account. Fleet-level alerts (no accountId) are left
	// non-interactive — there's nothing to drill into.
	const drillFor = (
		alert: (typeof filteredAlerts)[number],
	): (() => void) | undefined => {
		const accountId = alert.accountId ?? alert.instagramAccountId;
		if (!accountId) return undefined;
		const meta = accounts.find((a) => a.id === accountId);
		if (!meta) return undefined;
		return () => {
			useAccountScopeStore.getState().setScope({
				id: meta.id,
				handle: meta.handle,
				platform: meta.platform,
			});
		};
	};
	const fleetTimeframe = useMemo(() => daysToFleetTimeframe(days), [days]);
	const fallbackFleet = useFleetMetrics(
		fleetTimeframe,
		toFleetPlatform(platform),
		scopedAccount,
		{ enabled: !fleetProp, accountIds, groupId },
	);
	const fleet = fleetProp ?? fallbackFleet;
	const compareLabel = compare === "prev" ? "vs. prior window" : "off";
	const evidenceQueue = evidenceQueueFor(platform);
	const isAccountScope = !!scopedAccount?.id;
	const isFilteredScope =
		!isAccountScope && !!(accountIds && accountIds.length > 0);
	const snapshotTitle = isAccountScope
		? `Account snapshot · last ${days}d`
		: isFilteredScope
			? `${cohortLabel} snapshot · last ${days}d`
			: `All accounts snapshot · last ${days}d`;
	const accountHandle = scopedAccount?.handle
		? scopedAccount.handle.startsWith("@")
			? scopedAccount.handle
			: `@${scopedAccount.handle}`
		: "Selected account";
	const accountPlatform =
		scopedAccount?.platform === "instagram" ? "Instagram" : "Threads";

	return (
		<aside className="flex h-full flex-col gap-4">
			<NovaDataPanel
				title="What changed"
				description="24h anomaly feed"
				toolbar={
					<Badge tone="outline">
						{isLoading
							? "Loading"
							: filteredAlerts.length > 0
								? `${filteredAlerts.length} total`
								: "None"}
					</Badge>
				}
				className="min-h-[168px]"
				contentClassName="flex h-full flex-col gap-3"
			>
					{isLoading ? (
						<div
							className="flex flex-col gap-2"
							role="status"
							aria-label="Loading anomaly feed"
						>
							{[72, 54, 82, 64].map((width, index) => (
								<div
									key={width}
									className="rounded-md border border-border/40 bg-muted/40 px-2.5 py-2"
								>
									<div className="mb-2 flex items-center justify-between gap-3">
										<Skeleton className="h-2.5 w-20 rounded-full" />
										<Skeleton className="h-2.5 w-10 rounded-full" />
									</div>
									<Skeleton
										className="h-2 rounded-full bg-[color:var(--color-oxblood)]/25"
										style={{ width: `${width}%`, animationDelay: `${index * 90}ms` }}
									/>
								</div>
							))}
						</div>
					) : hasError ? (
						<p className="text-[0.75rem] text-muted-foreground">
							Could not load the 24h anomaly feed.
						</p>
					) : topAlerts.length === 0 ? (
						<p className="text-[0.75rem] text-muted-foreground">
							No 24h anomalies for {cohortLabel}.
						</p>
					) : (
						<ul className="flex flex-col gap-2.5">
							{topAlerts.map((alert) => {
								const drill = drillFor(alert);
								const interactive = !!drill;
								return (
									<li
										key={alert.id}
										className={
											"flex flex-col gap-0.5 min-w-0 " +
											(interactive
												? "cursor-pointer rounded-md -mx-1 px-1 py-0.5 hover:bg-muted/50 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-border"
												: "")
										}
										onClick={drill}
										onKeyDown={
											interactive
												? (e) => {
														if (e.key === "Enter" || e.key === " ") {
															e.preventDefault();
															drill?.();
														}
													}
												: undefined
										}
										role={interactive ? "button" : undefined}
										tabIndex={interactive ? 0 : undefined}
										aria-label={
											interactive ? `Drill into ${alert.title}` : undefined
										}
									>
										<div className="flex items-center justify-between gap-2">
											<span className="text-[0.75rem] font-medium text-foreground truncate">
												{alert.title}
											</span>
											<Badge
												tone={severityToTone(alert.severity)}
												className="px-1.5 py-[1px] text-[0.625rem]"
											>
												{alert.severity}
											</Badge>
										</div>
										{alert.description ? (
											<p className="line-clamp-2 text-[0.6875rem] text-muted-foreground">
												{alert.description}
											</p>
										) : null}
									</li>
								);
							})}
						</ul>
					)}
			</NovaDataPanel>

			{/* Window snapshot.
          Mixes load-bearing analytical context (post count, fleet reach,
          delta, accounts contributing) with filter confirmation (cohort,
          breakdown). Replaces the earlier all-decoration filter-context
          tile so the rail's bottom half carries real signal. */}
			<NovaDataPanel
				title={snapshotTitle}
				className="min-h-[176px]"
				contentClassName="flex h-full flex-col"
			>
					<div className="mt-3 grid grid-cols-1 gap-x-5 sm:grid-cols-2">
						<Row
							label="Posts in window"
							value={fleet.postCount.toLocaleString()}
							mono
						/>
						<Row
							label={platform === "threads" ? "Views" : "Reach"}
							value={fleet.isLoading ? "Sync" : formatCompact(fleet.totalReach)}
							mono
						/>
						<Row
							label="vs. prior"
							value={
								fleet.reachDeltaPct == null
									? "0.0%"
									: `${fleet.reachDeltaPct >= 0 ? "+" : ""}${fleet.reachDeltaPct.toFixed(1)}%`
							}
							tone={
								fleet.reachDeltaPct == null
									? undefined
									: fleet.reachDeltaPct >= 5
										? "good"
										: fleet.reachDeltaPct <= -10
											? "crit"
											: fleet.reachDeltaPct <= -5
												? "warn"
												: undefined
							}
							mono
						/>
						{isAccountScope ? (
							<>
								<Row label="Account" value={accountHandle} />
								<Row label="Platform" value={accountPlatform} />
							</>
						) : (
							<>
								<Row
									label={
										isFilteredScope ? "Active in scope" : "Active accounts"
									}
									value={`${fleet.accounts.filter((a) => a.posts > 0).length} / ${accountCount}`}
									mono
								/>
								<Row
									label={isFilteredScope ? "Scope" : "Cohort"}
									value={cohortLabel}
								/>
							</>
						)}
						<Row label="Compare" value={compareLabel} />
					</div>
			</NovaDataPanel>

			<EvidenceCard
				title="Evidence queue"
				description="Jump into the checks that explain this view before changing strategy."
				className="min-h-[180px] flex-1"
				contentClassName="flex h-full flex-col"
			>
					<div className="flex h-full flex-col justify-between gap-4">
						<div className="grid gap-2">
							{evidenceQueue.map((item) => (
								<a
									key={item.href}
									href={item.href}
									className="group flex items-center justify-between gap-3 rounded-md border border-border/60 bg-muted/25 px-3 py-2 text-[0.75rem] transition-colors hover:border-oxblood/45 hover:bg-oxblood/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-oxblood/35"
								>
									<span className="min-w-0">
										<span className="block truncate font-medium text-foreground">
											{item.label}
										</span>
										<span className="block truncate text-[0.6875rem] text-muted-foreground">
											{item.detail}
										</span>
									</span>
									<Badge tone="outline" className="bg-background/60 group-hover:text-oxblood">
										{item.kicker}
									</Badge>
								</a>
							))}
						</div>
					</div>
			</EvidenceCard>
		</aside>
	);
}

function evidenceQueueFor(platform: Platform): {
	label: string;
	detail: string;
	href: string;
	kicker: string;
}[] {
	if (platform === "threads") {
		return [
			{
				label: "Fleet grid",
				detail: "Worst account deltas and flags",
				href: "#evidence-1",
				kicker: "grid",
			},
			{
				label: "Conversation system",
				detail: "Reply depth, quote ratio, suppression",
				href: "#evidence-conversation-system",
				kicker: "talk",
			},
			{
				label: "Top posts",
				detail: "Thread winners and low performers",
				href: "#evidence-15",
				kicker: "posts",
			},
		];
	}

	if (platform === "ig") {
		return [
			{
				label: "Fleet grid",
				detail: "Instagram account movement",
				href: "#evidence-1",
				kicker: "grid",
			},
			{
				label: "Distribution inputs",
				detail: "Format, hashtags, Reels friction",
				href: "#evidence-distribution-inputs",
				kicker: "inputs",
			},
			{
				label: "Post table",
				detail: "IG top and bottom posts",
				href: "#evidence-15",
				kicker: "posts",
			},
		];
	}

	return [
		{
			label: "Fleet grid",
			detail: "Cross-platform account movement",
			href: "#evidence-1",
			kicker: "grid",
		},
		{
			label: "Metric matrix",
			detail: "Account-by-metric scan",
			href: "#evidence-matrix",
			kicker: "matrix",
		},
		{
			label: "Trajectory",
			detail: "Forecast, confidence, annotations",
			href: "#evidence-trajectory",
			kicker: "trend",
		},
	];
}

function Row({
	label,
	value,
	mono,
	tone,
}: {
	label: string;
	value: string;
	mono?: boolean | undefined;
	tone?: "good" | "warn" | "crit" | undefined;
}) {
	const color =
		tone === "good"
			? "var(--color-health-good)"
			: tone === "warn"
				? "var(--color-gold)"
				: tone === "crit"
					? "var(--color-oxblood)"
					: undefined;
	return (
		<div className="flex items-center justify-between py-1 text-[0.75rem]">
			<span className="text-muted-foreground">{label}</span>
			<span
				className={`text-foreground ${mono ? "font-mono tabular-nums" : ""}`}
				style={color ? { color } : undefined}
			>
				{value}
			</span>
		</div>
	);
}

function severityToTone(severity: string | null | undefined): "danger" | "outline" | "secondary" {
	const s = (severity ?? "").toLowerCase();
	if (s === "critical" || s === "high") return "danger";
	if (s === "medium" || s === "warn") return "outline";
	return "secondary";
}
