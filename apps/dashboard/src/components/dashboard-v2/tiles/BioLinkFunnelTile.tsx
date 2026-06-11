// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard, NovaEmpty, NovaInset, NovaMiniStat } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { useBioLinkFunnel } from "@/hooks/useBioLinkFunnel";
import { scopedRoute } from "@/lib/scopedRoutes";
import { formatCompact } from "../shared";
import type { DashboardScopeProps } from "../scope";

const SOURCE_COLORS = [
	"var(--color-oxblood)",
	"var(--color-gold)",
	"var(--color-chart-2)",
	"var(--color-health-good)",
];

function money(value: number): string {
	if (!Number.isFinite(value) || value <= 0) return "$0";
	if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
	return `$${value.toFixed(value >= 100 ? 0 : 2)}`;
}

export function BioLinkFunnelTile({
	scopedAccount,
	accountIds,
	groupId,
	periodDays = 30,
}: DashboardScopeProps & { periodDays?: number }) {
	const {
		links,
		totals,
		activeLinkCount,
		totalLinkCount,
		isLoading,
		hasError,
	} = useBioLinkFunnel(periodDays, scopedAccount, accountIds, groupId);

	const topSources = useMemo(
		() =>
			Object.entries(totals.clicksBySource)
				.sort((a, b) => b[1] - a[1])
				.slice(0, 4)
				.map(([source, count], i) => ({
					source,
					count,
					pct: totals.clicks > 0 ? (count / totals.clicks) * 100 : 0,
					color: SOURCE_COLORS[i % SOURCE_COLORS.length],
				})),
		[totals.clicks, totals.clicksBySource],
	);

	const hasNoData =
		!isLoading &&
		!hasError &&
		totals.clicks === 0 &&
		totals.conversions === 0 &&
		totals.conversionValue === 0 &&
		totals.estimatedRevenue === 0;
	const hasData = !hasNoData && (totals.clicks > 0 || totals.conversions > 0);
	const revenue =
		totals.conversionValue > 0
			? totals.conversionValue
			: totals.estimatedRevenue;
	const revenueLabel = totals.conversionValue > 0 ? "actual" : "est.";
	const conversionRate =
		totals.clicks > 0 ? (totals.conversions / totals.clicks) * 100 : null;

	return (
		<NovaCard
			variant="compact"
			eyebrow={`Bio-link funnel · ${periodDays}d`}
			title="Smart links"
			description="Clicks, conversions, and estimated revenue across active bio links."
			action={<Badge variant="outline">{activeLinkCount}/{totalLinkCount} active</Badge>}
		>
				{hasData ? (
					<>
						<div className="mt-4 grid grid-cols-3 gap-2">
							<NovaMiniStat
								label="Clicks"
								value={formatCompact(totals.clicks)}
								tone="primary"
								size="compact"
							/>
							<NovaMiniStat
								label="Conversions"
								value={formatCompact(totals.conversions)}
								description={
									conversionRate != null
										? `${conversionRate.toFixed(1)}% conversion`
										: "— conversion"
								}
								size="compact"
							/>
							<NovaMiniStat
								label="Revenue"
								value={money(revenue)}
								tone="warning"
								trend={revenueLabel}
								size="compact"
							/>
						</div>

						<div className="mt-4 flex h-7 overflow-hidden rounded-lg border border-border bg-muted">
							{topSources.length > 0 ? (
								topSources.map((s) => (
									<div
										key={s.source}
										title={`${s.source} · ${s.count} clicks`}
										style={{
											width: `${Math.max(s.pct, 3)}%`,
											background: s.color,
											borderRight:
												"1px solid color-mix(in srgb, var(--color-card) 35%, transparent)",
										}}
									/>
								))
							) : (
								<div style={{ width: "100%", background: "var(--color-muted)" }} />
							)}
						</div>

						<div className="mt-3 grid grid-cols-2 gap-2">
							{topSources.slice(0, 4).map((s) => (
								<NovaInset key={s.source} className="p-3">
									<div className="flex items-center gap-2">
										<span
											style={{
												width: 7,
												height: 7,
												borderRadius: 2,
												background: s.color,
												flexShrink: 0,
											}}
										/>
										<span
											className="font-mono"
											style={{
												fontSize: 9,
												color: "var(--color-muted-foreground)",
												textTransform: "uppercase",
											}}
										>
											{s.source}
										</span>
									</div>
									<div className="mt-2 text-lg font-semibold tabular-nums text-foreground">
										{formatCompact(s.count)}
									</div>
									<div className="mt-1 text-xs text-muted-foreground">
										— conv
									</div>
								</NovaInset>
							))}
						</div>

						<NovaInset className="mt-4 p-3">
							<div className="text-sm leading-relaxed text-muted-foreground">
								{links.length > 0 ? (
									<>
										Top link{" "}
										<strong className="font-semibold text-foreground">
											{links[0]!.title || links[0]!.code}
										</strong>{" "}
										drove {formatCompact(links[0]!.clicks)} clicks. Revenue uses
										conversion postbacks first, configured estimates second.
									</>
								) : (
									"Click events are live; no individual link crossed the display threshold."
								)}
							</div>
						</NovaInset>
					</>
				) : (
					<BioLinkEmpty
						isLoading={isLoading}
						hasError={hasError}
						hasNoData={hasNoData}
						periodDays={periodDays}
						linksHref={scopedRoute("/links", { scopedAccount, accountIds, groupId })}
					/>
				)}
		</NovaCard>
	);
}

function BioLinkEmpty({
	isLoading,
	hasError,
	hasNoData,
	periodDays,
	linksHref,
}: {
	isLoading: boolean;
	hasError: boolean;
	hasNoData: boolean;
	periodDays: number;
	linksHref: string;
}) {
	if (isLoading) {
		return (
			<div className="mt-3 rounded-lg border border-border bg-muted/35 p-4">
				<div className="grid grid-cols-3 gap-2">
					{Array.from({ length: 3 }).map((_, index) => (
						<div key={index} className="rounded-lg border border-border bg-card p-3">
							<Skeleton className="h-2 w-14" />
							<Skeleton className="mt-3 h-5 w-16" />
						</div>
					))}
				</div>
				<Skeleton className="mt-4 h-7 w-full rounded-md" />
			</div>
		);
	}

	return (
		<NovaEmpty
			className="mt-3"
			title={hasError ? "Bio-link funnel unavailable" : "No bio-link clicks yet"}
			description={
				hasError
					? "Refresh to retry the smart-link read."
					: hasNoData
						? `No bio-link clicks in ${periodDays}D. Check that the link is live and attached to the right account.`
						: "Smart-link click events are still syncing."
			}
		>
			{hasNoData ? (
				<Button asChild variant="outline" size="sm">
					<Link to={linksHref}>Open Smart Links</Link>
				</Button>
			) : null}
		</NovaEmpty>
	);
}
