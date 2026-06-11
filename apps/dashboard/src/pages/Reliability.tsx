import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
	AlertTriangle,
	CheckCircle2,
	Clock3,
	ExternalLink,
	ShieldCheck,
} from "lucide-react";
import { z } from "zod";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ListRow } from "@/components/ui/ListRow";
import {
	NovaCard,
	NovaEmpty,
	NovaHeader,
	NovaStat,
} from "@/components/ui/NovaPrimitives";
import { apiFetch } from "@/lib/apiFetch";
import { useOperatorSnapshot } from "@/hooks/useOperatorSnapshot";
import { queryKeys } from "@/lib/queryKeys";

const recordSchema = z.record(z.string(), z.unknown());
const reliabilityResponseSchema = z.object({
	success: z.boolean().optional(),
	generatedAt: z.string().optional(),
	reliabilitySlo: z
		.object({
			tone: z.enum(["healthy", "warning", "critical"]).default("healthy"),
			scheduledTotal: z.number().default(0),
			publishedTotal: z.number().default(0),
			failedTotal: z.number().default(0),
			onTimeRate: z.number().default(100),
			successRate: z.number().default(100),
			lateOver5m: z.number().default(0),
			qstashFailures: z.number().default(0),
			dlqCount: z.number().default(0),
			backlogCount: z.number().default(0),
			driftSeconds: z
				.object({
					p50: z.number().default(0),
					p95: z.number().default(0),
					p99: z.number().default(0),
					max: z.number().default(0),
					avg: z.number().default(0),
				})
				.default({ p50: 0, p95: 0, p99: 0, max: 0, avg: 0 }),
			issues: z.array(recordSchema).default([]),
			trend: z.array(recordSchema).default([]),
		})
		.passthrough(),
	metaApiUsage: z
		.object({
			tone: z.enum(["healthy", "warning", "critical"]).default("healthy"),
			maxUsagePercent: z.number().default(0),
			retryAfterActiveCount: z.number().default(0),
			warningCount: z.number().default(0),
			criticalCount: z.number().default(0),
			latest: z.array(recordSchema).default([]),
		})
		.passthrough(),
	webhookHealth: z
		.object({
			tone: z.enum(["healthy", "warning", "critical"]).default("healthy"),
			failedDeliveries: z.number().default(0),
			deadLetterDeliveries: z.number().default(0),
			threadsDeadLetters: z.number().default(0),
			instagramDeadLetters: z.number().default(0),
			nextRetryCount: z.number().default(0),
			issues: z.array(recordSchema).default([]),
		})
		.passthrough(),
	tokenSlo: z
		.object({
			tone: z.enum(["healthy", "warning", "critical"]).default("healthy"),
			totalIssues: z.number().default(0),
			needsReauth: z.number().default(0),
			expiringSoon: z.number().default(0),
			expired: z.number().default(0),
			accounts: z.array(recordSchema).default([]),
		})
		.passthrough(),
});

type ReliabilityResponse = z.infer<typeof reliabilityResponseSchema>;
type Tone = "healthy" | "warning" | "critical";

function toneColor(tone: Tone) {
	if (tone === "critical") return "var(--color-oxblood)";
	if (tone === "warning") return "var(--color-gold)";
	return "var(--color-health-good)";
}

function toneLabel(tone: Tone) {
	if (tone === "critical") return "Critical";
	if (tone === "warning") return "Watch";
	return "Healthy";
}

function badgeTone(tone: Tone): "secondary" | "danger" | "oxblood" {
	if (tone === "critical") return "danger";
	if (tone === "warning") return "oxblood";
	return "secondary";
}

function num(value: unknown) {
	const number = Number(value);
	return Number.isFinite(number) ? number : 0;
}

function pct(value: number) {
	return `${value.toFixed(value >= 99 ? 1 : 0)}%`;
}

export function Reliability() {
	const navigate = useNavigate();
	const operator = useOperatorSnapshot();
	const query = useQuery({
		queryKey: queryKeys.system.reliabilitySummary(24),
		staleTime: 60_000,
		queryFn: () =>
			apiFetch(
				"/api/reliability?action=slo-summary&windowHours=24",
				reliabilityResponseSchema,
			),
	});
	const data: ReliabilityResponse = query.data ?? {
		reliabilitySlo: operator.snapshot.reliabilitySlo,
		metaApiUsage: operator.snapshot.metaApiUsage,
		webhookHealth: operator.snapshot.webhookHealth,
		tokenSlo: operator.snapshot.tokenSlo,
	};
	const overallTone = useMemo<Tone>(() => {
		const tones = [
			data.reliabilitySlo.tone,
			data.metaApiUsage.tone,
			data.webhookHealth.tone,
			data.tokenSlo.tone,
		];
		if (tones.includes("critical")) return "critical";
		if (tones.includes("warning")) return "warning";
		return "healthy";
	}, [data]);
	const refresh = () => {
		void operator.refetch();
		void query.refetch();
	};

	return (
		<NovaScreen width="full" density="compact" className="max-w-[1440px]">
			<NovaHeader
				eyebrow="Production reliability"
				title="Reliability Center"
				description="Scheduling SLOs, Meta usage, webhook replay health, and token risk for the current workspace."
				meta="Read-only · recovery routes only"
				actions={
					<div className="flex flex-wrap items-center gap-2">
						<Badge tone={badgeTone(overallTone)}>
							{toneLabel(overallTone)}
						</Badge>
						<Button
							type="button"
							variant="outline"
							onClick={refresh}
							disabled={query.isFetching || operator.isLoading}
						>
							{query.isFetching || operator.isLoading
								? "Refreshing"
								: "Refresh"}
						</Button>
					</div>
				}
			/>

			<div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
				<NovaCard
					variant="hero"
					eyebrow="Scheduled publishing SLO"
					title="Will scheduled posts land on time?"
					description="Target: 99.9% publish within 60 seconds; delayed over 5 minutes becomes operator work."
					action={<HealthIcon tone={data.reliabilitySlo.tone} />}
				>
					<div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
						<NovaStat
							label="On-time rate"
							value={pct(data.reliabilitySlo.onTimeRate)}
							trend={
								data.reliabilitySlo.onTimeRate < 99.9
									? { direction: "down", label: "watch" }
									: "healthy"
							}
							variant="compact"
						/>
						<NovaStat
							label="Success rate"
							value={pct(data.reliabilitySlo.successRate)}
							trend={
								data.reliabilitySlo.failedTotal > 0
									? { direction: "down", label: "failed" }
									: "healthy"
							}
							variant="compact"
						/>
						<NovaStat
							label="P95 drift"
							value={`${data.reliabilitySlo.driftSeconds.p95}s`}
							trend={
								data.reliabilitySlo.driftSeconds.p95 > 300
									? { direction: "down", label: "critical" }
									: data.reliabilitySlo.driftSeconds.p95 > 60
										? "watch"
										: "healthy"
							}
							variant="compact"
						/>
						<NovaStat
							label="DLQ / backlog"
							value={`${data.reliabilitySlo.dlqCount}/${data.reliabilitySlo.backlogCount}`}
							trend={
								data.reliabilitySlo.dlqCount > 0
									? { direction: "down", label: "dlq" }
									: data.reliabilitySlo.backlogCount > 20
										? "watch"
										: "healthy"
							}
							variant="compact"
						/>
					</div>
					<div className="mt-5 grid gap-3 md:grid-cols-3">
						<SmallStat
							label="Scheduled"
							value={data.reliabilitySlo.scheduledTotal}
						/>
						<SmallStat
							label="Published"
							value={data.reliabilitySlo.publishedTotal}
						/>
						<SmallStat label="Failed" value={data.reliabilitySlo.failedTotal} />
					</div>
					<IssueList
						issues={data.reliabilitySlo.issues}
						empty="No scheduling SLO blockers in the current window."
						onRoute={(route) => navigate(route)}
					/>
				</NovaCard>

				<NovaCard
					eyebrow="Token SLO"
					title="Accounts that could fail tomorrow"
					action={<HealthIcon tone={data.tokenSlo.tone} />}
				>
					<div className="mt-5 grid grid-cols-3 gap-2">
						<SmallStat label="Reauth" value={data.tokenSlo.needsReauth} />
						<SmallStat label="Expiring" value={data.tokenSlo.expiringSoon} />
						<SmallStat label="Expired" value={data.tokenSlo.expired} />
					</div>
					<NovaCard
						variant="panel"
						className="mt-4 overflow-hidden"
						contentClassName="p-0"
					>
						{data.tokenSlo.accounts.length === 0 ? (
							<NovaEmpty
								className="min-h-0 p-3"
								title="No token issues"
								description="No token issues in the 7-day warning window."
							/>
						) : (
							data.tokenSlo.accounts.slice(0, 8).map((account) => (
								<ListRow
									key={String(account.id)}
									density="compact"
									onClick={() =>
										navigate(
											String(account.route || "/accounts?status=flagged"),
										)
									}
								>
									<div className="flex items-center justify-between gap-3">
										<div className="min-w-0">
											<div className="truncate text-sm font-semibold">
												@{String(account.handle || account.id)}
											</div>
											<div className="mt-1 truncate text-xs text-muted-foreground">
												{String(account.platform || "account")} · expires{" "}
												{String(account.token_expires_at || "unknown")}
											</div>
										</div>
										<ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
									</div>
								</ListRow>
							))
						)}
					</NovaCard>
				</NovaCard>
			</div>

			<div className="grid gap-4 lg:grid-cols-2">
				<NovaCard
					eyebrow="Meta API usage"
					title="Rate-limit pressure"
					description="Captured from Meta usage headers and Retry-After responses."
					action={<HealthIcon tone={data.metaApiUsage.tone} />}
				>
					<div className="mt-5 grid gap-3 sm:grid-cols-3">
						<NovaStat
							label="Max usage"
							value={`${data.metaApiUsage.maxUsagePercent}%`}
							trend={
								data.metaApiUsage.maxUsagePercent >= 95
									? { direction: "down", label: "critical" }
									: data.metaApiUsage.maxUsagePercent >= 80
										? "watch"
										: "healthy"
							}
							variant="compact"
						/>
						<NovaStat
							label="Retry-After"
							value={data.metaApiUsage.retryAfterActiveCount}
							trend={
								data.metaApiUsage.retryAfterActiveCount > 0
									? { direction: "down", label: "active" }
									: "healthy"
							}
							variant="compact"
						/>
						<NovaStat
							label="Warnings"
							value={
								data.metaApiUsage.warningCount + data.metaApiUsage.criticalCount
							}
							trend={
								data.metaApiUsage.criticalCount > 0
									? { direction: "down", label: "critical" }
									: data.metaApiUsage.warningCount > 0
										? "watch"
										: "healthy"
							}
							variant="compact"
						/>
					</div>
					<NovaCard
						variant="panel"
						className="mt-4 overflow-hidden"
						contentClassName="p-0"
					>
						{data.metaApiUsage.latest.length === 0 ? (
							<NovaEmpty
								className="min-h-0 rounded-none border-0 bg-transparent p-3"
								title="No pressure captured"
								description="No Meta usage pressure captured in this window."
							/>
						) : (
							data.metaApiUsage.latest.slice(0, 8).map((row) => (
								<div
									key={String(
										row.id ??
											`${row.platform}:${row.endpoint_family}:${row.captured_at}`,
									)}
									className="grid grid-cols-[1fr_auto_auto] gap-3 border-b border-border p-3 text-sm last:border-b-0"
								>
									<div className="min-w-0 truncate">
										{String(row.platform || "meta")} ·{" "}
										{String(row.endpoint_family || "unknown")}
									</div>
									<div className="tabular-nums text-muted-foreground">
										{num(row.usage_percent)}%
									</div>
									<Badge tone={badgeTone((row.tone as Tone) || "healthy")}>
										{String(row.tone || "healthy")}
									</Badge>
								</div>
							))
						)}
					</NovaCard>
				</NovaCard>

				<NovaCard
					eyebrow="Webhook replay health"
					title="Incoming and outgoing delivery recovery"
					description="Failures route to existing webhook settings and DLQ recovery surfaces."
					action={<HealthIcon tone={data.webhookHealth.tone} />}
				>
					<div className="mt-5 grid gap-3 sm:grid-cols-4">
						<SmallStat
							label="Failed"
							value={data.webhookHealth.failedDeliveries}
						/>
						<SmallStat
							label="DLQ"
							value={data.webhookHealth.deadLetterDeliveries}
						/>
						<SmallStat
							label="Threads"
							value={data.webhookHealth.threadsDeadLetters}
						/>
						<SmallStat
							label="Instagram"
							value={data.webhookHealth.instagramDeadLetters}
						/>
					</div>
					<div className="mt-4 flex flex-wrap gap-2">
						<Button
							type="button"
							variant="outline"
							onClick={() => navigate("/settings?tab=webhooks")}
						>
							Webhook settings
							<ExternalLink data-icon="inline-end" aria-hidden="true" />
						</Button>
						<Button
							type="button"
							variant="outline"
							onClick={() => navigate("/admin/dead-letters")}
						>
							Dead letters
							<ExternalLink data-icon="inline-end" aria-hidden="true" />
						</Button>
					</div>
				</NovaCard>
			</div>

			{query.isError ? (
				<div className="rounded-md border border-oxblood/30 bg-oxblood/5 p-3 text-sm text-oxblood">
					Could not refresh the Reliability Center. The snapshot fallback is
					still visible.
				</div>
			) : null}
		</NovaScreen>
	);
}

function HealthIcon({ tone }: { tone: Tone }) {
	const className = "h-5 w-5";
	if (tone === "critical")
		return (
			<AlertTriangle className={className} style={{ color: toneColor(tone) }} />
		);
	if (tone === "warning")
		return <Clock3 className={className} style={{ color: toneColor(tone) }} />;
	return (
		<CheckCircle2 className={className} style={{ color: toneColor(tone) }} />
	);
}

function SmallStat({
	label,
	value,
}: {
	label: string;
	value: string | number;
}) {
	return <NovaStat label={label} value={value} variant="compact" />;
}

function IssueList({
	issues,
	empty,
	onRoute,
}: {
	issues: Array<Record<string, unknown>>;
	empty: string;
	onRoute: (route: string) => void;
}) {
	if (issues.length === 0) {
		return (
			<NovaEmpty
				className="mt-5 min-h-0 p-3"
				icon={<ShieldCheck data-icon aria-hidden="true" />}
				title="Clear"
				description={empty}
			/>
		);
	}
	return (
		<NovaCard
			variant="panel"
			className="mt-5 overflow-hidden"
			contentClassName="p-0"
		>
			{issues.map((issue) => (
				<ListRow
					key={String(issue.key)}
					density="compact"
					onClick={() => onRoute(String(issue.route || "/reliability"))}
				>
					<div className="flex items-center gap-3">
						<AlertTriangle
							className="h-4 w-4 shrink-0"
							style={{
								color: toneColor(
									issue.severity === "critical" ? "critical" : "warning",
								),
							}}
						/>
						<div className="min-w-0 flex-1 truncate text-sm font-medium">
							{String(issue.title || "Reliability issue")}
						</div>
						<Badge tone={issue.severity === "critical" ? "danger" : "oxblood"}>
							{String(issue.severity || "warning")}
						</Badge>
						<ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
					</div>
				</ListRow>
			))}
		</NovaCard>
	);
}
