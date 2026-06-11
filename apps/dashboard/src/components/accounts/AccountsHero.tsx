import { Link2, Plus } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaEmpty, NovaHeader } from "@/components/ui/NovaPrimitives";
import { cn } from "@/lib/utils";
import type { FleetAccountTotals } from "@/hooks/useFleetAccounts";
import type { StatusFilter } from "./shared";

interface AccountsHeroProps {
	totals: FleetAccountTotals;
	groupsCount: number;
	isLoading: boolean;
	status: StatusFilter;
	showEmpty: boolean;
	onStatusChange: (status: StatusFilter) => void;
	onAddAccount: () => void;
}

export function AccountsHero({
	totals,
	groupsCount,
	isLoading,
	status,
	showEmpty,
	onStatusChange,
	onAddAccount,
}: AccountsHeroProps) {
	return (
		<>
			<NovaHeader
				eyebrow="Accounts"
				title="Connected networks"
				meta="Fleet · live"
				description={
					<>
						<strong className="font-semibold text-foreground">
							Monitor health, publishing access, and sync state.
						</strong>{" "}
						{isLoading
							? "Loading account coverage."
							: `${totals.total} account${totals.total === 1 ? "" : "s"}${groupsCount > 0 ? ` across ${groupsCount} network${groupsCount === 1 ? "" : "s"}` : ""}.`}
					</>
				}
				filters={
					<>
						<Badge tone="secondary">{totals.active} active</Badge>
						<Badge tone={totals.flagged > 0 ? "danger" : "outline"}>
							{totals.flagged} flagged
						</Badge>
						<Badge tone="outline">{totals.drifting} drifting</Badge>
					</>
				}
				actions={
					<Button type="button" onClick={onAddAccount}>
						<Plus data-icon="inline-start" />
						Add account
					</Button>
				}
			/>

			{showEmpty ? (
				<div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
					<NovaEmpty
						className="border-0 bg-transparent"
						title="No accounts connected yet"
						description="Link your Threads or Instagram accounts to start monitoring health, publishing content, and pulling analytics."
						icon={<Link2 data-icon="inline-start" aria-hidden="true" />}
						action={
							<>
							<Button type="button" onClick={onAddAccount}>
								Connect account
							</Button>
							<Button type="button" variant="outline" onClick={onAddAccount}>
								Or import a list
							</Button>
							</>
						}
					>
						<Badge tone="outline">Fleet - not yet connected</Badge>
						<GhostAccountRows />
					</NovaEmpty>
				</div>
			) : (
				<div className="mb-6 flex flex-col gap-3 rounded-xl border border-border bg-card p-3 shadow-sm sm:flex-row sm:items-center sm:justify-between">
					<div className="min-w-0">
						<div className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-[color:var(--color-oxblood)]">
							Fleet filters
						</div>
						<p className="app-caption mt-1 text-muted-foreground">
							Use health state as a filter. Detailed account metrics live in the
							list below.
						</p>
					</div>
					<div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:justify-end">
						<AccountStatusFilter
							label="Active"
							value={totals.active}
							tone="good"
							selected={status === "active"}
							onClick={() =>
								onStatusChange(status === "active" ? "all" : "active")
							}
						/>
						<AccountStatusFilter
							label="Drifting"
							value={totals.drifting}
							tone="warn"
							selected={status === "drifting"}
							onClick={() =>
								onStatusChange(status === "drifting" ? "all" : "drifting")
							}
						/>
						<AccountStatusFilter
							label="Flagged"
							value={totals.flagged}
							tone="bad"
							selected={status === "flagged"}
							onClick={() =>
								onStatusChange(status === "flagged" ? "all" : "flagged")
							}
						/>
						<AccountStatusFilter
							label="Inactive"
							value={totals.inactive}
							selected={status === "inactive"}
							onClick={() =>
								onStatusChange(status === "inactive" ? "all" : "inactive")
							}
						/>
					</div>
				</div>
			)}
		</>
	);
}

function AccountStatusFilter({
	label,
	value,
	selected,
	tone = "neutral",
	onClick,
}: {
	label: string;
	value: number;
	selected: boolean;
	tone?: "neutral" | "good" | "warn" | "bad" | undefined;
	onClick: () => void;
}) {
	const toneClass =
		tone === "good"
			? "text-[color:var(--color-health-good)]"
			: tone === "warn"
				? "text-[color:var(--color-warning)]"
				: tone === "bad"
					? "text-[color:var(--color-critical)]"
					: "text-muted-foreground";
	return (
		<Button
			type="button"
			aria-pressed={selected}
			onClick={onClick}
			variant={selected ? "default" : "outline"}
			size="sm"
			className={cn(
				"min-h-10 justify-between gap-3 text-left sm:min-w-[7.5rem]",
			)}
		>
			<span className="app-control-text text-muted-foreground">{label}</span>
			<span
				className={cn(
					"app-data text-[0.75rem] font-bold tabular-nums",
					toneClass,
				)}
			>
				{value.toLocaleString()}
			</span>
		</Button>
	);
}

function GhostAccountRows() {
	return (
		<div className="w-full h-full px-6 pt-14 pb-8">
			<div className="mx-auto flex max-w-[640px] flex-col gap-1.5">
				{Array.from({ length: 5 }).map((_, i) => (
					<div
						key={i}
						className="flex h-9 items-center gap-3 rounded-md border border-border bg-card px-3"
						aria-hidden="true"
					>
						<div className="size-5 rounded-full bg-muted" />
						<div className="h-2 max-w-[120px] flex-1 rounded-full bg-muted" />
						<div className="h-2 w-16 rounded-full bg-muted" />
						<div className="ml-auto h-2 w-10 rounded-full bg-muted" />
					</div>
				))}
			</div>
		</div>
	);
}
