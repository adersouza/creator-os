import { useMemo } from "react";
import { useTopicTagLift } from "@/hooks/useTopicTagLift";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatCompact } from "../shared";

interface Props {
	/** Recent window in days. */
	periodDays?: number | undefined;
	/** Baseline window for comparison. */
	baselineDays?: number | undefined;
	platform?: "all" | "instagram" | "threads" | undefined;
	scopedAccount?: AccountScopeValue | null | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
}

/**
 * §10 Topic reach lift (Threads). Backed by api/analytics?action=topic-tag-lift,
 * which compares avg reach per topic in a recent window vs a longer baseline.
 *
 * Renders horizontal bars for each topic, sorted by lift desc. Positive lift
 * = the topic is performing above its own historical baseline; negative =
 * algorithmic friction. Useful for the new Meta "Your Algorithm" topic
 * controls where users tune which topics they see.
 */
export function TopicTagLiftCurves({
	periodDays = 30,
	baselineDays = 90,
	platform = "threads",
	scopedAccount: scopedAccountProp,
	accountIds,
	groupId,
}: Props) {
	const storeScopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const scopedAccount =
		scopedAccountProp !== undefined ? scopedAccountProp : storeScopedAccount;
	const incompatibleScope =
		!!scopedAccount &&
		platform !== "all" &&
		scopedAccount.platform !== platform;
	const accountId =
		scopedAccount && !incompatibleScope ? scopedAccount.id : null;

	const { topics, isLoading, hasError } = useTopicTagLift(
		periodDays,
		baselineDays,
		incompatibleScope ? null : scopedAccount,
		platform,
		accountIds,
		groupId,
	);

	const ranked = useMemo(
		() =>
			[...topics]
				.sort((a, b) => (b.lift ?? -Infinity) - (a.lift ?? -Infinity))
				.slice(0, 8),
		[topics],
	);

	if (incompatibleScope) {
		return (
			<EvidenceCard
				state="empty"
				eyebrow="Topics"
				title="Topic lift"
			>
				<NovaEmpty
					title="Account outside topic view"
					description={`The selected ${scopedAccount.platform} account is outside this ${platform} topic view.`}
				/>
			</EvidenceCard>
		);
	}

	if (isLoading && topics.length === 0) {
		return (
			<EvidenceCard
				state="loading"
				title="Topic lift"
				description={`Last ${periodDays}d vs. ${baselineDays}d baseline`}
			>
				<div className="flex flex-col gap-3" role="status" aria-label="Loading topic lift">
					<Skeleton className="h-9 w-full rounded-lg" />
					<Skeleton className="h-9 w-full rounded-lg" />
					<Skeleton className="h-9 w-4/5 rounded-lg" />
				</div>
			</EvidenceCard>
		);
	}

	if (hasError && topics.length === 0) {
		return (
			<EvidenceCard
				state="empty"
				eyebrow="Topics"
				title="Topic lift"
			>
				<NovaEmpty
					title="Topic lift unavailable"
					description="Topic lift could not be computed from the current topic-tag payload. The next refresh will reuse cached data if available and retry the comparison."
				/>
			</EvidenceCard>
		);
	}

	if (ranked.length === 0) {
		return (
			<EvidenceCard
				state="empty"
				eyebrow="Topics"
				title="Topic lift"
			>
				<NovaEmpty
					title="No topic baseline yet"
					description={`No ${
						platform === "instagram"
							? "Instagram"
							: platform === "threads"
								? "Threads"
								: "fleet"
					} topics have enough tagged posts with reach in the selected ${periodDays}-day window. Use a wider range or keep publishing tagged posts; lift appears once each topic has a real baseline.`}
				/>
			</EvidenceCard>
		);
	}

	// Symmetric scale around 0 so positive + negative lifts read at the same
	// visual scale (otherwise an extreme positive squashes the negatives).
	const maxAbs = Math.max(
		...ranked.map((t) => (t.lift != null ? Math.abs(t.lift) : 0)),
		0.5,
	);

	return (
		<EvidenceCard
			title="Topic lift"
			description={`Last ${periodDays}d vs. ${baselineDays}d baseline · ranked by lift`}
			action={
				<InvestigateButton
					accountId={accountId}
					metric="reach"
					metricLabel="Topic reach"
					periodDays={periodDays}
				/>
			}
		>
			<div className="flex flex-col gap-2.5">
				{ranked.map((topic) => {
					const lift = topic.lift ?? 0;
					const pct = Math.min(100, (Math.abs(lift) / maxAbs) * 50);
					const tone =
						lift >= 0.2
							? "var(--color-health-good)"
							: lift <= -0.2
								? "var(--color-oxblood)"
								: "var(--color-gold)";
					return (
						<div key={topic.topic} className="flex flex-col gap-1">
							<div className="flex items-center justify-between gap-3 text-sm">
								<span className="min-w-0 flex-1 truncate text-foreground capitalize">
									{topic.topic}
								</span>
								<span className="flex shrink-0 items-center gap-2 font-mono text-xs tabular-nums">
									<span className="text-muted-foreground">
										{formatCompact(topic.windowAvgReach)} avg
									</span>
									<span style={{ color: tone }}>
										{topic.lift == null
											? "—"
											: `${lift >= 0 ? "+" : ""}${(lift * 100).toFixed(0)}%`}
									</span>
								</span>
							</div>
							{/* Diverging bar centered at the midline. */}
							<div className="relative h-1.5 overflow-hidden rounded-full bg-border">
								<div
									className="absolute top-0 bottom-0"
									style={
										lift >= 0
											? { left: "50%", width: `${pct}%`, background: tone }
											: { right: "50%", width: `${pct}%`, background: tone }
									}
								/>
								<div
									className="absolute bottom-0 top-0 w-px bg-muted-foreground/40"
									style={{ left: "50%" }}
									aria-hidden="true"
								/>
							</div>
							<span className="text-xs text-muted-foreground tabular-nums">
								{topic.windowPosts} post{topic.windowPosts === 1 ? "" : "s"} ·
								baseline {formatCompact(topic.baselineAvgReach)} avg
							</span>
						</div>
					);
				})}
			</div>
		</EvidenceCard>
	);
}
