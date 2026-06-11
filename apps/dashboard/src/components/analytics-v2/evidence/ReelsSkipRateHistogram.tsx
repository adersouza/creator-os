import { useMemo } from "react";
import { useSkipRateAlerts } from "@/hooks/useSkipRateAlerts";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatCompact } from "../shared";

interface Props {
	/** Window in days. */
	days?: number | undefined;
	scopedAccount?: ScopedAccountLite | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
	/** Skip-rate threshold (0–1). Defaults to 0.5 (50%). */
	threshold?: number | undefined;
}

/**
 * §9 Reels skip-rate histogram. Backend at api/analytics?action=skip-rate-alerts
 * returns Reels above the skip threshold. We render them as a horizontal
 * histogram (skip rate × magnitude) with the post content + view count for
 * each, plus a band at the threshold so the triage zone is obvious.
 */
export function ReelsSkipRateHistogram({
	days = 30,
	scopedAccount: scopedAccountProp,
	accountIds,
	groupId,
	threshold = 0.5,
}: Props) {
	const storeScopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const scopedAccount = scopedAccountProp ?? storeScopedAccount;
	const accountId =
		scopedAccount?.platform === "instagram" ? (scopedAccount.id ?? null) : null;
	const { alerts, isLoading, hasError } = useSkipRateAlerts(
		days,
		threshold,
		accountId,
		accountId ? undefined : accountIds,
		accountId ? null : groupId,
	);

	const ranked = useMemo(
		() => [...alerts].sort((a, b) => b.skipRate - a.skipRate).slice(0, 8),
		[alerts],
	);

	if (isLoading) {
		return (
			<EvidenceCard
				state="loading"
				title="Reels skip-rate distribution"
				description={`Above ${(threshold * 100).toFixed(0)}% · last ${days}d`}
			>
				<div className="flex flex-col gap-3" role="status" aria-label="Loading Reels skip-rate distribution">
					<Skeleton className="h-9 w-full rounded-lg" />
					<Skeleton className="h-9 w-full rounded-lg" />
					<Skeleton className="h-9 w-5/6 rounded-lg" />
				</div>
			</EvidenceCard>
		);
	}

	if (hasError) {
		return (
			<EvidenceCard
				state="empty"
				eyebrow="Reels"
				title="Reels skip-rate distribution"
			>
				<NovaEmpty
					title="Skip-rate alerts unavailable"
					description="Reels skip-rate alerts did not return for this scope. The histogram appears once nightly IG capture provides skip-rate rows."
				/>
			</EvidenceCard>
		);
	}

	if (ranked.length === 0) {
		return (
			<EvidenceCard
				state="empty"
				eyebrow="Reels"
				title="Reels skip-rate distribution"
				description="No skip-rate alerts"
			>
				<NovaEmpty
					title="No high skip-rate Reels"
					description={`No Reels exceeded the ${(threshold * 100).toFixed(0)}% skip threshold in the last ${days} days. ig_skip_rate is captured nightly.`}
				/>
			</EvidenceCard>
		);
	}

	return (
		<EvidenceCard
			title="Reels skip-rate distribution"
			description={`${ranked.length} Reel${ranked.length === 1 ? "" : "s"} above ${(threshold * 100).toFixed(0)}% · last ${days}d`}
			action={
				<InvestigateButton
					accountId={accountId}
					metric="reach"
					metricLabel="Skip-rate suppression"
					periodDays={days}
				/>
			}
			footer={
				<p className="text-xs leading-relaxed text-muted-foreground">
					SOURCE · ig_skip_rate per Reel, captured nightly. Above{" "}
					{(threshold * 100).toFixed(0)}% = Meta is recommending the Reel to
					viewers but they are tapping past it within the first 3 seconds.
				</p>
			}
		>
			<div className="flex flex-col gap-2.5">
				{ranked.map((alert) => {
					const pct = Math.min(
						100,
						Math.max(threshold * 100, alert.skipRate * 100),
					);
					const tone =
						alert.skipRate >= 0.75
							? "var(--color-oxblood)"
							: alert.skipRate >= 0.6
								? "var(--color-gold)"
								: "var(--color-foreground)";
					return (
						<div key={alert.id} className="flex flex-col gap-1">
							<div className="flex items-center justify-between gap-3 text-sm">
								<span className="min-w-0 flex-1 line-clamp-1 text-foreground">
									{alert.content || "(no caption)"}
								</span>
								<span
									className="shrink-0 font-mono tabular-nums"
									style={{ color: tone }}
								>
									{(alert.skipRate * 100).toFixed(1)}%
								</span>
							</div>
							<div className="h-1.5 overflow-hidden rounded-full bg-border">
								<div
									role="img"
									className="h-full rounded-full"
									style={{
										width: `${pct}%`,
										background: tone,
									}}
									aria-label={`${(alert.skipRate * 100).toFixed(1)}% skip rate`}
								/>
							</div>
							<div className="flex items-center justify-between gap-2 text-xs text-muted-foreground tabular-nums">
								<span className="min-w-0 truncate">
									{formatCompact(alert.views)} views ·{" "}
									{formatCompact(alert.reach)} reach
								</span>
								<span className="shrink-0">
									{new Date(alert.publishedAt).toLocaleDateString()}
								</span>
							</div>
						</div>
					);
				})}
			</div>
		</EvidenceCard>
	);
}
