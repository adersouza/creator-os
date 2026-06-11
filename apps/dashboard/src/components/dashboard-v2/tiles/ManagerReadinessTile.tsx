import { BrainCircuit, CalendarRange, ExternalLink, RefreshCw } from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { useOperatorSnapshot } from "@/hooks/useOperatorSnapshot";
import { cn } from "@/lib/utils";
import type { DashboardScopeProps } from "../scope";

function toneClass(tone: string) {
	if (tone === "critical") return "text-primary";
	if (tone === "warning") return "text-warning";
	return "text-success";
}

function matchesScope(
	day: { accountIds?: string[] | undefined },
	scope: DashboardScopeProps,
) {
	if (scope.scopedAccount) return day.accountIds?.includes(scope.scopedAccount.id) ?? false;
	if (scope.groupId && scope.accountIds?.length) {
		return (day.accountIds ?? []).some((id) => scope.accountIds?.includes(id));
	}
	return true;
}

export function FleetCapacityTile(props: DashboardScopeProps) {
	const navigate = useNavigate();
	const { snapshot, isLoading, refetch } = useOperatorSnapshot();
	const capacity = snapshot.fleetCapacity;
	const scopedDays = useMemo(
		() => capacity.days.filter((day) => matchesScope(day, props)),
		[capacity.days, props],
	);
	const visibleDays = scopedDays.length > 0 ? scopedDays : capacity.days;
	const problemDays = visibleDays.filter((day) => day.tone !== "healthy").length;
	const scopedTone = visibleDays.some((day) => day.tone === "critical")
		? "critical"
		: problemDays > 0
			? "warning"
			: capacity.tone;
	const scheduled = visibleDays.reduce((sum, day) => sum + day.scheduled + day.pendingQueue, 0);
	const failed = visibleDays.reduce((sum, day) => sum + day.failed + day.deadLetter, 0);

	return (
		<NovaCard className="h-full" contentClassName="flex h-full flex-col">
			<div className="flex items-start justify-between gap-3">
				<div>
					<span className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Posting coverage</span>
					<div className="mt-2 flex items-center gap-3">
						<BrandLogo name="meta" size="sm" />
						<CalendarRange
							aria-hidden="true"
							className={toneClass(scopedTone)}
						/>
						<div className="text-[32px] font-semibold leading-none text-foreground tabular-nums">
							{isLoading ? "..." : scheduled}
						</div>
					</div>
					<div className="mt-1 text-xs text-muted-foreground">
						{props.scopeLabel ?? "Visible scope"} · next 7 days scheduled and queued.
					</div>
				</div>
				<Button type="button" size="sm" variant="outline" onClick={() => void refetch()} disabled={isLoading}>
					<RefreshCw data-icon="inline-start" className={isLoading ? "animate-spin" : undefined} />
					Refresh
				</Button>
			</div>

			<div className="mt-4 grid grid-cols-7 gap-1.5 rounded-lg border border-border bg-muted/35 p-2">
				{visibleDays.slice(0, 7).map((day) => (
					<Button
						key={day.date}
						type="button"
						variant="ghost"
						className="h-auto min-h-0 flex-col items-start justify-start gap-1 rounded-md px-2 py-2 text-left"
						onClick={() => navigate(`/calendar?date=${day.date}`)}
						title={`${day.date}: ${day.scheduled + day.pendingQueue} planned, ${day.failed + day.deadLetter} failed/DLQ`}
					>
						<span className="text-[10px] text-muted-foreground">
							{new Date(`${day.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "short" })}
						</span>
						<span
							className={cn("text-sm font-semibold", toneClass(day.tone))}
						>
							{day.scheduled + day.pendingQueue}
						</span>
					</Button>
				))}
			</div>

			<div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs">
				<span className="text-muted-foreground">
					{failed > 0 ? `${failed} failed or DLQ item${failed === 1 ? "" : "s"} need recovery.` : `${capacity.activeAccountCount} active accounts covered.`}
				</span>
				<Button type="button" size="sm" onClick={() => navigate("/calendar")}>
					Calendar
					<ExternalLink data-icon="inline-end" />
				</Button>
			</div>
		</NovaCard>
	);
}

export function AIEvalSummaryTile() {
	const navigate = useNavigate();
	const { snapshot, isLoading } = useOperatorSnapshot();
	const evals = snapshot.aiEvalSummary;
	const coverage = evals.coverage;
	const recentTrend = evals.trend.slice(-5);
	const suiteRows = evals.suites.slice(0, 4);
	const latestFailures = evals.latestFailures.slice(0, 2);
	const coverageCopy =
		coverage.directGenerativeSurfaceCount > 0
			? `${coverage.directGenerativeCoveredCount}/${coverage.directGenerativeSurfaceCount} direct AI surfaces covered`
			: "Direct AI coverage registry ready";
	return (
		<NovaCard className="h-full" contentClassName="flex h-full flex-col">
			<div className="flex items-start justify-between gap-3">
				<div>
					<span className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">AI readiness</span>
					<div className="mt-2 flex items-center gap-3">
						<BrainCircuit aria-hidden="true" className={toneClass(evals.tone)} />
						<div className="text-[32px] font-semibold leading-none text-foreground tabular-nums">
							{isLoading ? "..." : `${evals.passRate}%`}
						</div>
					</div>
					<div className="mt-1 text-xs text-muted-foreground">
						Last {evals.windowDays} days · content assistant quality checks.
					</div>
				</div>
				<Button type="button" size="sm" onClick={() => navigate("/settings?tab=ai")}>
					AI
					<ExternalLink data-icon="inline-end" />
				</Button>
			</div>

			<div className="mt-4 grid grid-cols-3 gap-2">
				{[
					["Total", evals.total, "default"],
					["Passed", evals.passed, "good"],
					["Failed", evals.failed, evals.failed > 0 ? "critical" : "good"],
				].map(([label, value, tone]) => (
					<div
						key={label}
						className="rounded-lg border border-border bg-muted/35 p-3"
					>
						<div className="text-xs font-medium text-muted-foreground">{label}</div>
						<div
							className={cn(
								"mt-2 text-2xl font-semibold text-foreground tabular-nums",
								tone === "critical" && "text-primary",
								tone === "good" && "text-success",
							)}
						>
							{value}
						</div>
						{label === "Failed" && Number(value) > 0 ? (
							<div className="mt-1 text-xs text-muted-foreground">Watch</div>
						) : null}
					</div>
				))}
			</div>

				{recentTrend.length > 0 && (
					<div className="mt-4 flex h-10 items-end gap-1.5" title="AI eval pass-rate trend">
						{recentTrend.map((point) => (
							<div
								key={`${point.day}-${point.suiteName}-${point.surface}`}
								className={cn(
									"min-w-0 flex-1 rounded-sm",
									point.failed > 0 ? "bg-warning" : "bg-success",
								)}
								style={{
									height: `${Math.max(8, point.passRate)}%`,
								}}
								title={`${point.day} ${point.suiteName}/${point.surface}: ${point.passRate}% pass rate`}
							/>
						))}
					</div>
				)}

				{suiteRows.length > 0 && (
					<div className="mt-4 grid gap-2 rounded-lg border border-border bg-muted/35 p-2">
						{suiteRows.map((suite) => (
							<div key={`${suite.suiteName}-${suite.surface}`} className="flex items-center justify-between gap-3 rounded-md border border-border bg-card/55 px-3 py-2 text-xs">
								<div className="min-w-0">
									<div className="truncate font-medium text-foreground">
										{suite.suiteName.replace(/^live:/, "")}
									</div>
									<div className="truncate text-muted-foreground">{suite.surface}</div>
								</div>
								<div className="shrink-0 text-right">
									<div
										className={cn(
											"font-semibold",
											suite.failed > 0 ? "text-primary" : "text-success",
										)}
									>
										{suite.passRate}%
									</div>
									<div className="text-muted-foreground">{suite.total} run{suite.total === 1 ? "" : "s"}</div>
								</div>
							</div>
						))}
					</div>
				)}

				{latestFailures.length > 0 && (
					<div className="mt-4 flex flex-col gap-1.5 text-xs">
						{latestFailures.map((failure) => (
							<div key={`${String(failure.id)}-${String(failure.capturedAt)}`} className="text-muted-foreground">
								<span className="text-primary">
									{String(failure.suiteName ?? "eval")}
								</span>
								{" · "}
								{String(failure.caseId ?? "case")}
								{failure.failures.length > 0 ? ` · ${String(failure.failures[0])}` : ""}
							</div>
						))}
					</div>
				)}

				<div className="mt-4 text-xs text-muted-foreground">
					{evals.thresholds.failures.length > 0
						? evals.thresholds.failures[0]
						: coverage.uncoveredDirectSurfaces.length > 0
						? `${coverageCopy}; missing recent live snapshots for ${coverage.uncoveredDirectSurfaces.slice(0, 2).join(", ")}.`
						: evals.latestFailures.length > 0
						? "Recent failures are captured for prompt/model regression follow-up."
						: `${coverageCopy}; ${coverage.documentedNonGenerativeCount} non-generative surfaces documented.`}
				</div>
		</NovaCard>
	);
}
