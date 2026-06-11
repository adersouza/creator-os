import {
	type CompetitorSurprise,
	useCompetitorSurprises,
} from "@/hooks/useCompetitorSurprises";
import { Link } from "react-router-dom";
import { scopedRoute } from "@/lib/scopedRoutes";
import { useGhostPostCount } from "@/hooks/useGhostPostCount";
import { useNonFollowerReach } from "@/hooks/useNonFollowerReach";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { Avatar } from "../atoms/Avatar";
import { DeltaPill } from "../atoms/DeltaPill";
import type { DashboardScopeProps } from "../scope";
import { formatCompact, formatPct, formatSignedDelta } from "../shared";

function formatRelativeTime(iso: string): string {
	const now = Date.now();
	const then = new Date(iso).getTime();
	const diffMs = now - then;
	const hours = Math.floor(diffMs / (1000 * 60 * 60));
	if (hours < 1) return `${Math.floor(diffMs / (1000 * 60))}m ago`;
	if (hours < 24) return `${hours}h ago`;
	return `${Math.floor(hours / 24)}d ago`;
}

// =========================================================================
// Below-fold competitor pulse — quiet unless a watched competitor spikes.
// =========================================================================

interface CompetitorSurpriseTileProps {
	surprises?: CompetitorSurprise[] | undefined;
	isLoading?: boolean | undefined;
}

export function CompetitorSurpriseTile(
	props: CompetitorSurpriseTileProps = {},
) {
	const local = useCompetitorSurprises();
	const surprises = props.surprises ?? local.surprises;
	const isLoading = props.isLoading ?? local.isLoading;
	const top = surprises[0] ?? null;
	const handle = top?.competitorUsername ? `@${top.competitorUsername}` : null;
	const snippet = top?.content?.slice(0, 110) ?? null;

	return (
		<NovaCard
			className="h-full"
			contentClassName="flex h-full flex-col gap-3"
		>
			<div className="flex items-baseline justify-between gap-3">
				<span className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
					Competitor pulse · threshold-gated
				</span>
				{top ? (
					<Button asChild size="sm">
						<Link
							to={scopedRoute("/listening", {}, { q: handle ?? "competitor" })}
						>
							Route signal
						</Link>
					</Button>
				) : (
					<Badge tone="outline">CALM</Badge>
				)}
			</div>
			{top ? (
				<>
					<div className="flex min-w-0 items-center gap-3 rounded-lg border border-warning/35 bg-warning/10 px-3 py-2.5">
						<Avatar seed={top.competitorId} size="md" />
						<div className="min-w-0 flex-1">
							<div className="truncate text-sm font-semibold text-foreground">
								{handle}
							</div>
							<div
								className="text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground"
							>
								{formatRelativeTime(top.publishedAt)} · pacing{" "}
								{top.multiplier.toFixed(1)}× vs 30d median · over live threshold
							</div>
						</div>
						<div className="font-mono text-lg font-bold tabular-nums text-warning">
							{top.multiplier.toFixed(1)}×
						</div>
					</div>
					{snippet && (
						<div className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
							"{snippet}"
						</div>
					)}
					{surprises.length > 1 ? (
						<div className="text-xs text-muted-foreground">
							+ {surprises.length - 1} more competitors pacing &gt; median
						</div>
					) : null}
					<div className="flex justify-end gap-2">
						<Button asChild size="sm" variant="outline">
							<Link
								to={scopedRoute(
									"/ideas",
									{},
									{ body: snippet ?? undefined, source: "rough" },
								)}
							>
								Create idea
							</Link>
						</Button>
						<Button asChild size="sm" variant="outline">
							<Link
								to={scopedRoute(
									"/listening",
									{},
									{ q: handle ?? "competitor" },
								)}
							>
								Open listening
							</Link>
						</Button>
					</div>
					<div className="mt-auto grid grid-cols-2 gap-2 pt-3 sm:grid-cols-4">
						{(
							[
								["Views", top.views],
								["Likes", top.likes],
								["Replies", top.replies],
								["Reposts", top.reposts],
							] as const
						).map(([label, val]) => (
							<div key={label} className="rounded-md border border-border bg-muted px-2 py-1.5">
								<div className="font-mono text-[9px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
									{label}
								</div>
								<div className="mt-0.5 font-mono text-[13px] font-semibold tabular-nums text-foreground">
									{formatCompact(val)}
								</div>
							</div>
						))}
					</div>
				</>
			) : (
				<div className="mt-auto flex items-center justify-between gap-3 rounded-lg border border-border bg-muted px-3.5 py-3">
					<div className="flex min-w-0 items-center gap-2">
						<span
							aria-hidden="true"
							className="size-2 shrink-0 rounded-full bg-muted-foreground"
						/>
						<span className="text-xs text-muted-foreground">
							{isLoading
								? "Scanning tracked competitor baselines."
								: "0 competitor shifts above threshold"}
						</span>
					</div>
					<Badge tone="outline">QUIET BY DEFAULT</Badge>
				</div>
			)}
		</NovaCard>
	);
}

// Data note: the mockup IG variant wants a "By format · 30d"
// breakdown showing non-follower reach % per Reels / Carousel / Story.
// Data-blocked: posts.ig_non_follower_reach_pct does NOT exist —
// non-follower reach % is only stored at the daily account level in
// account_analytics.ig_non_follower_reach_pct. Producing the per-format
// split needs either:
//   (a) extending Meta sync to capture per-post non_follower_count
//       (reach insight with breakdown=follow_type) and persisting it
//       to a new posts.ig_non_follower_reach_pct column, or
//   (b) extending the daily rollup to bucket by media_product_type.
// Both are backend extensions — separate PR. Until then, IG view shows
// the same fleet-IG aggregate as ALL view (the hook already filters
// platform='instagram', so the data is IG-relevant — just not split by
// format).
export function NonFollowerReachTile({
	scopedAccount,
	accountIds,
	groupId,
}: DashboardScopeProps) {
	const reach = useNonFollowerReach(
		"30d",
		scopedAccount
			? {
					accountId: scopedAccount.id,
					accountPlatform: scopedAccount.platform,
					accountHandle: scopedAccount.handle,
				}
			: null,
		accountIds,
		groupId,
	);
	const pct = reach.hasRealData ? Math.round(reach.nonFollowerPct) : null;
	const inBand = pct !== null && pct >= 30 && pct <= 60;
	const status =
		pct === null
			? null
			: pct < 30
				? "Below threshold"
				: pct > 60
					? "Above band"
					: "In band";
	return (
		<NovaCard className="h-full" contentClassName="flex h-full flex-col">
			<div className="flex items-baseline justify-between">
				<span className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
					Non-follower reach
				</span>
				<Badge tone="outline">30D ROLLING</Badge>
			</div>
			<div className="mt-2 flex items-baseline gap-2">
				<div className="text-[32px] font-semibold leading-none tracking-normal text-foreground tabular-nums">
					{pct ?? 0}
					<span className="ml-1 text-lg text-muted-foreground">%</span>
				</div>
				{reach.delta && (
					<DeltaPill tone={reach.delta.startsWith("-") ? "down" : "up"}>
						{reach.delta.split(" ")[0]}
					</DeltaPill>
				)}
			</div>
			<div className="mt-1 text-xs text-muted-foreground">
				{pct === null ? (
					reach.loading ? (
						"Reading IG discovery split for the 30d rail."
					) : (
						"Discovery split is unavailable for this fleet."
					)
				) : (
					<>
						<span title="Juno33 fleet bands from synced IG discovery rollups.">
							Healthy band 30–60%.
						</span>{" "}
						<span className="font-semibold text-foreground">{status}.</span>
					</>
				)}
			</div>
			{pct === null && (
				<div className="mt-3 grid gap-2 rounded-lg border border-dashed border-border bg-muted/35 p-3">
					{[
						["Metric", "IG reach breakdown"],
						["Window", "30d fleet rollup"],
						["Status", reach.loading ? "reading" : "unavailable"],
					].map(([label, value], i) => (
						<div
							key={label}
							className="grid grid-cols-[54px_minmax(0,1fr)] items-center gap-2.5"
							style={{ opacity: 0.82 - i * 0.12 }}
						>
							<span className="text-[9px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
								{label}
							</span>
							<div
								className={cn(
									"h-5 truncate rounded-[5px] bg-foreground/5 px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.04em]",
									i === 2 ? "text-primary" : "text-muted-foreground",
								)}
							>
								{value}
							</div>
						</div>
					))}
				</div>
			)}
			{/* Bullet rail — research-driven (matches mockup #14 NEW) */}
			<div className="mt-auto pt-3">
				<div className="relative h-3.5 overflow-hidden rounded-full border border-border bg-foreground/5">
					{pct !== null && (
						<div
							className={cn(
								"absolute bottom-0.5 left-0 top-0.5 rounded-full",
								inBand
									? "bg-success"
									: pct < 20 || pct > 75
										? "bg-error"
										: "bg-primary",
							)}
							style={{
								width: `${Math.min(100, Math.max(0, pct))}%`,
							}}
						/>
					)}
					{/* Healthy-band markers at 30% and 60% */}
					<div
						className={cn(
							"absolute -top-0.5 -bottom-0.5 w-px opacity-60",
							inBand ? "bg-foreground" : "bg-muted-foreground",
						)}
						style={{ left: "30%" }}
					/>
					<div
						className={cn(
							"absolute -top-0.5 -bottom-0.5 w-px opacity-60",
							inBand ? "bg-foreground" : "bg-muted-foreground",
						)}
						style={{ left: "60%" }}
					/>
				</div>
				<div className="mt-1.5 flex justify-between font-mono text-[9px] font-medium text-muted-foreground">
					<span>0%</span>
					<span>30%</span>
					<span>60%</span>
					<span>100%</span>
				</div>
			</div>
		</NovaCard>
	);
}

// =========================================================================
// Threads view — Band 1 right-2: Ghost count
// =========================================================================

export function GhostCountTile({
	scopedAccount,
	accountIds,
}: DashboardScopeProps) {
	const threadScopedIds = scopedAccount
		? scopedAccount.platform === "threads"
			? [scopedAccount.id]
			: []
		: accountIds;
	const { total, withLinks, weekOverWeekDelta, accounts, isLoading, hasError } =
		useGhostPostCount(threadScopedIds);
	const topAffected = accounts.slice(0, 5);
	const floor = 3;
	const ghostToneClass =
		isLoading || hasError
			? "text-foreground"
			: total === 0
				? "text-success"
				: total <= floor
					? "text-foreground"
					: total > floor * 2
						? "text-error"
						: "text-primary";
	return (
		<NovaCard className="h-full" contentClassName="flex h-full flex-col">
			<div className="flex items-baseline justify-between">
				<span className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
					Ghost posts · 7d
				</span>
				<Badge tone="outline">&lt;10 VIEWS · &gt;24H OLD</Badge>
			</div>
			<div className="mt-2 flex items-baseline gap-3">
				<div
					className={cn(
						"text-[32px] font-semibold leading-none tracking-normal tabular-nums",
						ghostToneClass,
					)}
				>
					{isLoading ? "Sync" : hasError ? "Retry" : total}
					<span className="ml-1 text-sm text-muted-foreground">ghosts</span>
				</div>
				{!isLoading && !hasError && weekOverWeekDelta !== 0 ? (
					<DeltaPill tone={weekOverWeekDelta > 0 ? "warn" : "up"}>
						{weekOverWeekDelta > 0
							? `+${weekOverWeekDelta}`
							: String(weekOverWeekDelta)}{" "}
						weekly · vs prior 7d
					</DeltaPill>
				) : null}
			</div>
			<div className="mt-1 text-xs text-muted-foreground">
				{isLoading
					? "scanning fleet…"
					: hasError
						? "ghost-post scan unavailable"
						: total === 0
							? "no suppressed posts in window"
							: `${withLinks} with links · triggers: thin thread, no reply chain, no quote`}
			</div>

			{/* Most-affected accounts — research-driven (matches mockup #15 NEW addition) */}
			{!hasError && isLoading ? (
				<div className="mt-auto flex flex-col gap-2 rounded-lg border border-dashed border-border bg-muted/35 p-3">
					{[0.72, 0.54, 0.38].map((w, i) => (
						<div
							key={w}
							className="grid grid-cols-[22px_minmax(0,1fr)_44px] items-center gap-2"
							style={{ opacity: 0.58 - i * 0.09 }}
						>
							<span className="size-[22px] rounded-full bg-error/10" />
							<Skeleton className="h-2.5" style={{ width: `${w * 100}%` }} />
							<Skeleton className="h-2.5 w-[34px]" />
						</div>
					))}
					<div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
						Scanning fleet for posts under 10 views after 24h.
					</div>
				</div>
			) : !isLoading && !hasError && topAffected.length > 0 ? (
				<div className="mt-3.5 border-t border-border pt-3">
					<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
						Most affected · 7d
					</div>
					<div className="flex flex-col gap-1.5">
						{topAffected.map((acct, i) => (
							<div
								key={acct.accountId}
								className={cn(
									"grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-[13px]",
									i === 0 ? "bg-error/10" : "bg-muted",
								)}
							>
								<span className="truncate font-medium text-foreground">
									{acct.username ? `@${acct.username}` : "Unknown account"}
								</span>
								<span
									className={cn(
										"font-mono text-[11px] font-semibold",
										i === 0 ? "text-error" : "text-muted-foreground",
									)}
								>
									{acct.ghostCount} {acct.ghostCount === 1 ? "ghost" : "ghosts"}
								</span>
							</div>
						))}
					</div>
				</div>
			) : !isLoading && !hasError ? (
				<div className="mt-auto flex flex-col gap-2 rounded-lg border border-dashed border-border bg-muted/35 p-3">
					{[0.62, 0.46, 0.32].map((w, i) => (
						<div
							key={w}
							className="grid grid-cols-[22px_minmax(0,1fr)_44px] items-center gap-2"
							style={{ opacity: 0.52 - i * 0.1 }}
						>
							<div className="size-[22px] rounded-full bg-success/10" />
							<div
								className="h-2 rounded-full bg-muted"
								style={{ width: `${w * 100}%` }}
							/>
							<div className="h-2 w-full rounded-full bg-muted" />
						</div>
					))}
					<div className="mt-1 border-t border-border pt-2 text-[11px] font-semibold text-success">
						Fleet clean · no affected accounts
					</div>
				</div>
			) : null}
		</NovaCard>
	);
}

// Keep an underscored reference so eslint doesn't flag formatPct / formatSignedDelta as unused when
// the caller chain above doesn't hit them in a given render path.
const _fmt = { formatPct, formatSignedDelta };

export { _fmt as __formatters };
