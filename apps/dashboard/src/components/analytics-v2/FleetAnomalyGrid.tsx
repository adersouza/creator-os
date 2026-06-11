import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { ColumnDef } from "@tanstack/react-table";
import { Wrench } from "lucide-react";
import {
	useFleetMetrics,
	type FleetAccountAggregate,
	type FleetMetricsState,
} from "@/hooks/useFleetMetrics";
import { useFleetHealthAccounts } from "@/hooks/useFleetHealthAccounts";
import { useAnomalyFeed } from "@/hooks/useAnomalyFeed";
import {
	useSeverityScore,
	type AccountSeverity,
} from "@/hooks/useSeverityScore";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { AccountAvatar } from "@/components/dashboard/polish";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataTable } from "@/components/ui/DataTable";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { AnalyticsActionLink } from "./AnalyticsActionLink";
import { scopedRoute } from "@/lib/scopedRoutes";
import {
	toFleetPlatform,
	daysToFleetTimeframe,
} from "@/components/analytics/analyticsShared";
import { formatCompact, type Platform } from "./shared";

interface FleetAnomalyGridProps {
	platform: Platform;
	/** Real day count from the date range. */
	days: number;
	/** Pre-fetched fleet metrics from the parent. */
	fleet?: FleetMetricsState | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
	scopeLabel?: string | undefined;
}

type EnrichedRow = FleetAccountAggregate & {
	engagementRate: number;
	anomalyCount: number;
	healthBucket?: "crit" | "warn" | "healthy" | undefined;
	healthReason?: string | null | undefined;
	severity?: AccountSeverity | null | undefined;
};

/**
 * §1 Fleet anomaly grid — worst-first table with per-platform column sets
 * (spec §6). Severity = real 7-day z-score vs 90-day own-history distribution
 * (|z| > 2.5 critical, 2.0 < |z| ≤ 2.5 warning; |daily_delta| ≥ 10 backstop
 * per production_playbook §5). Accent bar + flag pill read from the z-score
 * severity plus the supplementary fleet-health + anomaly-feed joins. Derived
 * originality and ghost-post columns render from live analytics fallbacks.
 */
export function FleetAnomalyGrid({
	platform,
	days,
	fleet,
	accountIds,
	groupId,
	scopeLabel,
}: FleetAnomalyGridProps) {
	const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const fleetTimeframe = useMemo(() => daysToFleetTimeframe(days), [days]);
	const fallbackMetrics = useFleetMetrics(
		fleetTimeframe,
		toFleetPlatform(platform),
		scopedAccount,
		{ enabled: !fleet, accountIds, groupId },
	);
	const metrics = fleet ?? fallbackMetrics;
	const { accounts: healthRows, hasError: healthHasError } =
		useFleetHealthAccounts(50);
	const { alerts, hasError: anomalyHasError } = useAnomalyFeed(
		{ hours: 72 },
		"all",
		scopedAccount,
		accountIds,
		groupId,
	);
	const accountIdsForSeverity = useMemo(
		() => metrics.accounts.map((a) => a.accountId),
		[metrics.accounts],
	);
	const severityScopeIds =
		scopedAccount?.id || (accountIds && !groupId)
			? accountIdsForSeverity
			: undefined;
	const severity = useSeverityScore(
		severityScopeIds,
		scopedAccount?.id ? null : groupId,
		metrics.accounts.length > 0,
	);
	const sidecarHasError =
		healthHasError || anomalyHasError || severity.hasError;

	const [anomalyOnly, setAnomalyOnly] = useState(false);
	const [showAll, setShowAll] = useState(false);

	const healthByAccount = useMemo(() => {
		const map = new Map<string, (typeof healthRows)[number]>();
		for (const row of healthRows) map.set(row.accountId, row);
		return map;
	}, [healthRows]);

	const anomaliesByAccount = useMemo(() => {
		const map = new Map<string, number>();
		for (const alert of alerts) {
			const key = alert.accountId ?? alert.instagramAccountId;
			if (!key) continue;
			map.set(key, (map.get(key) ?? 0) + 1);
		}
		return map;
	}, [alerts]);

	const rows = useMemo<EnrichedRow[]>(() => {
		const enriched = metrics.accounts.map((a) => {
			const engagementRate =
				a.reach > 0
					? ((a.likes + a.comments + a.sends + a.saves) / a.reach) * 100
					: 0;
			const anomalyCount = anomaliesByAccount.get(a.accountId) ?? 0;
			const health = healthByAccount.get(a.accountId);
			return {
				...a,
				engagementRate,
				anomalyCount,
				healthBucket: health?.bucket,
				healthReason: health?.reason,
				severity: severity.get(a.accountId),
			};
		});
		const filtered = anomalyOnly
			? enriched.filter(
					(r) =>
						r.anomalyCount > 0 ||
						r.healthBucket === "crit" ||
						r.severity?.severity === "critical" ||
						r.severity?.severity === "warning",
				)
			: enriched;
		// Worst-first: z-score severity drives the sort; ties broken by |z|, then
		// EQS ascending so small-account noise sinks below flagged accounts.
		return [...filtered].sort(
			(a, b) =>
				severityFor(a).rank - severityFor(b).rank ||
				Math.abs(b.severity?.z ?? 0) - Math.abs(a.severity?.z ?? 0) ||
				a.eqs - b.eqs,
		);
	}, [
		metrics.accounts,
		anomaliesByAccount,
		healthByAccount,
		anomalyOnly,
		severity,
	]);

	const isThreads = platform === "threads";
	const visibleRows = showAll ? rows : rows.slice(0, 8);
	const hiddenCount = rows.length - visibleRows.length;
	const actionableCount = rows.filter(
		(row) =>
			row.anomalyCount > 0 ||
			row.healthBucket === "crit" ||
			row.severity?.severity === "critical" ||
			row.severity?.severity === "warning",
	).length;
	const isScoped = !!scopedAccount || !!(accountIds && accountIds.length > 0);
	const scopeEyebrow = scopedAccount
		? "Account"
		: isScoped
			? "Group"
			: "All accounts";
	const title = scopedAccount
		? "Selected account anomaly view"
		: isScoped
			? `${scopeLabel ?? "Selected group"} anomaly grid`
			: "Fleet anomaly grid";
	const description = scopedAccount
		? "Selected account metrics for this window · click row to drill"
		: isScoped
			? `${scopeLabel ?? "Selected group"} accounts sorted worst-first by 7d z-score vs 90d own-history · click row to drill`
			: "Sorted worst-first by 7d z-score vs 90d own-history · click row to drill";
	const investigateLabel = scopedAccount
		? "Selected account"
		: isScoped
			? `${scopeLabel ?? "Group"} anomalies`
			: "Fleet anomalies";

	return (
		<EvidenceCard
			id="evidence-1"
			className="analytics-fleet-anomaly-widget"
			eyebrow={scopeEyebrow}
			title={title}
			description={description}
			action={
				<div className="flex flex-wrap items-center justify-end gap-2">
					<Button
						type="button"
						variant={anomalyOnly ? "default" : "outline"}
						size="sm"
						onClick={() => setAnomalyOnly((v) => !v)}
						aria-pressed={anomalyOnly}
					>
						Anomaly only
					</Button>
					{actionableCount > 0 ? (
						<AnalyticsActionLink
							to={scopedRoute(
								"/accounts",
								{ scopedAccount, accountIds, groupId, platform },
								{ status: "flagged" },
							)}
							label="Fix accounts"
							icon={Wrench}
							tone="primary"
						/>
					) : null}
					<InvestigateButton
						accountId={scopedAccount?.id ?? null}
						metric={isThreads ? "views" : "reach"}
						metricLabel={investigateLabel}
						periodDays={days}
					/>
				</div>
			}
			contentClassName="flex h-full flex-col gap-3"
			footer={
				<div className="text-[0.6875rem] text-muted-foreground">
					SOURCE · 7d rolling z-score vs 90d own-history. Critical |z| &gt; 2.5,
					warning 2.0 &lt; |z| ≤ 2.5. Sorted worst-first.
				</div>
			}
		>
				<div className="min-h-0 flex-1">
					{metrics.isLoading ? (
						<FleetGridSkeleton />
					) : rows.length === 0 ? (
						<FleetGridEmpty
							anomalyOnly={anomalyOnly}
							onClearFilter={() => setAnomalyOnly(false)}
							accountsHref={scopedRoute("/accounts", {
								scopedAccount,
								accountIds,
								groupId,
								platform,
							})}
						/>
					) : (
						<>
							{sidecarHasError ? (
								<div className="mb-3 rounded-md border border-border bg-muted/40 px-3 py-2 text-[0.75rem] leading-relaxed text-muted-foreground">
									Some anomaly sidecars are unavailable; showing the live fleet
									roll-up with any available severity data.
								</div>
							) : null}
							{isThreads ? (
								<ThreadsTable rows={visibleRows} />
							) : (
								<IgTable rows={visibleRows} />
							)}
						</>
					)}
				</div>

				{hiddenCount > 0 || showAll ? (
					<div className="flex items-center justify-center gap-2 border-t border-border pt-3 text-[0.75rem] text-muted-foreground">
						<span>
							{showAll
								? `Showing all ${rows.length} accounts`
								: `+${hiddenCount} more`}
						</span>
						<Button
							type="button"
							variant="ghost"
							size="sm"
							onClick={() => setShowAll((v) => !v)}
						>
							{showAll ? "Collapse" : "Show all"}
						</Button>
					</div>
				) : null}
		</EvidenceCard>
	);
}

function FleetGridSkeleton() {
	return (
		<div>
			<div className="rounded-lg border border-border bg-muted/20 p-4">
				<div className="grid grid-cols-[1.4fr_0.8fr_0.8fr_0.8fr_0.8fr_0.6fr] gap-3 border-b border-border pb-3">
					{Array.from({ length: 6 }).map((_, index) => (
						<Skeleton
							key={index}
							className="h-2"
						/>
					))}
				</div>
				<div className="flex flex-col gap-3 pt-3">
					{Array.from({ length: 8 }).map((_, row) => (
						<div
							key={row}
							className="grid grid-cols-[1.4fr_0.8fr_0.8fr_0.8fr_0.8fr_0.6fr] items-center gap-3"
						>
							<div className="flex items-center gap-3">
								<Skeleton className="size-6 rounded-full" />
								<Skeleton className="h-2.5 w-28" />
							</div>
							{Array.from({ length: 5 }).map((_, col) => (
								<Skeleton
									key={`${row}-${col}`}
									className="ml-auto h-2"
									style={{ width: `${44 + ((row + col) % 3) * 16}px` }}
								/>
							))}
						</div>
					))}
				</div>
			</div>
		</div>
	);
}

function FleetGridEmpty({
	anomalyOnly,
	onClearFilter,
	accountsHref,
}: {
	anomalyOnly: boolean;
	onClearFilter: () => void;
	accountsHref: string;
}) {
	return (
		<NovaEmpty
			className="min-h-[260px]"
			title={anomalyOnly ? "No accounts match anomaly-only" : "No fleet rows to rank yet"}
			description={
				anomalyOnly
					? "The anomaly filter is active and no visible accounts currently cross the risk threshold. Clear it to inspect the full scoped fleet."
					: "Connect accounts or publish posts in this scope to populate per-account anomaly rows. The grid stays empty until live account metrics exist."
			}
			action={
				anomalyOnly ? (
					<Button type="button" variant="outline" onClick={onClearFilter}>
						Clear anomaly filter
					</Button>
				) : (
					<Button asChild>
						<Link to={accountsHref}>Open accounts</Link>
					</Button>
				)
			}
		/>
	);
}

function ThreadsTable({ rows }: { rows: EnrichedRow[] }) {
	const columns = useMemo<ColumnDef<EnrichedRow>[]>(
		() => [
			{
				id: "severity",
				header: "",
				enableSorting: false,
				cell: ({ row }) => <SeverityRail row={row.original} />,
				meta: {
					headerClassName: "w-[3px] p-0",
					cellClassName: "w-[3px] p-0",
				},
			},
			{
				accessorKey: "username",
				header: "Account",
				cell: ({ row }) => <AccountCell row={row.original} />,
				sortingFn: (a, b) =>
					(a.original.username ?? a.original.accountId).localeCompare(
						b.original.username ?? b.original.accountId,
					),
				meta: {
					headerClassName: "analytics-col-account px-4",
					cellClassName: "analytics-col-account px-4 py-2.5",
				},
			},
			{
				accessorKey: "reach",
				header: "Views",
				cell: ({ row }) => formatCompact(row.original.reach),
				meta: {
					headerClassName: "analytics-col-primary text-right",
					cellClassName:
						"analytics-col-primary px-3 py-2.5 text-right tabular-nums font-medium text-foreground",
				},
			},
			{
				accessorKey: "reachDeltaPct",
				header: "Δ vs prior",
				cell: ({ row }) => <DeltaCell value={row.original.reachDeltaPct} />,
				sortUndefined: "last",
				meta: {
					headerClassName: "analytics-col-delta text-right",
					cellClassName: "analytics-col-delta px-3 py-2.5 text-right tabular-nums",
				},
			},
			{
				accessorKey: "sends",
				header: "Reposts",
				cell: ({ row }) => formatCompact(row.original.sends),
				meta: {
					headerClassName: "analytics-col-secondary text-right",
					cellClassName:
						"analytics-col-secondary px-3 py-2.5 text-right tabular-nums text-muted-foreground",
				},
			},
			{
				accessorKey: "comments",
				header: "Replies",
				cell: ({ row }) => formatCompact(row.original.comments),
				meta: {
					headerClassName: "analytics-col-secondary text-right",
					cellClassName:
						"analytics-col-secondary px-3 py-2.5 text-right tabular-nums text-muted-foreground",
				},
			},
			{
				accessorKey: "posts",
				header: "Posts",
				meta: {
					headerClassName: "analytics-col-posts text-right",
					cellClassName:
						"analytics-col-posts px-3 py-2.5 text-right tabular-nums text-muted-foreground",
				},
			},
			{
				id: "flag",
				header: "Flag",
				enableSorting: false,
				cell: ({ row }) => <FlagPill row={row.original} />,
				meta: {
					headerClassName: "analytics-col-flag px-4 text-right",
					cellClassName: "analytics-col-flag px-4 py-2.5 text-right",
				},
			},
		],
		[],
	);
	const drillIn = (row: EnrichedRow) => {
		useAccountScopeStore.getState().setScope({
			id: row.accountId,
			handle: row.username ?? row.accountId,
			platform: row.platform,
		});
	};

	return (
		<DataTable
			data={rows}
			columns={columns}
			ariaLabel="Threads fleet anomaly grid"
			tableClassName="analytics-fleet-table"
			onRowClick={drillIn}
			rowClassName="hover:bg-[color-mix(in_srgb,var(--color-foreground)_3%,transparent)]"
		/>
	);
}

function IgTable({ rows }: { rows: EnrichedRow[] }) {
	const columns = useMemo<ColumnDef<EnrichedRow>[]>(
		() => [
			{
				id: "severity",
				header: "",
				enableSorting: false,
				cell: ({ row }) => <SeverityRail row={row.original} />,
				meta: {
					headerClassName: "w-[3px] p-0",
					cellClassName: "w-[3px] p-0",
				},
			},
			{
				accessorKey: "username",
				header: "Account",
				cell: ({ row }) => <AccountCell row={row.original} />,
				sortingFn: (a, b) =>
					(a.original.username ?? a.original.accountId).localeCompare(
						b.original.username ?? b.original.accountId,
					),
				meta: {
					headerClassName: "analytics-col-account px-4",
					cellClassName: "analytics-col-account px-4 py-2.5",
				},
			},
			{
				accessorKey: "reach",
				header: "Reach",
				cell: ({ row }) => formatCompact(row.original.reach),
				meta: {
					headerClassName: "analytics-col-primary text-right",
					cellClassName:
						"analytics-col-primary px-3 py-2.5 text-right tabular-nums font-medium text-foreground",
				},
			},
			{
				accessorKey: "reachDeltaPct",
				header: "Δ vs prior",
				cell: ({ row }) => <DeltaCell value={row.original.reachDeltaPct} />,
				sortUndefined: "last",
				meta: {
					headerClassName: "analytics-col-delta text-right",
					cellClassName: "analytics-col-delta px-3 py-2.5 text-right tabular-nums",
				},
			},
			{
				accessorKey: "engagementRate",
				header: "Eng rate",
				cell: ({ row }) =>
					row.original.reach > 0
						? `${row.original.engagementRate.toFixed(1)}%`
						: "—",
				meta: {
					headerClassName: "analytics-col-secondary text-right",
					cellClassName:
						"analytics-col-secondary px-3 py-2.5 text-right tabular-nums text-muted-foreground",
				},
			},
			{
				id: "saveRate",
				header: "Save rate",
				accessorFn: (row) => (row.reach > 0 ? (row.saves / row.reach) * 100 : null),
				cell: ({ row }) =>
					row.original.reach > 0
						? `${((row.original.saves / row.original.reach) * 100).toFixed(1)}%`
						: "—",
				sortUndefined: "last",
				meta: {
					headerClassName: "analytics-col-secondary text-right",
					cellClassName:
						"analytics-col-secondary px-3 py-2.5 text-right tabular-nums text-muted-foreground",
				},
			},
			{
				accessorKey: "posts",
				header: "Posts",
				meta: {
					headerClassName: "analytics-col-posts text-right",
					cellClassName:
						"analytics-col-posts px-3 py-2.5 text-right tabular-nums text-muted-foreground",
				},
			},
			{
				id: "flag",
				header: "Flag",
				enableSorting: false,
				cell: ({ row }) => <FlagPill row={row.original} />,
				meta: {
					headerClassName: "analytics-col-flag px-4 text-right",
					cellClassName: "analytics-col-flag px-4 py-2.5 text-right",
				},
			},
		],
		[],
	);
	const drillIn = (row: EnrichedRow) => {
		useAccountScopeStore.getState().setScope({
			id: row.accountId,
			handle: row.username ?? row.accountId,
			platform: row.platform,
		});
	};

	return (
		<DataTable
			data={rows}
			columns={columns}
			ariaLabel="Instagram fleet anomaly grid"
			tableClassName="analytics-fleet-table"
			onRowClick={drillIn}
			rowClassName="hover:bg-[color-mix(in_srgb,var(--color-foreground)_3%,transparent)]"
		/>
	);
}

function DeltaCell({ value }: { value: number | null }) {
	if (value == null) {
		return <span className="text-muted-foreground/70">—</span>;
	}
	const tone =
		value >= 5
			? "var(--color-health-good)"
			: value <= -10
				? "var(--color-oxblood)"
				: value <= -5
					? "var(--color-gold)"
					: "var(--color-muted-foreground)";
	return (
		<span style={{ color: tone }}>
			{value >= 0 ? "+" : ""}
			{value.toFixed(1)}%
		</span>
	);
}

function SeverityRail({ row }: { row: EnrichedRow }) {
	const severity = severityFor(row);
	return (
		<div
			className="h-full min-h-9 w-[3px]"
			style={{ backgroundColor: severity.accent }}
			aria-hidden="true"
		/>
	);
}

function AccountCell({ row }: { row: EnrichedRow }) {
	return (
		<div className="flex items-center gap-2.5">
			<AccountAvatar handle={row.username ?? row.accountId} size={22} />
			<div className="flex flex-col min-w-0">
				<span className="font-medium text-foreground truncate">
					{row.username ?? "Unnamed"}
				</span>
				<span className="text-[0.6875rem] text-muted-foreground">
					{row.platform} · {row.posts} post{row.posts === 1 ? "" : "s"}
				</span>
			</div>
		</div>
	);
}

function FlagPill({ row }: { row: EnrichedRow }) {
	// Priority: z-score severity first (that's the new Wave 2 ground truth),
	// then explicit anomaly-feed alerts, then fleet-health verdicts, then the
	// top-decile / below-cohort affordances.
	const sev = row.severity?.severity;
	const z = row.severity?.z ?? null;

	if (sev === "critical") {
		const reason = (row.healthReason ?? "").toLowerCase();
		if (reason.includes("suppress"))
			return <Badge tone="danger">Suppressed</Badge>;
		if (reason.includes("crash") || reason.includes("reach"))
			return <Badge tone="danger">Crash</Badge>;
		return <Badge tone="danger">Z {z !== null ? zFmt(z) : "—"}</Badge>;
	}
	if (sev === "warning") {
		return <Badge tone="outline">Z {z !== null ? zFmt(z) : "—"}</Badge>;
	}
	if (row.healthBucket === "crit") {
		return (
			<Badge tone="danger">
				{row.healthReason?.toUpperCase() ?? "CRIT"}
			</Badge>
		);
	}
	if (row.anomalyCount >= 2) {
		return <Badge tone="oxblood">{row.anomalyCount} alerts</Badge>;
	}
	if (row.anomalyCount === 1) {
		return <Badge tone="outline">Alert</Badge>;
	}
	if (row.healthBucket === "warn") {
		return <Badge tone="outline">Dormant</Badge>;
	}
	if (row.eqs >= 75) {
		return <Badge tone="secondary">Top decile</Badge>;
	}
	if (row.eqs < 30 && row.posts > 0) {
		return <Badge tone="outline">Below</Badge>;
	}
	return null;
}

interface Severity {
	rank: number; // lower = more severe (ascending sort key)
	label: string;
	accent: string;
}

function severityFor(row: EnrichedRow): Severity {
	const sev = row.severity?.severity;
	const z = row.severity?.z;
	const zStr = typeof z === "number" ? zFmt(z) : "—";
	const oxblood = "var(--color-oxblood)";
	const gold = "var(--color-gold)";

	if (sev === "critical")
		return { rank: 0, label: `critical (z ${zStr})`, accent: oxblood };
	if (row.healthBucket === "crit")
		return { rank: 0, label: "critical", accent: oxblood };
	if (sev === "warning")
		return { rank: 1, label: `warning (z ${zStr})`, accent: gold };
	if (row.anomalyCount >= 2)
		return { rank: 1, label: `${row.anomalyCount} alerts`, accent: oxblood };
	if (row.healthBucket === "warn")
		return { rank: 2, label: "warning", accent: gold };
	if (row.anomalyCount === 1) return { rank: 2, label: "alert", accent: gold };
	if (row.eqs >= 75)
		return { rank: 3, label: "top decile", accent: "transparent" };
	return { rank: 3, label: "healthy", accent: "transparent" };
}

function zFmt(z: number): string {
	const sign = z >= 0 ? "+" : "−";
	return `${sign}${Math.abs(z).toFixed(1)}`;
}
