import { Wrench } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard, NovaEmpty, NovaInset } from "@/components/ui/NovaPrimitives";
import { useFleetAccounts } from "@/hooks/useFleetAccounts";
import { scopedRoute } from "@/lib/scopedRoutes";
import { cn } from "@/lib/utils";
import type { DashboardScopeProps } from "../scope";

/**
 * 4×2 dot-grid fleet hero. One dot per account, colored by health,
 * critical accounts pulse. Grouped by platform (IG top, Threads bottom).
 * Spec §4.2.
 */
export function FleetDotGrid({
	scopedAccount,
	accountIds,
	groupId,
	scopeLabel,
}: DashboardScopeProps) {
	const navigate = useNavigate();
	const accountsPath = scopedRoute("/accounts", { scopedAccount, accountIds, groupId });
	const { accounts, totals, isLoading } = useFleetAccounts();
	const scopedAccounts = accounts.filter((account) => {
		if (scopedAccount)
			return (
				account.id === scopedAccount.id &&
				account.platform === scopedAccount.platform
			);
		if (accountIds && accountIds.length > 0)
			return accountIds.includes(account.id);
		return true;
	});
	const scopedTotals = scopedAccounts.reduce(
		(acc, account) => {
			acc.total += 1;
			if (account.health === "critical") acc.flagged += 1;
			else if (account.health === "offline") acc.inactive += 1;
			else if (account.health === "warn" || account.health === "idle")
				acc.drifting += 1;
			else acc.active += 1;
			return acc;
		},
		{ active: 0, flagged: 0, drifting: 0, inactive: 0, total: 0 },
	);
	const displayTotals =
		scopedAccount || (accountIds && accountIds.length > 0)
			? scopedTotals
			: totals;
	const displayHealthCounts = scopedAccounts.reduce(
		(acc, account) => {
			acc[account.health] = (acc[account.health] ?? 0) + 1;
			return acc;
		},
		{} as Record<string, number>,
	);

	// Order: critical → warn → idle → good → offline, then by platform.
	const sorted = [...scopedAccounts].sort((a, b) => {
		const rank: Record<string, number> = {
			critical: 0,
			warn: 1,
			idle: 2,
			good: 3,
			offline: 4,
		};
		const ra = rank[a.health] ?? 5;
		const rb = rank[b.health] ?? 5;
		if (ra !== rb) return ra - rb;
		if (a.platform !== b.platform) return a.platform === "instagram" ? -1 : 1;
		return a.handle.localeCompare(b.handle);
	});

	const cellClassFor = (h: string): string => {
		const base = "min-h-2 rounded-[3px] border transition-colors";
		if (h === "critical")
			return cn(
				base,
				"border-[color-mix(in_srgb,var(--color-error)_42%,var(--color-border))] bg-[color:var(--color-error)]",
			);
		if (h === "warn")
			return cn(
				base,
				"border-[color-mix(in_srgb,var(--color-warning)_38%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-warning)_58%,white)]",
			);
		if (h === "good")
			return cn(
				base,
				"border-[color-mix(in_srgb,var(--color-primary)_34%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-primary)_55%,transparent)]",
			);
		if (h === "idle")
			return cn(
				base,
				"border-[color-mix(in_srgb,var(--color-warning)_22%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-warning)_34%,var(--color-muted-foreground))] opacity-70",
			);
		return cn(base, "border-border bg-muted opacity-60");
	};
	const dotGridClass =
		"mt-4 grid grid-cols-[repeat(22,minmax(0,1fr))] gap-1 sm:grid-cols-[repeat(44,minmax(0,1fr))]";
	const loadingCellClass = "min-h-2 rounded-[3px] border border-border bg-muted";

	// Cap visible cells at 88 (compact 44×2 status strip). The sort above
	// already ranks critical → warn → idle → good → offline, so slicing
	// keeps every critical account visible regardless of fleet size.
	const hasOverflow = sorted.length > 88;
	const visible = hasOverflow ? sorted.slice(0, 87) : sorted.slice(0, 88);
	const overflowCount = Math.max(0, sorted.length - visible.length);
	const shownLabel = hasOverflow
		? `${visible.length} of ${displayTotals.total} accounts`
		: scopedAccount
			? "1 account"
			: `${displayTotals.total} accounts`;
	const needsAttention =
		displayTotals.flagged > 0 || displayTotals.inactive > 0 || displayTotals.drifting > 0;
	const headingLabel = scopedAccount
		? "Account status"
		: accountIds && accountIds.length > 0
			? `${scopeLabel ?? "Group"} status`
			: "All accounts status";

	return (
		<NovaCard
			variant="compact"
			className="h-full cursor-pointer transition-colors hover:bg-muted/30"
			contentClassName="flex h-full flex-col"
			onClick={() => navigate(accountsPath)}
			role="button"
			tabIndex={0}
			onKeyDown={(e) => {
				if (e.key === "Enter" || e.key === " ") {
					e.preventDefault();
					navigate(accountsPath);
				}
			}}
		>
				<div className="flex items-baseline justify-between gap-3">
					<span className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">
						{headingLabel} · {shownLabel}
					</span>
					{needsAttention ? (
						<Button
							type="button"
							size="sm"
							onClick={(event) => {
								event.stopPropagation();
								navigate(scopedRoute(accountsPath, {}, { status: "flagged" }));
							}}
						>
							<Wrench data-icon="inline-start" aria-hidden="true" />
							Fix critical
						</Button>
					) : (
						<Badge tone="outline">COMPOSITE HEALTH</Badge>
					)}
				</div>

				{isLoading ? (
					<NovaInset className={dotGridClass}>
						{Array.from({ length: 88 }).map((_, i) => (
							<div key={i} className={loadingCellClass} />
						))}
					</NovaInset>
				) : visible.length === 0 ? (
					<div className="flex-1 min-h-0 flex items-center justify-center">
						<NovaEmpty
							className="min-h-36"
							title="Connect first account"
							description="Health dots appear here after a Threads or Instagram account is connected."
							action={
								<Button
									type="button"
									size="sm"
									onClick={(event) => {
										event.stopPropagation();
										navigate("/accounts");
									}}
								>
									Connect account
								</Button>
							}
						/>
					</div>
				) : (
					<NovaInset className={dotGridClass}>
						{visible.map((a) => (
							<div
								key={a.id}
								className={cellClassFor(a.health)}
								title={`${a.handle} · ${a.health}`}
							/>
						))}
						{hasOverflow ? (
							<div
								className="flex min-h-2 items-center justify-center rounded-[3px] border border-border bg-muted text-[9px] font-semibold tabular-nums text-muted-foreground"
								title={`${overflowCount} more accounts`}
							>
								+{overflowCount}
							</div>
						) : null}
					</NovaInset>
				)}

				<div className="mt-3 flex shrink-0 flex-wrap gap-3">
					{[
						{
							label: "Healthy",
							count: displayTotals.active,
							swatch: "var(--color-primary)",
							opacity: 0.55,
						},
						{
							label: "Critical",
							count: displayTotals.flagged,
							swatch: "var(--color-error)",
							opacity: 1,
						},
						{
							label: "No sample",
							count: displayHealthCounts.warn ?? 0,
							swatch: "color-mix(in srgb, var(--color-warning) 58%, white)",
							opacity: 0.7,
						},
						{
							label: "Idle",
							count: displayHealthCounts.idle ?? 0,
							swatch:
								"color-mix(in srgb, var(--color-warning) 34%, var(--color-muted-foreground))",
							opacity: 0.55,
						},
						{
							label: "Paused",
							count: displayTotals.inactive,
							swatch: "var(--color-warning)",
							opacity: 0.45,
						},
					].map((item) => (
						<div
							key={item.label}
							className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground"
						>
							<span
								className="size-2.5 shrink-0 rounded-[3px]"
								style={{
									background: item.swatch,
									opacity: item.opacity,
								}}
							/>
							{item.label}
							<strong
								className="ml-1 font-mono font-semibold text-foreground"
							>
								{item.count}
							</strong>
						</div>
					))}
				</div>
		</NovaCard>
	);
}
