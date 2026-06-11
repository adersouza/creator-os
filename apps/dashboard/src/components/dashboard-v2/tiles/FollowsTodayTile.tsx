import { useMemo } from "react";
import { Badge } from "@/components/ui/Badge";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { useFollowerAttribution } from "@/hooks/useFollowerAttribution";
import { cn } from "@/lib/utils";
import type { DashboardScopeProps } from "../scope";

/**
 * Follows today — All view band 2 right.
 * Keeps the bespoke sparkline math, but moves the card shell to Juno/shadcn
 * widget composition.
 */
export function FollowsTodayTile({
	scopedAccount,
	accountIds,
	groupId,
}: DashboardScopeProps) {
	const { days, isLoading, hasError } = useFollowerAttribution(
		7,
		null,
		scopedAccount,
		accountIds,
		groupId,
	);

	const { totalFollows, avg14d, sparkBars, latestDate } = useMemo(() => {
		if (!days.length)
			return {
				totalFollows: 0,
				avg14d: 0,
				sparkBars: [] as number[],
				latestDate: null as string | null,
			};
		const latest = days[days.length - 1];
		const followCount = latest?.followerGrowth ?? 0;
		const padded = Array(Math.max(0, 14 - days.length))
			.fill(0)
			.concat(days.map((d) => d.followerGrowth));
		const last14 = padded.slice(-14);
		const avg =
			last14.length > 0 ? last14.reduce((s, v) => s + v, 0) / last14.length : 0;

		return {
			totalFollows: followCount,
			avg14d: avg,
			sparkBars: last14,
			latestDate: latest?.date ?? null,
		};
	}, [days]);

	const hasData = totalFollows !== 0 || sparkBars.some((v) => v !== 0);
	const maxMagnitude = Math.max(1, ...sparkBars.map((v) => Math.abs(v)));
	const latestDateLabel = latestDate
		? new Date(latestDate).toLocaleDateString("en-US", {
				month: "short",
				day: "numeric",
			})
		: isLoading
			? "Syncing"
			: "No snapshot";
	const displayValue =
		hasError && !hasData
			? "Retry"
			: hasData
				? totalFollows >= 0
					? `+${totalFollows.toLocaleString()}`
					: totalFollows.toLocaleString()
				: "+0";

	return (
		<NovaCard
			className="h-full"
			contentClassName="flex h-full min-h-[190px] flex-col p-4"
			eyebrow="Follows today"
			action={<Badge tone="outline">Most recent · {latestDateLabel}</Badge>}
		>
			<div className="mt-2 flex items-baseline gap-2">
				<div
					className={cn(
						"text-3xl font-semibold tracking-normal",
						hasData
							? totalFollows >= 0
								? "text-foreground"
								: "text-error"
							: "text-muted-foreground",
					)}
				>
					{displayValue}
				</div>
				<span className="text-xs text-muted-foreground">
					follows
				</span>
			</div>

			{hasData ? (
				<div className="mt-1 text-xs text-muted-foreground">
					Avg{" "}
					<strong className="font-semibold text-foreground">
						{avg14d >= 0 ? "+" : ""}
						{avg14d.toFixed(0)}/day
					</strong>{" "}
					14d.
				</div>
			) : (
				<Badge tone={hasError ? "secondary" : "outline"} className="mt-1">
					{hasError ? "Follower deltas unavailable" : "No follow change today"}
				</Badge>
			)}

			<div
				className="relative mt-auto flex h-[50px] items-stretch gap-[3px] pt-3"
			>
				<span
					aria-hidden="true"
					className="absolute inset-x-0 top-1/2 border-t border-border"
				/>
				{sparkBars.length > 0 && hasData
					? sparkBars.map((v, i) => {
							const isPeak = Math.abs(v) === maxMagnitude && v > 0;
							const isToday = i === sparkBars.length - 1;
							const heightPct = Math.max(8, (Math.abs(v) / maxMagnitude) * 46);
							return (
								<div
									key={i}
									className="relative flex-1"
									title={`${i === sparkBars.length - 1 ? "Today" : `${sparkBars.length - 1 - i}d ago`}: ${v >= 0 ? "+" : ""}${v}`}
								>
									<div
										className={cn(
											"absolute inset-x-0",
											v < 0 ? "rounded-b-sm" : "rounded-t-sm",
											v < 0
												? "bg-error/60"
												: isToday
													? "bg-primary"
													: isPeak
														? "bg-primary/70"
														: "bg-primary/35",
										)}
										style={{
											...(v < 0
												? { top: "50%", height: `${heightPct}%` }
												: { bottom: "50%", height: `${heightPct}%` }),
										}}
									/>
								</div>
							);
						})
					: Array.from({ length: 14 }).map((_, i) => (
							<div
								key={i}
								className="flex-1 rounded-t-sm border border-dashed border-border bg-muted opacity-45"
								style={{
									height: `${15 + (i % 4) * 10}%`,
								}}
							/>
						))}
			</div>
			<div className="mt-1 flex justify-between font-mono text-[9px] font-medium text-muted-foreground">
				<span>14d ago</span>
				<span>today</span>
			</div>
			{!hasData && !isLoading && (
				<div className="mt-2 text-[10.5px] leading-snug text-muted-foreground">
					{hasError
						? "Daily follower growth appears after account analytics sync."
						: "Daily follower delta. Spark fills in once accounts publish."}
				</div>
			)}
		</NovaCard>
	);
}
