import { useMemo } from "react";
import { Radar } from "lucide-react";
import { useCompetitorBenchmark } from "@/hooks/useCompetitorBenchmark";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { EvidenceTile } from "../EvidenceTile";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { AnalyticsActionLink } from "@/components/analytics-v2/AnalyticsActionLink";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { scopedRoute } from "@/lib/scopedRoutes";

interface Props {
	/** Optional override; defaults to the scoped account or the first connected one. */
	accountId?: string | null | undefined;
	platform?: "threads" | "instagram" | undefined;
	scopedAccount?: AccountScopeValue | null | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
}

/**
 * §11 Competitor benchmark — percentile of the user's normalized 7d engagement
 * rate against peers in the same follower-size band (±50%). Backend at
 * api/analytics?action=competitor-benchmark.
 *
 * Renders a small bullet chart: user's rate as a marker on a 0-100 axis,
 * with peer P50 / P75 / P90 reference lines. Falls back to an EmptyEvidence
 * tile if no account is in scope (single-account requirement).
 */
export function CompetitorBenchmarkPanel({
	accountId,
	platform,
	scopedAccount: scopedAccountProp,
	accountIds,
	groupId,
}: Props) {
	const storeScopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const scopedAccount =
		scopedAccountProp !== undefined ? scopedAccountProp : storeScopedAccount;
	const { accounts } = useConnectedAccounts();

	// Resolve which account to benchmark: explicit prop > scoped account > first
	// account matching the active view. All-view keeps the Threads-first default
	// because Threads has the densest competitor pool in the current fleet.
	const resolved = useMemo(() => {
		if (accountId && platform) return { id: accountId, platform };
		if (scopedAccount) {
			if (platform && scopedAccount.platform !== platform) return null;
			return {
				id: scopedAccount.id,
				platform: (scopedAccount.platform === "instagram"
					? "instagram"
					: "threads") as "threads" | "instagram",
			};
		}
		const visibleAccounts =
			accountIds && accountIds.length > 0
				? accounts.filter((a) => accountIds.includes(a.id))
				: accounts;
		if (platform === "instagram") {
			const firstIg = visibleAccounts.find((a) => a.platform === "instagram");
			return firstIg
				? { id: firstIg.id, platform: "instagram" as const }
				: null;
		}
		if (platform === "threads") {
			const firstThreads = visibleAccounts.find(
				(a) => a.platform === "threads",
			);
			return firstThreads
				? { id: firstThreads.id, platform: "threads" as const }
				: null;
		}
		const firstThreads = visibleAccounts.find((a) => a.platform === "threads");
		if (firstThreads)
			return { id: firstThreads.id, platform: "threads" as const };
		const firstIg = visibleAccounts.find((a) => a.platform === "instagram");
		if (firstIg) return { id: firstIg.id, platform: "instagram" as const };
		return null;
	}, [accountId, platform, scopedAccount, accountIds, accounts]);

	const { data, isLoading, hasError } = useCompetitorBenchmark(
		resolved?.id ?? null,
		resolved?.platform ?? "threads",
	);

	if (!resolved) {
		return (
			<EvidenceTile
				state="empty"
				label="Benchmarks"
				title="Competitor benchmark"
				note="Connect at least one account to see how your normalized engagement compares to a follower-band peer pool."
				variant="bullet"
			/>
		);
	}

	if (hasError) {
		return (
			<EvidenceTile
				state="empty"
				label="Benchmarks"
				title="Competitor benchmark"
				note="Competitor benchmarks did not return for this account. The bullet chart appears once the peer-pool endpoint returns percentile bands."
				variant="bullet"
			/>
		);
	}

	if (isLoading || !data) {
		return (
			<EvidenceTile
				state="loading"
				index={11}
				title="Competitor benchmark"
				hint={`±50% follower band · ${resolved.platform}`}
				variant="bullet"
			/>
		);
	}

	if (data.peerCount === 0 || data.percentile === null) {
		return (
			<EvidenceTile
				state="empty"
				label="Benchmarks"
				title="Competitor benchmark"
				note={`No peers in the ±50% follower band yet for ${data.userFollowers.toLocaleString()} followers on ${resolved.platform}. The pool fills in as more accounts sync at this size.`}
				variant="bullet"
			/>
		);
	}

	// Bullet chart maths: scale user rate + percentile markers to a 0-100 axis
	// using a max derived from peer P90 (or user rate, whichever is larger).
	const axisMax = Math.max(data.peerP90, data.userRate, 1) * 1.15;
	const pct = (v: number) => Math.max(0, Math.min(100, (v / axisMax) * 100));

	const userTone =
		data.percentile >= 75 ? "good" : data.percentile >= 50 ? "gold" : "crit";
	const userColor =
		userTone === "good"
			? "var(--color-health-good)"
			: userTone === "gold"
				? "var(--color-gold)"
				: "var(--color-oxblood)";

	return (
		<EvidenceCard
			title="Competitor benchmark"
			description={`${data.peerCount} peers · ${resolved.platform} · ±50% follower band · 7d engagement rate`}
			action={
				<>
					<AnalyticsActionLink
						to={scopedRoute(
							"/listening",
							{ scopedAccount, accountIds, groupId, platform: resolved.platform },
							{ q: resolved.id },
						)}
						label="Open listening"
						icon={Radar}
						tone={data.percentile < 50 ? "primary" : "neutral"}
					/>
					<InvestigateButton
						accountId={resolved.id}
						metric="engagement"
						metricLabel="Peer percentile"
					/>
				</>
			}
			contentClassName="flex h-full flex-col gap-4"
		>
				{/* Headline reading. */}
				<div className="flex items-baseline gap-3">
					<span
						className="text-[2rem] font-semibold tabular-nums leading-none"
						style={{ color: userColor }}
					>
						{Math.round(data.percentile)}
						<span className="text-[1.125rem] text-muted-foreground">th</span>
					</span>
					<span className="text-[0.8125rem] text-muted-foreground">
						percentile · {data.userRate.toFixed(2)} interactions / 1k followers
					</span>
				</div>

				{/* Bullet chart. */}
				<div className="relative h-9">
					{/* Axis. */}
					<div className="absolute inset-x-0 top-1/2 h-1 rounded-full bg-border" />
					{/* P50 / P75 / P90 reference ticks. */}
					{[
						{ label: "P50", val: data.peerP50 },
						{ label: "P75", val: data.peerP75 },
						{ label: "P90", val: data.peerP90 },
					].map((tick) => (
						<div
							key={tick.label}
							role="img"
							className="absolute top-0 bottom-0 flex flex-col items-center"
							style={{
								left: `${pct(tick.val)}%`,
								transform: "translateX(-50%)",
							}}
							aria-label={`${tick.label} ${tick.val.toFixed(2)}`}
						>
							<span className="font-mono text-[0.5625rem] text-muted-foreground">
								{tick.label}
							</span>
							<div
								className="w-px flex-1 bg-muted-foreground/30"
								aria-hidden="true"
							/>
						</div>
					))}
					{/* User marker. */}
					<div
						role="img"
						className="absolute top-1/2 size-3 -translate-y-1/2 rounded-full ring-2 ring-background"
						style={{
							left: `${pct(data.userRate)}%`,
							transform: "translate(-50%, -50%)",
							backgroundColor: userColor,
						}}
						aria-label="Your rate"
					/>
				</div>

				<dl className="grid grid-cols-3 gap-3 text-[0.6875rem]">
					<Stat label="Peer P50" value={data.peerP50} />
					<Stat label="Peer P75" value={data.peerP75} />
					<Stat label="Peer P90" value={data.peerP90} />
				</dl>
		</EvidenceCard>
	);
}

function Stat({ label, value }: { label: string; value: number }) {
	return (
		<div className="flex min-w-0 flex-col gap-0.5">
			<dt className="text-muted-foreground uppercase tracking-[0.04em]">
				{label}
			</dt>
			<dd className="font-mono tabular-nums text-foreground">
				{value.toFixed(2)}
			</dd>
		</div>
	);
}
