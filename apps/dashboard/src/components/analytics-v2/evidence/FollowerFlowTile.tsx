import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { JunoDeltaBarChart } from "@/components/ui/JunoChart";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/utils";
import { useFollowerFlow } from "@/hooks/useFollowerFlow";
import {
	toFleetPlatform,
	type Platform,
	type ScopedAccountLite,
} from "@/components/analytics/analyticsShared";
interface Props {
	platform: Platform;
	days: number;
	scopedAccount?: ScopedAccountLite | undefined;
	accountIds?: string[] | undefined;
}

export function FollowerFlowTile({
	platform,
	days,
	scopedAccount,
	accountIds,
}: Props) {
	const live = useFollowerFlow(
		toFleetPlatform(platform),
		days,
		scopedAccount?.id
			? {
					accountId: scopedAccount.id,
					accountPlatform: scopedAccount.platform,
					accountHandle: scopedAccount.handle,
				}
			: null,
		scopedAccount?.id ? undefined : accountIds,
	);

	if (!live.hasRealData && !live.loading) {
		return (
			<EvidenceCard
				state="empty"
				eyebrow="Audience"
				title="Follower flow"
				description={`${live.windowLabel} · gains vs losses`}
			>
				<NovaEmpty
					className="min-h-[220px]"
					title="No follower flow yet"
					description="Follower flow needs at least two follower snapshots across the selected window before daily gains and losses can be computed."
				/>
			</EvidenceCard>
		);
	}

	if (live.loading) {
		return (
			<EvidenceCard
				state="loading"
				eyebrow="Audience"
				title="Follower flow"
				description={`${days}d · gains vs losses`}
				contentClassName="flex min-h-[280px] flex-col gap-4"
			>
				<div className="flex items-end justify-between gap-4">
					<div className="grid gap-2">
						<Skeleton className="h-10 w-24" />
						<Skeleton className="h-4 w-36" />
					</div>
					<div className="flex gap-2">
						<Skeleton className="h-9 w-20" />
						<Skeleton className="h-9 w-20" />
					</div>
				</div>
				<Skeleton className="h-[150px] w-full" />
			</EvidenceCard>
		);
	}

	const gains = live.gains;
	const losses = live.losses;
	const maxBar = Math.max(...gains, ...losses, 1);
	const bars = gains.map((gain, index) => ({
		label: `${index + 1}`,
		gain,
		loss: -Math.abs(losses[index] ?? 0),
	}));

	return (
		<EvidenceCard
			eyebrow="Audience"
			title="Follower flow"
			description={`${live.windowLabel} · gains vs losses`}
			action={
				<InvestigateButton
					accountId={scopedAccount?.id ?? null}
					metric="followers"
					metricLabel="Follower flow"
					periodDays={days}
				/>
			}
			contentClassName="flex h-full flex-col gap-5"
		>
					<div className="flex items-end justify-between gap-4">
						<div>
							<div className="text-4xl font-semibold tracking-normal tabular-nums text-foreground">
								{live.netTotal}
							</div>
							<div className="mt-1 text-[0.75rem] text-muted-foreground">
								net follower change
							</div>
						</div>
						<div className="grid grid-cols-2 gap-2 text-right">
							<Summary
								label="Inflow"
								value={live.inflowTotal}
								tone="success"
							/>
							<Summary
								label="Outflow"
								value={live.outflowTotal}
								tone="danger"
							/>
						</div>
					</div>

					<div>
						<div className="mb-2 flex items-center justify-between text-[0.6875rem] text-muted-foreground">
							<span>Daily delta</span>
							<span className="font-mono tabular-nums">
								{live.churnRate} churn
							</span>
						</div>
						<div className="h-[150px] rounded-md border border-border/70 bg-muted/25 px-2 py-3">
							<JunoDeltaBarChart
								ariaLabel="Daily follower gains and losses"
								height={126}
								data={bars}
								maxMagnitude={maxBar}
							/>
						</div>
						<div className="mt-1 flex justify-between text-[0.625rem] text-muted-foreground/75 tabular-nums">
							<span>{days}d ago</span>
							<span>Today</span>
						</div>
					</div>
		</EvidenceCard>
	);
}

function Summary({
	label,
	value,
	tone,
}: {
	label: string;
	value: string;
	tone: "success" | "danger";
}) {
	return (
		<div>
			<div className="text-[0.625rem] uppercase tracking-[0.1em] text-muted-foreground">
				{label}
			</div>
			<div
				className={cn(
					"mt-1 font-mono text-[0.8125rem] tabular-nums",
					tone === "success" ? "text-success" : "text-error",
				)}
			>
				{value}
			</div>
		</div>
	);
}
