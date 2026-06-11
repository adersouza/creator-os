import { useMemo } from "react";
import { useEngagementVelocity } from "@/hooks/useEngagementVelocity";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { formatCompact } from "../shared";

interface Props {
	days?: number | undefined;
	platform?: "all" | "threads" | "instagram" | undefined;
	scopedAccount?: ScopedAccountLite | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
	/** Max hours-since-publish for the first snapshot to count. */
	maxAgeHours?: number | undefined;
}

/**
 * §6 First-hour engagement velocity. For each post in the window, takes
 * its earliest `post_metric_history` snapshot within `maxAgeHours` of
 * publish and renders the views/hour distribution as a horizontal box-plot
 * (p25 / median / p75 / max). Below the plot, the top + bottom samples by
 * velocity surface so the user can drill in.
 *
 * Pure measurement — no Meta-API extension required. The data lives in
 * post_metric_history, which is populated by the analytics-pipeline cron.
 */
export function EngagementVelocityChart({
	days = 30,
	platform = "instagram",
	scopedAccount: scopedAccountProp,
	accountIds,
	groupId,
	maxAgeHours = 6,
}: Props) {
	const storeScopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const rawScope = scopedAccountProp ?? storeScopedAccount;
	const scopedAccount =
		rawScope?.id && rawScope.handle
			? {
					id: rawScope.id,
					handle: rawScope.handle,
					platform: rawScope.platform,
				}
			: null;
	const { samples, p25, p50, p75, max, isLoading, hasError } =
		useEngagementVelocity({
			days,
			platform,
			scopedAccount,
			accountIds: scopedAccount ? undefined : accountIds,
			groupId: scopedAccount ? null : groupId,
			maxAgeHours,
		});

	const { topSamples, bottomSamples } = useMemo(() => {
		const sorted = [...samples].sort((a, b) => b.viewsPerHour - a.viewsPerHour);
		return {
			topSamples: sorted.slice(0, 3),
			bottomSamples: sorted.slice(-3).reverse(),
		};
	}, [samples]);

	if (isLoading && samples.length === 0) {
		return (
			<EvidenceCard
				state="loading"
				title="First-hour velocity"
				description={`Last ${days}d · views/hour at first snapshot`}
			>
				<div
					className="flex flex-col gap-3"
					role="status"
					aria-label="Loading first-hour velocity"
				>
					<Skeleton className="h-24 w-full rounded-lg" />
					<div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
						<Skeleton className="h-28 w-full rounded-lg" />
						<Skeleton className="h-28 w-full rounded-lg" />
					</div>
				</div>
			</EvidenceCard>
		);
	}

	if (hasError) {
		return (
			<EvidenceCard
				state="empty"
				title="First-hour velocity"
				description="Velocity"
			>
				<NovaEmpty
					title="First-hour data unavailable"
					description="First-hour snapshot data did not return for this scope. The chart waits for a valid post-metric history payload instead of plotting a misleading flatline."
				/>
			</EvidenceCard>
		);
	}

	if (samples.length === 0) {
		return (
			<EvidenceCard
				state="empty"
				title="First-hour velocity"
				description="Velocity"
			>
				<NovaEmpty
					title="No early snapshots yet"
					description={`No posts had a snapshot within ${maxAgeHours}h of publish in the last ${days} days. The analytics-pipeline cron captures snapshots; coverage fills in as it runs.`}
				/>
			</EvidenceCard>
		);
	}

	// Render box-plot maths: scale every value to the same axis, anchored
	// to the max so the whisker reaches 100%.
	const axisMax = max ?? 1;
	const pct = (v: number) => Math.max(0, Math.min(100, (v / axisMax) * 100));

	return (
		<EvidenceCard
			title="First-hour velocity"
			description={`${samples.length} post${samples.length === 1 ? "" : "s"} · last ${days}d · within ${maxAgeHours}h of publish`}
			action={
				<InvestigateButton
					accountId={scopedAccount?.id ?? null}
					metric="reach"
					metricLabel="First-hour velocity"
					periodDays={days}
				/>
			}
			footer={
				<div className="text-xs uppercase tracking-[0.08em] text-muted-foreground">
					SOURCE · earliest `post_metric_history` snapshot per post within{" "}
					{maxAgeHours}h of publish · {samples.length} sample
					{samples.length === 1 ? "" : "s"}.
				</div>
			}
		>
			<div className="flex flex-col gap-4">
				{/* Box plot. */}
				<div className="flex flex-col gap-2 rounded-lg border border-border/70 bg-muted/20 px-3 py-3">
					<div className="flex flex-col gap-1 text-[0.6875rem] tabular-nums sm:flex-row sm:items-center sm:justify-between">
						<span className="text-muted-foreground">Views / hour</span>
						<span className="min-w-0 truncate font-mono text-muted-foreground">
							p25 {fmt(p25)} · p50 {fmt(p50)} · p75 {fmt(p75)} · max{" "}
							{fmt(max)}
						</span>
					</div>
					<div className="relative h-8">
						<div className="absolute inset-x-0 top-1/2 h-px bg-muted-foreground/30" />
						{p25 != null && p75 != null ? (
							<div
								role="img"
								className="absolute bottom-2 top-2 rounded"
								style={{
									left: `${pct(p25)}%`,
									width: `${Math.max(2, pct(p75) - pct(p25))}%`,
									background:
										"color-mix(in srgb, var(--color-chart-1) 28%, transparent)",
									border: "1px solid var(--color-chart-1)",
								}}
								aria-label="Interquartile range"
							/>
						) : null}
						{p50 != null ? (
							<div
								role="img"
								className="absolute bottom-2 top-2 w-[2px]"
								style={{
									left: `${pct(p50)}%`,
									background: "var(--color-chart-1)",
								}}
								aria-label="Median"
							/>
						) : null}
						{max != null ? (
							<div
								role="img"
								className="absolute top-1/2 size-2 -translate-y-1/2 rounded-full"
								style={{
									left: `${pct(max)}%`,
									transform: "translate(-50%, -50%)",
									background: "var(--color-chart-2)",
								}}
								aria-label="Max"
							/>
						) : null}
					</div>
				</div>

				{/* Top + bottom samples. */}
				<div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
					<SampleList
						title="Top first-hour velocity"
						samples={topSamples}
						tone="good"
					/>
					<SampleList
						title="Slow starters"
						samples={bottomSamples}
						tone="warn"
					/>
				</div>
			</div>
		</EvidenceCard>
	);
}

function SampleList({
	title,
	samples,
	tone,
}: {
	title: string;
	samples: ReturnType<typeof useEngagementVelocity>["samples"];
	tone: "good" | "warn";
}) {
	const color =
		tone === "good" ? "var(--color-health-good)" : "var(--color-warning)";
	return (
		<div className="rounded-md border border-border/70 bg-card/35 px-3 py-2">
			<div className="mb-2 text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">
				{title}
			</div>
			<ul className="flex flex-col gap-1">
				{samples.map((s) => (
					<li
						key={s.postId}
						className="flex items-center justify-between gap-2 text-[0.75rem]"
					>
						<span className="min-w-0 truncate text-muted-foreground tabular-nums">
							{s.hoursSincePublish.toFixed(1)}h ·{" "}
							{formatCompact(s.viewsAtSnapshot)}
						</span>
						<span className="shrink-0 font-mono tabular-nums" style={{ color }}>
							{formatCompact(s.viewsPerHour)}/h
						</span>
					</li>
				))}
			</ul>
		</div>
	);
}

function fmt(n: number | null): string {
	if (n == null || !Number.isFinite(n)) return "—";
	return formatCompact(n);
}
