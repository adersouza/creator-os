import { useMemo } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/Tooltip";
import type { FleetAccount, FleetGroupMeta } from "@/hooks/useFleetAccounts";
import { labelFor } from "@/lib/socialPlatform";
import {
	accountSignalStatus,
	formatLastPost,
	hasTokenExpiringSignal,
	STATUS_LABEL,
	type AccountHealthSignal,
	UNASSIGNED_COLOR,
} from "./shared";

interface AccountMapViewProps {
	accounts: FleetAccount[];
	groups: FleetGroupMeta[];
	healthSignalsByAccount: Map<string, AccountHealthSignal[]>;
	onOpen: (account: FleetAccount) => void;
}

export function AccountMapView({
	accounts,
	groups,
	healthSignalsByAccount,
	onOpen,
}: AccountMapViewProps) {
	const grouped = useMemo(() => {
		const out = new Map<
			string,
			{ meta: FleetGroupMeta; rows: FleetAccount[] }
		>();
		for (const group of groups) out.set(group.id, { meta: group, rows: [] });
		const unassigned: FleetAccount[] = [];
		for (const account of accounts) {
			if (account.groupId && out.has(account.groupId))
				out.get(account.groupId)?.rows.push(account);
			else unassigned.push(account);
		}
		const sections = Array.from(out.values()).filter(
			(section) => section.rows.length > 0,
		);
		if (unassigned.length > 0) {
			sections.push({
				meta: { id: "unassigned", name: "Unassigned", color: UNASSIGNED_COLOR },
				rows: unassigned,
			});
		}
		return sections;
	}, [accounts, groups]);

	return (
		<div className="flex flex-col gap-6">
			{grouped.map((section) => (
				<NovaCard
					key={section.meta.id}
					variant="panel"
					title={
						<span className="flex items-center gap-2">
							<span
								className="size-1.5 rounded-full"
								style={{ background: section.meta.color }}
							/>
							{section.meta.name}
						</span>
					}
					action={<Badge tone="outline">{section.rows.length}</Badge>}
					contentClassName="pt-0"
				>
					<div className="flex flex-wrap gap-[3px]">
						{section.rows.map((account) => (
							<MapCell
								key={account.id}
								account={account}
								signals={healthSignalsByAccount.get(account.id) ?? []}
								onOpen={() => onOpen(account)}
							/>
						))}
					</div>
				</NovaCard>
			))}
		</div>
	);
}

export function FleetHealthGrid({
	accounts,
	healthSignalsByAccount,
	onOpen,
}: AccountMapViewProps) {
	const counts = useMemo(() => {
		const next = { active: 0, drifting: 0, flagged: 0, inactive: 0 };
		for (const account of accounts) {
			next[
				accountSignalStatus(
					account.health,
					healthSignalsByAccount.get(account.id),
				)
			] += 1;
		}
		return next;
	}, [accounts, healthSignalsByAccount]);

	return (
		<NovaCard
			className="mt-10"
			title="Fleet health"
			description={`${accounts.length} ${accounts.length === 1 ? "account" : "accounts"}`}
			action={
				<Badge tone={counts.flagged > 0 ? "oxblood" : "secondary"}>
					{counts.flagged} flagged
				</Badge>
			}
		>
			<div
				className="flex flex-wrap gap-[3px]"
				role="img"
				aria-label={`Fleet health grid: ${counts.active} active, ${counts.drifting} drifting, ${counts.flagged} flagged, ${counts.inactive} inactive`}
			>
				{accounts.map((account) => {
					const signals = healthSignalsByAccount.get(account.id) ?? [];
					const label = mapTooltip(account, signals);
					return (
						<Tooltip key={account.id}>
							<TooltipTrigger asChild>
								<Button
									type="button"
									onClick={() => onOpen(account)}
									aria-label={label}
									variant="ghost"
									size="icon"
									className="h-[7px] min-h-0 w-[7px] min-w-0 rounded-[1px] p-0 transition-transform hover:scale-[1.6]"
									style={{
										backgroundColor: statusColor(account, signals, false),
									}}
								/>
							</TooltipTrigger>
							<TooltipContent>{label}</TooltipContent>
						</Tooltip>
					);
				})}
			</div>
			<div className="mt-3 flex items-center gap-4 text-[0.65625rem] text-muted-foreground tabular-nums">
				<Legend
					color="var(--color-health-good)"
					label={`Active ${counts.active}`}
				/>
				<Legend
					color="var(--color-warning)"
					label={`Drifting ${counts.drifting}`}
				/>
				<Legend
					color="var(--color-critical)"
					label={`Flagged ${counts.flagged}`}
				/>
				<Legend
					color="color-mix(in_srgb,var(--color-foreground)_18%,transparent)"
					label={`Inactive ${counts.inactive}`}
				/>
			</div>
		</NovaCard>
	);
}

function MapCell({
	account,
	signals,
	onOpen,
}: {
	account: FleetAccount;
	signals: AccountHealthSignal[];
	onOpen: () => void;
}) {
	const tokenExpiring = hasTokenExpiringSignal(signals);
	const label = mapTooltip(account, signals);
	return (
		<Tooltip>
			<TooltipTrigger asChild>
				<Button
					type="button"
					onClick={onOpen}
					aria-label={label}
					variant="ghost"
					size="icon"
					className="relative h-5 min-h-0 w-5 min-w-0 rounded-[5px] p-0 transition-transform duration-[80ms] hover:z-10 hover:scale-[1.25] hover:shadow-[0_4px_12px_color-mix(in_srgb,var(--color-foreground)_12%,transparent)]"
					style={{ background: statusColor(account, signals, true) }}
				>
					{tokenExpiring && (
						<span
							className="absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-[var(--color-critical)] ring-1 ring-card"
							aria-hidden="true"
						/>
					)}
				</Button>
			</TooltipTrigger>
			<TooltipContent>{label}</TooltipContent>
		</Tooltip>
	);
}

function Legend({ color, label }: { color: string; label: string }) {
	return (
		<span className="flex items-center gap-1.5">
			<span
				className="size-[7px] rounded-[1px]"
				style={{ backgroundColor: color }}
			/>
			{label}
		</span>
	);
}

function statusColor(
	account: FleetAccount,
	signals: AccountHealthSignal[],
	large: boolean,
): string {
	const ui = accountSignalStatus(account.health, signals);
	if (ui === "flagged") return "var(--color-critical)";
	if (ui === "drifting") return "var(--color-warning)";
	if (ui === "inactive")
		return large
			? "color-mix(in_srgb,var(--color-foreground)_8%,transparent)"
			: "color-mix(in_srgb,var(--color-foreground)_18%,transparent)";
	return "var(--color-health-good)";
}

function mapTooltip(
	account: FleetAccount,
	signals: AccountHealthSignal[],
): string {
	const ui = accountSignalStatus(account.health, signals);
	const activeSignal = signals.find((signal) => !signal.resolved_at);
	const reason = activeSignal
		? ` - ${activeSignal.signal_type.replace(/_/g, " ")}`
		: "";
	return `${account.handle} - ${labelFor(account.platform)} - last posted ${formatLastPost(
		account.lastPostHoursAgo,
	)} ago - ${STATUS_LABEL[ui]}${reason}`;
}
