import type React from "react";
import type { FleetMetricsState } from "@/hooks/useFleetMetrics";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { EvidenceTile } from "../EvidenceTile";

interface Props {
	fleet: FleetMetricsState;
	scopedAccount?: ScopedAccountLite | null | undefined;
}

const METRICS = [
	{ key: "reach", label: "Reach" },
	{ key: "sends", label: "Sends" },
	{ key: "saves", label: "Saves" },
	{ key: "comments", label: "Replies" },
	{ key: "followerGrowthPct", label: "Follows" },
	{ key: "eqs", label: "EQS" },
] as const;

export function MatrixCoordinateTile({ fleet, scopedAccount }: Props) {
	const rows = (fleet.accounts ?? []).slice(0, 5);
	const isAccountScope = !!scopedAccount?.id;
	const title = isAccountScope ? "Account metric matrix" : "Metric matrix";
	const hint = isAccountScope
		? "Selected account × 6 metrics"
		: "5 accounts × 6 metrics · sub-chart cells";

	if (rows.length === 0 && !fleet.isLoading) {
		return (
			<EvidenceTile
				state="empty"
				label="Matrix"
				title={title}
				note={
					isAccountScope
						? "Publish posts in this window to populate this account's metric matrix."
						: "Connect active accounts or publish posts in this window to populate the account-by-metric matrix."
				}
				variant="table"
				statusLabel={
					fleet.hasError
						? "Metric data unavailable"
						: isAccountScope
							? "No account sample"
							: "No account sample"
				}
			/>
		);
	}

	return (
		<EvidenceCard
			eyebrow="Matrix"
			title={title}
			description={hint}
			className="h-full"
			contentClassName="flex h-full flex-col p-5 pt-0"
		>
			<div className="overflow-hidden">
				<div className="rounded-lg border border-border/70 overflow-hidden">
					<div className="grid grid-cols-[minmax(96px,1.25fr)_repeat(6,minmax(46px,1fr))] bg-muted/35 border-b border-border/70">
						<Cell muted>Account</Cell>
						{METRICS.map((metric) => (
							<Cell key={metric.key} muted align="center">
								{metric.label}
							</Cell>
						))}
					</div>
					{rows.map((row) => (
						<div
							key={row.accountId}
							className="grid grid-cols-[minmax(96px,1.25fr)_repeat(6,minmax(46px,1fr))] border-b last:border-b-0 border-border/60"
						>
							<Cell>
								<span className="font-medium text-foreground truncate">
									@{row.username ?? "account"}
								</span>
							</Cell>
							{METRICS.map((metric) => {
								const value = Number(row[metric.key] ?? 0);
								const max =
									metric.key === "eqs" ? 100 : maxFor(rows, metric.key);
								const pct = Math.max(
									4,
									Math.min(100, (Math.abs(value) / Math.max(1, max)) * 100),
								);
								const tone =
									value < 0
										? "bad"
										: metric.key === "followerGrowthPct" && value < 1
											? "warn"
											: "good";
								return (
									<Cell key={metric.key} align="center" heat={tone}>
										<div className="flex flex-col gap-1.5">
											<span className="font-mono tabular-nums text-[0.72rem] text-foreground">
												{formatMetric(metric.key, value)}
											</span>
											<div className="h-1.5 rounded-full bg-background/50 overflow-hidden">
												<div
													className="h-full rounded-full"
													style={{
														width: `${pct}%`,
														background:
															tone === "bad"
																? "var(--color-oxblood)"
																: tone === "warn"
																	? "var(--color-gold)"
																	: "var(--color-health-good)",
													}}
												/>
											</div>
										</div>
									</Cell>
								);
							})}
						</div>
					))}
				</div>
			</div>
		</EvidenceCard>
	);
}

function Cell({
	children,
	muted = false,
	align = "left",
	heat,
}: {
	children: React.ReactNode;
	muted?: boolean | undefined;
	align?: "left" | "center" | undefined;
	heat?: "good" | "warn" | "bad" | undefined;
}) {
	const heatClass =
		heat === "good"
			? "bg-[color-mix(in_srgb,var(--color-health-good)_13%,transparent)]"
			: heat === "warn"
				? "bg-[color-mix(in_srgb,var(--color-gold)_13%,transparent)]"
				: heat === "bad"
					? "bg-[color-mix(in_srgb,var(--color-oxblood)_16%,transparent)]"
					: "";
	return (
		<div
			className={[
				"min-h-[50px] px-2 py-2 flex items-center border-r last:border-r-0 border-border/60 min-w-0 overflow-hidden",
				muted ? "text-[0.6875rem] font-medium uppercase tracking-[0.08em] text-muted-foreground" : "",
				align === "center" ? "justify-center text-center" : "",
				heatClass,
			].join(" ")}
		>
			{children}
		</div>
	);
}

function maxFor(
	rows: FleetMetricsState["accounts"],
	key: (typeof METRICS)[number]["key"],
) {
	return Math.max(1, ...rows.map((row) => Math.abs(Number(row[key] ?? 0))));
}

function formatMetric(key: (typeof METRICS)[number]["key"], value: number) {
	if (key === "followerGrowthPct")
		return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
	if (key === "eqs") return value.toFixed(0);
	if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
	return Math.round(value).toLocaleString();
}
