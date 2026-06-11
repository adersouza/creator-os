// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo } from "react";
import { useContentTypeTrend } from "@/hooks/useContentTypeTrend";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { JunoComparisonBarChart } from "@/components/ui/JunoChart";
import { cn } from "@/lib/utils";
import { EvidenceTile } from "../EvidenceTile";
import { formatCompact } from "../shared";

interface Props {
	/** Choose the metric to focus on. Defaults to `reach`. */
	metric?: "reach" | "views" | "likes" | "comments" | "saves" | undefined;
	scopedAccount?: AccountScopeValue | null | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
}

/**
 * §8 Format-mix WoW trend (IG). Backend at api/analytics?action=content-type-trend
 * computes 7d-vs-prior-7d deltas per format from `ig_content_type_breakdown`
 * (Reels / Carousels / Feed / Stories). Renders one row per format with
 * current value + WoW % change.
 */
export function FormatMixWowTrend({
	metric = "reach",
	scopedAccount: scopedAccountProp,
	accountIds: accountIdsProp,
	groupId,
}: Props) {
	const storeScopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const scopedAccount =
		scopedAccountProp !== undefined ? scopedAccountProp : storeScopedAccount;
	const { accounts } = useConnectedAccounts();

	const accountIds = useMemo<string[] | undefined>(() => {
		if (scopedAccount) {
			return scopedAccount.platform === "instagram" ? [scopedAccount.id] : [];
		}
		if (groupId) return undefined;
		if (!accountIdsProp || accountIdsProp.length === 0) return undefined;
		const source = accounts.filter((a) => accountIdsProp.includes(a.id));
		return source.filter((a) => a.platform === "instagram").map((a) => a.id);
	}, [scopedAccount, groupId, accountIdsProp, accounts]);

	const hasUnsupportedScopedPlatform = accountIds?.length === 0;
	const { data, isLoading, hasError } = useContentTypeTrend(
		accountIds,
		null,
		groupId,
		!hasUnsupportedScopedPlatform,
	);

	const formats = useMemo(() => {
		if (!data) return [];
		const all = new Set([
			...Object.keys(data.current),
			...Object.keys(data.previous),
		]);
		return [...all]
			.map((fmt) => {
				const current = data.current[fmt]?.[metric] ?? 0;
				const previous = data.previous[fmt]?.[metric] ?? 0;
				const pct = data.deltas[fmt]?.[metric]?.pctChange ?? null;
				return { format: fmt, current, previous, pctChange: pct };
			})
			.filter((row) => row.current > 0 || row.previous > 0)
			.sort((a, b) => b.current - a.current);
	}, [data, metric]);

	if (hasUnsupportedScopedPlatform) {
		return (
			<EvidenceTile
				state="empty"
				label="Format mix"
				title="Format mix · WoW"
				note="Connect at least one Instagram account to see how Reels / Carousels / Feed posts are trending week-over-week."
				variant="bars"
			/>
		);
	}

	if (hasError) {
		return (
			<EvidenceTile
				state="empty"
				label="Format mix"
				title="Format mix · WoW"
				note="The format-mix comparison did not return a usable payload. The bars appear once current and prior IG content-type rows can be compared."
				variant="bars"
			/>
		);
	}

	if (isLoading || !data) {
		return (
			<EvidenceTile
				state="loading"
				index={8}
				title="Format mix · WoW"
				hint="Last 7d vs. prior 7d"
			/>
		);
	}

	if (formats.length === 0) {
		return (
			<EvidenceTile
				state="empty"
				label="Format mix"
				title="Format mix · WoW"
				note="No content-type breakdown rows in the comparison window. Reels, Carousels, Feed, and Stories appear here once IG format capture has enough samples."
				variant="bars"
			/>
		);
	}

	const chartRows = formats.slice(0, 6).map((row) => ({
		...row,
		label: row.format.charAt(0).toUpperCase() + row.format.slice(1),
	}));

	return (
		<EvidenceCard
			title="Format mix · WoW"
			description={`${metric.charAt(0).toUpperCase() + metric.slice(1)} · last 7d vs. prior 7d`}
			action={
				<InvestigateButton
					accountId={
						scopedAccount?.platform === "instagram" ? scopedAccount.id : null
					}
					metric={
						metric === "views"
							? "views"
							: metric === "reach"
								? "reach"
								: "engagement"
					}
					metricLabel="Format mix"
					periodDays={14}
				/>
			}
			contentClassName="flex h-full flex-col gap-3"
		>
				<JunoComparisonBarChart
					ariaLabel="Format mix week-over-week comparison"
					data={chartRows}
					valueFormatter={formatCompact}
				/>
				<div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
					{chartRows.map((row) => (
						<FormatDelta key={row.format} row={row} />
					))}
				</div>
		</EvidenceCard>
	);
}

function FormatDelta({
	row,
}: {
	row: {
		format: string;
		current: number;
		previous: number;
		pctChange: number | null;
	};
}) {
	const showPctChange = row.pctChange != null && row.previous >= 10;
	const toneClass = !showPctChange
		? "text-muted-foreground"
		: row.pctChange! >= 5
			? "text-success"
			: row.pctChange! <= -5
				? "text-primary"
				: "text-warning";

	return (
		<div className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/35 px-2.5 py-1.5 text-[0.6875rem]">
			<span className="min-w-0 truncate text-muted-foreground capitalize">
				{row.format}
			</span>
			<span className={cn("shrink-0 font-mono tabular-nums", toneClass)}>
				{showPctChange
					? `${row.pctChange! >= 0 ? "+" : ""}${row.pctChange!.toFixed(1)}%`
					: row.previous > 0
						? "new baseline"
						: formatCompact(row.current)}
			</span>
		</div>
	);
}
