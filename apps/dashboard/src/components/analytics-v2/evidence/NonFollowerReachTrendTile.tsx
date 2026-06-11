import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { useNonFollowerReach } from "@/hooks/useNonFollowerReach";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty, NovaMiniStat } from "@/components/ui/NovaPrimitives";

interface Props {
	days: number;
	scopedAccount?: ScopedAccountLite | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
}

/**
 * §2 / §13 Non-follower reach diagnostic. The live hook exposes the current
 * follower vs. non-follower split; this tile adds the Analytics-specific
 * threshold bands called out in the deep-dive so the value is immediately
 * interpretable instead of a loose percentage.
 */
export function NonFollowerReachTrendTile({
	days,
	scopedAccount,
	accountIds,
	groupId,
}: Props) {
	const live = useNonFollowerReach(
		{ days },
		scopedAccount?.id
			? {
					accountId: scopedAccount.id,
					accountPlatform: scopedAccount.platform,
					accountHandle: scopedAccount.handle,
				}
			: null,
		scopedAccount?.id ? undefined : accountIds,
		scopedAccount?.id ? null : groupId,
	);

	if (!live || (!live.hasRealData && !live.loading)) {
		return (
			<EvidenceCard
				state="empty"
				title="Non-follower reach"
				description="Discovery"
			>
				<NovaEmpty
					title="Non-follower reach unavailable"
					description="Non-follower reach is only available after Meta returns daily IG reach-breakdown rows for this account. Small accounts often stay gated until the audience clears Meta's insight threshold."
				/>
			</EvidenceCard>
		);
	}

	const pct = clamp(
		Number.isFinite(live.nonFollowerPct) ? live.nonFollowerPct : 0,
		0,
		100,
	);
	const status =
		pct < 10
			? {
					label: "Alarm",
					color: "var(--color-critical)",
					note: "Distribution is mostly existing audience. Check format mix and recent reach anomalies.",
				}
			: pct <= 60
				? {
						label: "Healthy",
						color: "var(--color-health-good)",
						note: "Non-follower discovery is in the expected working range for IG diagnostics.",
					}
				: {
						label: "Discovery-heavy",
						color: "var(--color-warning)",
						note: "Reach is expanding beyond the follower base. Watch saves and follows for quality.",
					};

	return (
		<EvidenceCard
			title="Non-follower reach"
			description={`Last ${days}d · healthy band 30-60%`}
			action={
				<InvestigateButton
					accountId={scopedAccount?.id ?? null}
					metric="reach"
					metricLabel="Non-follower reach"
					periodDays={days}
				/>
			}
		>
			<div className="flex flex-col gap-5">
				<div className="flex items-end justify-between gap-4">
					<div>
						<div className="text-4xl font-semibold tabular-nums">
							{pct.toFixed(1)}%
						</div>
						<div className="mt-1 text-sm text-muted-foreground">
							reach from Explore / For You
						</div>
					</div>
					<div className="text-right">
						<div className="text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">
							Status
						</div>
						<div
							className="mt-1 text-[0.875rem] font-semibold"
							style={{ color: status.color }}
						>
							{status.label}
						</div>
					</div>
				</div>

				<div className="flex flex-col gap-2">
					<div className="relative h-9 overflow-hidden rounded-md bg-muted/60">
						<Band left={0} width={10} color="var(--color-critical)" />
						<Band left={10} width={20} color="var(--color-warning)" />
						<Band left={30} width={30} color="var(--color-health-good)" />
						<Band left={60} width={40} color="var(--color-warning)" />
						<div
							className="absolute bottom-0 top-0 w-[2px] rounded-full"
							style={{
								left: `${pct}%`,
								background: "var(--color-foreground)",
								boxShadow:
									"0 0 0 3px color-mix(in srgb, var(--color-foreground) 14%, transparent)",
							}}
						/>
					</div>
					<div className="grid grid-cols-4 text-[0.625rem] text-muted-foreground tabular-nums">
						<span>&lt;10 alarm</span>
						<span>10-30 watch</span>
						<span>30-60 healthy</span>
						<span className="text-right">60+ volatile</span>
					</div>
				</div>

				<div className="grid grid-cols-2 gap-3">
					<NovaMiniStat label="Follower" value={`${live.followerPct}%`} />
					<NovaMiniStat label="Prior delta" value={live.delta ?? "No prior"} />
				</div>

				<p className="text-sm leading-relaxed text-muted-foreground">
					{status.note}
				</p>
			</div>
		</EvidenceCard>
	);
}

function Band({
	left,
	width,
	color,
}: {
	left: number;
	width: number;
	color: string;
}) {
	return (
		<div
			className="absolute top-0 bottom-0"
			style={{
				left: `${left}%`,
				width: `${width}%`,
				background: `color-mix(in srgb, ${color} 18%, transparent)`,
			}}
		/>
	);
}

function clamp(value: number, min: number, max: number) {
	return Math.max(min, Math.min(max, value));
}
