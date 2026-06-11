// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo } from "react";
import {
	useFleetMetrics,
	type FleetMetricsState,
} from "@/hooks/useFleetMetrics";
import { useFleetKpiData } from "@/hooks/useFleetKpiData";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import {
	daysToFleetTimeframe,
	toFleetPlatform,
} from "@/components/analytics/analyticsShared";
import { AutoInsightsFeed } from "@/components/analytics/AutoInsightsFeed";
import { AnalyticsActionLink } from "@/components/analytics-v2/AnalyticsActionLink";
import { Lightbulb } from "lucide-react";
import type { MetricSample } from "@/lib/surprise";
import { scopedRoute } from "@/lib/scopedRoutes";
import type { Platform } from "./shared";

interface Props {
	platform: Platform;
	days: number;
	/** Pre-fetched fleet metrics from the parent. */
	fleet?: FleetMetricsState | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
	scopeLabel?: string | undefined;
	scopeSubject?: string | undefined;
}

/**
 * §6 / §8 auto-insights — statistical-surprise ranking of fleet metric samples.
 * Wraps the existing AutoInsightsFeed primitive (which already implements
 * `rankBySurprise`), feeding it a metric set assembled from useFleetMetrics
 * (per-day reach + EQS series) and useFleetKpiData (current vs prior totals).
 *
 * The samples here are intentionally compact — we send daily reach + EQS
 * histories from the live fleet, then add point-in-time samples for save
 * rate, send rate, profile views, and website clicks so unusual movements
 * across either time-series or aggregate KPIs surface to the top of the feed.
 */
export function AutoInsightsSection({
	platform,
	days,
	fleet: fleetProp,
	accountIds,
	groupId,
	scopeLabel,
	scopeSubject,
}: Props) {
	const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const isAccountScope = !!scopedAccount?.id;
	const scopeWord = isAccountScope
		? "account"
		: accountIds && accountIds.length > 0
			? "group"
			: "all accounts";
	const metricScopeLabel =
		scopeSubject && scopeSubject !== "all accounts" ? scopeSubject : scopeWord;
	const fleetTimeframe = useMemo(() => daysToFleetTimeframe(days), [days]);
	const fleetPlatform = useMemo(() => toFleetPlatform(platform), [platform]);
	const viewKey = `${platform}:${scopedAccount?.id ?? groupId ?? accountIds?.join(",") ?? "fleet"}:${days}`;
	const ideaRoute = scopedRoute(
		"/ideas",
		{
			scopedAccount,
			accountIds,
			groupId,
			platform: platform === "all" ? null : platform,
			timeframe: `${days}d`,
		},
		{ source: "rough" },
	);
	const fallbackFleet = useFleetMetrics(
		fleetTimeframe,
		fleetPlatform,
		scopedAccount,
		{ enabled: !fleetProp, accountIds, groupId },
	);
	const fleet = fleetProp ?? fallbackFleet;
	const kpi = useFleetKpiData(
		{ days },
		fleetPlatform,
		scopedAccount,
		accountIds,
		groupId,
	);

	const samples = useMemo<MetricSample[]>(() => {
		const out: MetricSample[] = [];
		const series = fleet.series ?? [];
		const reach = series.map((p) => p.reach).filter((n) => Number.isFinite(n));
		if (reach.length >= 6) {
			out.push({
				key: `${metricScopeLabel}-reach-daily`,
				label:
					platform === "threads"
						? `Daily ${metricScopeLabel} views`
						: `Daily ${metricScopeLabel} reach`,
				history: reach.slice(0, -1),
				current: reach[reach.length - 1]!,
				higherIsBetter: true,
			});
		}
		const eqs = series.map((p) => p.eqs).filter((n) => Number.isFinite(n));
		if (eqs.length >= 6) {
			out.push({
				key: `${metricScopeLabel}-eqs-daily`,
				label: `Daily ${metricScopeLabel} EQS`,
				history: eqs.slice(0, -1),
				current: eqs[eqs.length - 1]!,
				higherIsBetter: true,
			});
		}
		// Point-in-time KPI samples — feed prior-window scalar as a 1-element
		// history so the surprise ranker still has something to compare against.
		// Skip when the prior side is unknown (delta=null) to avoid synthetic flags.
		const ratioSample = (
			key: string,
			label: string,
			current: number | null,
			delta: number | null,
			higherIsBetter: boolean,
		) => {
			if (current == null || !Number.isFinite(current) || delta == null) return;
			// Reverse-engineer prior value from the percentage-point delta.
			const prior = current - delta;
			out.push({
				key,
				label,
				history: [prior],
				current,
				higherIsBetter,
			});
		};
		ratioSample(
			"save-rate",
			"Save rate",
			kpi.saveRate,
			kpi.saveRateDelta,
			true,
		);
		ratioSample(
			"send-rate",
			"Send rate",
			kpi.sendRate,
			kpi.sendRateDelta,
			true,
		);
		ratioSample(
			"engagement-rate",
			"Engagement rate",
			kpi.engagementRate,
			kpi.engagementRateDelta,
			true,
		);
		ratioSample(
			"non-follower-reach",
			"Non-follower reach %",
			kpi.igNonFollowerReachPct,
			kpi.igNonFollowerReachPctDelta,
			true,
		);
		return out;
	}, [fleet.series, kpi, platform, metricScopeLabel]);

	if (samples.length === 0 && fleet.isLoading) {
		return null;
	}

	return (
		<AutoInsightsFeed
			key={viewKey}
			metrics={samples}
			limit={5}
			title={
				isAccountScope
					? "Account auto-insights"
					: scopeLabel
						? `${scopeLabel} auto-insights`
						: "Auto-insights"
			}
			windowLabel={`Ranked by statistical surprise · last ${days}d`}
			loading={fleet.isLoading && samples.length === 0}
			action={
				samples.length > 0 ? (
					<AnalyticsActionLink
						to={ideaRoute}
						label="Create idea"
						icon={Lightbulb}
						tone="primary"
					/>
				) : null
			}
		/>
	);
}
