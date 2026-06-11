import { useStoriesFunnel } from "@/hooks/useStoriesFunnel";
import { Badge } from "@/components/ui/Badge";
import { NovaCard, NovaEmpty, NovaMiniStat } from "@/components/ui/NovaPrimitives";
import { formatCompact } from "../shared";
import type { DashboardScopeProps } from "../scope";

function timeLabel(iso: string): string {
	if (!iso) return "sequence";
	return new Date(iso).toLocaleDateString("en-US", {
		month: "short",
		day: "numeric",
	});
}

function formatCountWithPct(count: number, firstFrameViews: number): string {
	const pct = firstFrameViews > 0 ? (count / firstFrameViews) * 100 : null;
	return `${formatCompact(count)} (${pct == null ? "0.0%" : `${pct.toFixed(1)}%`})`;
}

export function StoriesFunnelTile({
	scopedAccount,
	accountIds,
	groupId,
	periodDays = 14,
}: DashboardScopeProps & { periodDays?: number }) {
	const { sequences, isLoading, hasError } = useStoriesFunnel(
		periodDays,
		scopedAccount,
		accountIds,
		groupId,
	);
	const sequence = sequences[0] ?? null;
	const isExpired = sequence
		? Date.now() - new Date(sequence.startedAt).getTime() > 24 * 60 * 60 * 1000
		: false;

	const frames = sequence?.frames.slice(0, 8) ?? [];
	const firstFrameViews = frames[0]?.views ?? 0;
	const hasNoData =
		!isLoading && !hasError && (!sequence || firstFrameViews === 0);
	const hasData = !!sequence && !isExpired && frames.length >= 2 && firstFrameViews > 0;

	return (
		<NovaCard
			variant="compact"
			eyebrow={`Stories funnel · ${sequence ? timeLabel(sequence.startedAt) : `${periodDays}d`}`}
			title="Most recent story sequence"
			description="Frame-level retention, exits, and navigation behavior."
			action={<Badge tone="outline">{sequence ? `${sequence.frameCount} frames` : `${periodDays}d`}</Badge>}
			contentClassName="flex h-full flex-col"
		>
				{hasData ? (
					<>
						<div className="mt-3">
							<div className="flex items-end justify-between gap-3">
								<div>
									<div className="font-mono text-4xl font-semibold tracking-[-0.04em] text-foreground">
										{sequence.completionPct.toFixed(0)}%
									</div>
									<div
										className="text-xs text-muted-foreground"
										title="Completion · viewers who reached final frame ÷ first-frame viewers"
									>
										completion
									</div>
								</div>
								<div style={{ textAlign: "right" }}>
									<div className="font-mono text-base font-bold tabular-nums text-foreground">
										{formatCompact(sequence.totals.views)}
									</div>
									<div className="text-xs text-muted-foreground">
										views · @{sequence.username ?? "ig"}
									</div>
								</div>
							</div>
						</div>

						<div
							style={{
								marginTop: 16,
								display: "grid",
								gridTemplateColumns: `repeat(${frames.length}, minmax(0, 1fr))`,
								gap: 5,
								alignItems: "end",
								minHeight: 92,
							}}
						>
							{frames.map((frame, i) => {
								const retentionPct =
									firstFrameViews > 0
										? (frame.views / firstFrameViews) * 100
										: 0;
								const height = Math.max(
									12,
									Math.min(82, (retentionPct / 100) * 82),
								);
								const isExitPeak = sequence.exitFramePeak === i + 1;
								return (
									<div key={frame.postId} style={{ minWidth: 0 }}>
										<div
											title={`Frame ${i + 1}: ${frame.retentionPct}% retained · ${frame.exits} exits`}
											style={{
												height,
												borderRadius: "6px 6px 3px 3px",
												background: isExitPeak
													? "var(--color-oxblood)"
													: "color-mix(in srgb, var(--color-oxblood) 48%, var(--color-muted))",
												border:
													"1px solid color-mix(in srgb, var(--color-foreground) 12%, transparent)",
											}}
										/>
										<div className="mt-1.5 text-center font-mono text-[0.625rem] text-muted-foreground">
											F{i + 1}
										</div>
										<div className="mt-0.5 text-center font-mono text-[0.625rem] text-muted-foreground/80">
											{Math.round(retentionPct)}% · {formatCompact(frame.views)}
										</div>
									</div>
								);
							})}
						</div>

						<div
							style={{
								marginTop: 12,
								display: "grid",
								gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
								gap: 7,
							}}
						>
							<NovaMiniStat
								label="Taps fwd"
								value={formatCountWithPct(
									sequence.totals.tapsForward,
									firstFrameViews,
								)}
								size="compact"
							/>
							<NovaMiniStat
								label="Back"
								value={formatCountWithPct(
									sequence.totals.tapsBack,
									firstFrameViews,
								)}
								size="compact"
							/>
							<NovaMiniStat
								label="Exits"
								value={formatCountWithPct(
									sequence.totals.exits,
									firstFrameViews,
								)}
								tone="primary"
								size="compact"
							/>
						</div>

						<div
							className="mt-auto pt-2.5 text-[0.6875rem] leading-snug text-muted-foreground"
						>
							{timeLabel(sequence.startedAt)} sequence. Exit peak on frame{" "}
							{sequence.exitFramePeak ?? "none"}; bars show frame-level view
							retention.
						</div>
					</>
				) : (
					<NovaEmpty
						className="mt-2"
						title={
							isExpired
								? "Story insight window expired"
								: hasError
									? "Stories funnel unavailable"
									: isLoading
										? "Reading story navigation"
										: "No story funnel sample"
						}
						description={
							isExpired
								? "Insights only available for the first 24h after a story posts."
								: hasError
									? "Stories funnel unavailable. Refresh to retry story navigation data."
									: isLoading
										? "Reading story navigation data…"
										: hasNoData
										? `No Story sequence with first-frame views in ${periodDays}D`
										: `No 2+ frame Story sequence in the last ${periodDays} days.`
						}
					/>
				)}
		</NovaCard>
	);
}
