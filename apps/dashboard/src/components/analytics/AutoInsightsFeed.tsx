/* =========================================================================
   AUTO-INSIGHTS FEED
   Ranks a set of metrics by how surprising their latest value is relative
   to the trailing window, then surfaces the top-5 as a compact feed.
   Pure render — the caller assembles metric samples from its own hooks.
   ========================================================================= */

import { ArrowDownRight, ArrowUpRight, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import {
	type MetricSample,
	type RankedInsight,
	rankBySurprise,
} from "@/lib/surprise";

type Props = {
	metrics: MetricSample[];
	/** Max rows to render. Defaults to 5. */
	limit?: number | undefined;
	/** Shown under the header — e.g. "30-day baseline". */
	windowLabel?: string | undefined;
	/** Title shown in the card header. Defaults to "Auto-insights". */
	title?: string | undefined;
	loading?: boolean | undefined;
	/** Tile variant. Pass "dark" to render this section as the deep oxblood
	 *  anchor that mirrors the rail's "what changed" anchor. Defaults to
	 *  "default" (translucent regular surface). */
	variant?: "default" | "dark" | undefined;
	action?: ReactNode | undefined;
};

export function AutoInsightsFeed({
	metrics,
	limit = 5,
	windowLabel,
	title = "Auto-insights",
	loading = false,
	variant = "default",
	action,
}: Props) {
	const ranked = rankBySurprise(metrics, limit);
	const isDark = variant === "dark";

	return (
		<NovaCard
			className="analytics-auto-insights-tile scroll-mt-16"
			contentClassName="p-5"
		>
			<div className="flex items-start justify-between gap-4 mb-4">
				<div>
					<div
						className={
							"text-[0.65625rem] font-semibold uppercase tracking-[0.12em] mb-1.5 flex items-center gap-1.5 " +
							(isDark ? "text-white/70" : "text-muted-foreground")
						}
					>
						<Sparkles
							className="w-3 h-3"
							style={{
								color: isDark
									? "color-mix(in srgb, var(--color-gold) 72%, var(--color-foreground))"
									: "var(--color-oxblood)",
							}}
						/>
						{title}
					</div>
					<div
						className={
							"text-[0.8125rem] " +
							(isDark ? "text-white/65" : "text-muted-foreground")
						}
					>
						{windowLabel ??
							"Rule-based ranking by how unexpected each value is vs its trailing baseline"}
					</div>
				</div>
				{action ? (
					<div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
						{action}
					</div>
				) : null}
			</div>

			{loading ? (
				<EmptyMessage
					title="Loading insights"
					detail="Scanning metrics for unexpected shifts."
				/>
			) : ranked.length === 0 ? (
				<EmptyMessage
					title="Nothing unusual this week"
					detail="Every tracked metric is within 1σ of its trailing baseline. Publish more or check back in a few days."
				/>
			) : (
				<ul
					className={`flex flex-col divide-y ${
						isDark ? "divide-white/10" : "divide-border/70"
					}`}
				>
					{ranked.map((insight) => (
						<InsightRow key={insight.key} insight={insight} dark={isDark} />
					))}
				</ul>
			)}
		</NovaCard>
	);
}

function InsightRow({
	insight,
	dark,
}: {
	insight: RankedInsight;
	dark: boolean;
}) {
	const { label, current, score, higherIsBetter } = insight;
	const isUp = score.direction === "up";
	const magnitudeLabel = `${score.magnitude.toFixed(1)}σ`;

	// Color: align with operator intent when higherIsBetter is set. Default is
	// direction-only (up green / down oxblood) so metrics without intent stay
	// neutral-ish.
	const sentiment: "positive" | "negative" | "neutral" = (() => {
		if (higherIsBetter === undefined) return isUp ? "positive" : "negative";
		if (isUp === higherIsBetter) return "positive";
		return "negative";
	})();

	// Dark anchor uses token-mixed colors that read against the deep oxblood
	// gradient; light mode routes directly through semantic tokens.
	const sentimentColor = dark
		? sentiment === "positive"
			? "color-mix(in srgb, var(--color-health-good) 72%, var(--color-foreground))"
			: sentiment === "negative"
				? "#F4A090"
				: "color-mix(in_srgb,var(--color-card)_85%,transparent)"
		: sentiment === "positive"
			? "var(--color-health-good)"
			: sentiment === "negative"
				? "var(--color-oxblood)"
				: "var(--color-ink)";

	const Arrow = isUp ? ArrowUpRight : ArrowDownRight;
	const deltaPct =
		score.baseline !== 0
			? ((current - score.baseline) / Math.abs(score.baseline)) * 100
			: null;

	return (
		<li className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
			<div className="min-w-0 flex-1">
				<div
					className={
						"text-[0.8125rem] font-medium truncate " +
						(dark ? "text-white" : "text-foreground")
					}
				>
					{label}
				</div>
				<div
					className={
						`text-[0.75rem] tabular-nums ${dark ? "text-white/65" : "text-muted-foreground"}`
					}
				>
					{formatNumber(current)}
					<span
						className={
							`mx-1.5 ${dark ? "text-white/40" : "text-muted-foreground"}`
						}
					>
						vs
					</span>
					{formatNumber(score.baseline)} baseline
					{deltaPct != null && (
						<>
							<span
								className={
									`mx-1.5 ${dark ? "text-white/40" : "text-muted-foreground"}`
								}
							>
								·
							</span>
							{deltaPct >= 0 ? "+" : ""}
							{deltaPct.toFixed(0)}%
						</>
					)}
				</div>
			</div>
			<div className="flex items-center gap-2 flex-shrink-0">
				<span
					className="text-[0.6875rem] font-semibold uppercase tracking-[0.08em] tabular-nums"
					style={{ color: sentimentColor }}
				>
					{magnitudeLabel}
				</span>
				<span
					className="inline-flex items-center justify-center w-7 h-7 rounded-full"
					style={{
						backgroundColor: dark
							? sentiment === "positive"
								? "color-mix(in_srgb,var(--color-health-good)_15%,transparent)"
								: sentiment === "negative"
									? "color-mix(in_srgb,var(--color-negative)_18%,transparent)"
									: "color-mix(in_srgb,var(--color-card)_8%,transparent)"
							: sentiment === "positive"
								? "color-mix(in srgb, var(--color-health-good) 14%, transparent)"
								: sentiment === "negative"
									? "color-mix(in srgb, var(--color-oxblood) 12%, transparent)"
									: "color-mix(in srgb, var(--color-foreground) 6%, transparent)",
					}}
				>
					<Arrow className="w-3.5 h-3.5" style={{ color: sentimentColor }} />
				</span>
			</div>
		</li>
	);
}

function EmptyMessage({ title, detail }: { title: string; detail: string }) {
	return (
		<NovaEmpty title={title} description={detail} />
	);
}

function formatNumber(n: number): string {
	if (!Number.isFinite(n)) return "—";
	if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	if (Math.abs(n) >= 10_000) return `${(n / 1_000).toFixed(1)}K`;
	if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(2)}K`;
	if (Math.abs(n) >= 10) return n.toFixed(0);
	return n.toFixed(1);
}
