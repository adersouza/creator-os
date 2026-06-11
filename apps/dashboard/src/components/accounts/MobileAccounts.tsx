import { useMemo, useRef, useState } from "react";
import { BarChart3, MoreVertical, Plus, Search } from "lucide-react";
import type {
	FleetAccount,
	FleetAccountTotals,
	FleetGroupMeta,
} from "@/hooks/useFleetAccounts";
import { labelFor } from "@/lib/socialPlatform";
import { MobilePageShell } from "@/components/layout/mobile";
import { Sheet } from "@/components/ui/Sheet";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Input } from "@/components/ui/Input";
import { NovaEmpty, NovaHeader, NovaStat } from "@/components/ui/NovaPrimitives";
import type { AccountGroup } from "@/hooks/useAccountGroups";
import { AccountGroupsPanel } from "./AccountGroupsPanel";
import type { StatusFilter } from "./shared";
import { formatFollowers, uiStatusFromHealth } from "./shared";

interface MobileAccountsProps {
	accounts: FleetAccount[];
	allAccounts: FleetAccount[];
	totals: FleetAccountTotals;
	groups: FleetGroupMeta[];
	groupsCount: number;
	isLoading: boolean;
	status: StatusFilter;
	selected: Set<string>;
	selectedRows: FleetAccount[];
	onToggleSelect: (id: string) => void;
	onClearSelect: () => void;
	onStatusChange: (status: StatusFilter) => void;
	onCreateGroup: (input: {
		name: string;
		color: string;
		accountIds: string[];
	}) => Promise<AccountGroup | null>;
	onUpdateGroup: (input: {
		id: string;
		name: string;
		color: string;
	}) => Promise<AccountGroup | null>;
	onDeleteGroup: (id: string) => Promise<void>;
	onFilterGroup: (id: string) => void;
	onMoveSelectedToGroup: (group: FleetGroupMeta) => Promise<void>;
	onUnassignSelected: () => Promise<void>;
	onOpen: (account: FleetAccount) => void;
	onPause: (account: FleetAccount) => void;
	onViewScheduler: (account: FleetAccount) => void;
	onViewAnalytics: (account: FleetAccount) => void;
	onMoveGroup: (account: FleetAccount) => void;
	onSync: (account: FleetAccount) => void;
	onHealthCheck: (account: FleetAccount) => void;
	onReconnect: (account: FleetAccount) => void;
	onRemove: (account: FleetAccount) => void;
	onAddAccount: () => void;
}

export function MobileAccounts({
	accounts,
	allAccounts,
	totals,
	groups,
	groupsCount,
	isLoading,
	status,
	selected,
	selectedRows,
	onToggleSelect,
	onClearSelect,
	onStatusChange,
	onCreateGroup,
	onUpdateGroup,
	onDeleteGroup,
	onFilterGroup,
	onMoveSelectedToGroup,
	onUnassignSelected,
	onOpen,
	onPause,
	onViewScheduler,
	onViewAnalytics,
	onMoveGroup,
	onSync,
	onHealthCheck,
	onReconnect,
	onRemove,
	onAddAccount,
}: MobileAccountsProps) {
	const [search, setSearch] = useState("");
	const [menuAccount, setMenuAccount] = useState<FleetAccount | null>(null);
	const longPressTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(
		new Map(),
	);
	const longPressFiredFor = useRef<Set<string>>(new Set());
	const safeTotals =
		totals ??
		(() => {
			const t = {
				total: accounts.length,
				active: 0,
				drifting: 0,
				flagged: 0,
				inactive: 0,
			};
			for (const a of accounts) {
				const ui = uiStatusFromHealth(a.health);
				if (ui === "active") t.active++;
				else if (ui === "drifting") t.drifting++;
				else if (ui === "flagged") t.flagged++;
				else if (ui === "inactive") t.inactive++;
			}
			return t;
		})();
	const isSelectMode = selected.size > 0;
	const startLongPress = (id: string) => {
		longPressFiredFor.current.delete(id);
		const timer = setTimeout(() => {
			longPressFiredFor.current.add(id);
			onToggleSelect(id);
		}, 500);
		longPressTimers.current.set(id, timer);
	};
	const cancelLongPress = (id: string) => {
		const timer = longPressTimers.current.get(id);
		if (timer) {
			clearTimeout(timer);
			longPressTimers.current.delete(id);
		}
	};
	const consumeLongPress = (id: string): boolean => {
		const fired = longPressFiredFor.current.has(id);
		longPressFiredFor.current.delete(id);
		return fired;
	};
	const shown = useMemo(() => {
		const q = search.trim().toLowerCase();
		const filtered = q
			? accounts.filter(
					(account) =>
						account.handle.toLowerCase().includes(q) ||
						account.displayName.toLowerCase().includes(q),
				)
			: accounts;
		return filtered.slice(0, 120);
	}, [accounts, search]);

	if (!isLoading && accounts.length === 0) {
		return (
			<MobilePageShell>
				<NovaHeader
					eyebrow="Accounts"
					title="Connected networks"
					meta="Fleet · live"
					description="Connect a Threads or Instagram account to start monitoring health, access, and sync state."
					actions={
						<Button type="button" onClick={onAddAccount} size="sm">
							<Plus data-icon="inline-start" />
							Add account
						</Button>
					}
				/>
				<NovaEmpty
					title="Connect your first account"
					description="Juno33 needs at least one Threads or Instagram account before this fleet can show status, groups, and reconnect actions."
					icon={<Plus data-icon="inline-start" aria-hidden="true" />}
					action={
						<Button type="button" onClick={onAddAccount}>
							<Plus data-icon="inline-start" />
							Connect account
						</Button>
					}
				/>
			</MobilePageShell>
		);
	}

	return (
		<MobilePageShell>
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
							: `${safeTotals.total} account${safeTotals.total === 1 ? "" : "s"}${groupsCount > 0 ? ` across ${groupsCount} network${groupsCount === 1 ? "" : "s"}` : ""}.`}
					</>
				}
				filters={
					<>
						<Badge>{safeTotals.active} active</Badge>
						<Badge tone={safeTotals.flagged > 0 ? "oxblood" : "secondary"}>
							{safeTotals.flagged} flagged
						</Badge>
						<Badge tone="outline">{safeTotals.drifting} drifting</Badge>
					</>
				}
				actions={
					<Button type="button" onClick={onAddAccount} size="sm">
						<Plus data-icon="inline-start" />
						Add account
					</Button>
				}
			/>

			<div className="mb-4 grid grid-cols-2 gap-2.5">
				<NovaStat
					label="Active"
					value={safeTotals.active}
					status={status === "active" ? <Badge>Selected</Badge> : undefined}
					action={
						<Button
							type="button"
							size="sm"
							variant={status === "active" ? "default" : "outline"}
							onClick={() =>
								onStatusChange(status === "active" ? "all" : "active")
							}
						>
							Filter
						</Button>
					}
				/>
				<NovaStat
					label="Drifting"
					value={safeTotals.drifting}
					status={status === "drifting" ? <Badge>Selected</Badge> : undefined}
					action={
						<Button
							type="button"
							size="sm"
							variant={status === "drifting" ? "default" : "outline"}
							onClick={() =>
								onStatusChange(status === "drifting" ? "all" : "drifting")
							}
						>
							Filter
						</Button>
					}
				/>
				<NovaStat
					label="Flagged"
					value={safeTotals.flagged}
					status={
						safeTotals.flagged > 0 ? (
							<Badge tone="oxblood">Review</Badge>
						) : undefined
					}
					action={
						<Button
							type="button"
							size="sm"
							variant={status === "flagged" ? "default" : "outline"}
							onClick={() =>
								onStatusChange(status === "flagged" ? "all" : "flagged")
							}
						>
							Filter
						</Button>
					}
				/>
				<NovaStat
					label="Inactive"
					value={safeTotals.inactive}
					status={status === "inactive" ? <Badge>Selected</Badge> : undefined}
					action={
						<Button
							type="button"
							size="sm"
							variant={status === "inactive" ? "default" : "outline"}
							onClick={() =>
								onStatusChange(status === "inactive" ? "all" : "inactive")
							}
						>
							Filter
						</Button>
					}
				/>
			</div>

			<AccountGroupsPanel
				groups={groups}
				accounts={allAccounts}
				selectedRows={selectedRows}
				onCreateGroup={onCreateGroup}
				onUpdateGroup={onUpdateGroup}
				onDeleteGroup={onDeleteGroup}
				onFilterGroup={onFilterGroup}
				onMoveSelectedToGroup={onMoveSelectedToGroup}
				onUnassignSelected={onUnassignSelected}
			/>

			<NovaCard className="mb-3" title="Find account">
				<Input
					type="text"
					value={search}
					onChange={(event) => setSearch(event.target.value)}
					placeholder="Search by handle..."
					aria-label="Search accounts"
					leadingIcon={<Search aria-hidden="true" />}
				/>
			</NovaCard>

			<ul className="flex flex-col gap-1.5">
				{shown.map((account) => {
					const ui = uiStatusFromHealth(account.health);
					const statusColor =
						ui === "flagged"
							? "var(--color-oxblood)"
							: ui === "drifting"
								? "var(--color-gold)"
								: ui === "inactive"
									? "color-mix(in srgb, var(--color-foreground) 30%, transparent)"
									: "var(--color-health-good)";
					const isChecked = selected.has(account.id);
					const handleRowTap = () => {
						if (consumeLongPress(account.id)) return;
						if (isSelectMode) {
							onToggleSelect(account.id);
						} else {
							onOpen(account);
						}
					};
					return (
						<li key={account.id}>
							<NovaCard
								variant="panel"
								className="active:bg-muted"
								contentClassName="flex items-center gap-3 px-3 py-2.5"
								onPointerDown={() => startLongPress(account.id)}
								onPointerUp={() => cancelLongPress(account.id)}
								onPointerLeave={() => cancelLongPress(account.id)}
								onPointerCancel={() => cancelLongPress(account.id)}
							>
								{isSelectMode ? (
									<Checkbox
										checked={isChecked}
										aria-label={`${isChecked ? "Deselect" : "Select"} ${account.handle}`}
										className="size-7 rounded-md"
										onClick={(event) => {
											event.stopPropagation();
											if (consumeLongPress(account.id)) return;
											onToggleSelect(account.id);
										}}
										onCheckedChange={() => undefined}
									/>
								) : (
									<span
										className="flex size-9 flex-shrink-0 items-center justify-center rounded-full text-[0.75rem] font-semibold text-white"
										style={{
											background: `linear-gradient(135deg, ${account.groupColor}, color-mix(in srgb, ${account.groupColor} 55%, var(--color-ink)))`,
										}}
									>
										{(account.displayName[0] ?? ".").toUpperCase()}
									</span>
								)}
								<Button
									type="button"
									onClick={handleRowTap}
									variant="ghost"
									className="min-w-0 flex-1 justify-start px-0 text-left hover:bg-transparent"
								>
									<div className="text-[0.84375rem] font-medium text-foreground truncate">
										{account.handle}
									</div>
									<div className="text-[0.6875rem] text-muted-foreground truncate">
										{account.groupName} - {labelFor(account.platform)} -{" "}
										{formatFollowers(account.followers)}
									</div>
								</Button>
								<span
									role="img"
									className="size-2.5 flex-shrink-0 rounded-full"
									style={{ backgroundColor: statusColor }}
									aria-label={ui}
								/>
								{isSelectMode ? null : (
									<Button
										type="button"
										onClick={(event) => {
											event.stopPropagation();
											onViewAnalytics(account);
										}}
										aria-label={`View analytics for ${account.handle}`}
										variant="secondary"
										size="icon"
									>
										<BarChart3 data-icon="icon" aria-hidden="true" />
									</Button>
								)}
								<Button
									type="button"
									onClick={(event) => {
										event.stopPropagation();
										setMenuAccount(account);
									}}
									aria-label={`More actions for ${account.handle}`}
									variant="ghost"
									size="icon"
									className="-mr-1"
								>
									<MoreVertical data-icon="icon" aria-hidden="true" />
								</Button>
							</NovaCard>
						</li>
					);
				})}
				{shown.length === 0 && (
					<li>
						<NovaEmpty
							className="min-h-24"
							title={`No accounts match "${search}"`}
							description="Try a different handle or clear the search field."
						/>
					</li>
				)}
				{!search && accounts.length > shown.length && (
					<li className="text-center py-3 text-[0.71875rem] text-muted-foreground tabular-nums">
						Showing {shown.length} of {accounts.length} - search to find more
					</li>
				)}
			</ul>
			{isSelectMode && (
				<div className="fixed top-0 inset-x-0 z-30 flex items-center gap-2 px-3 py-2 border-b border-border bg-card">
					<Button
						type="button"
						onClick={onClearSelect}
						variant="ghost"
						size="sm"
					>
						Cancel
					</Button>
					<div className="text-[0.84375rem] font-medium text-foreground tabular-nums">
						{selected.size} selected
					</div>
				</div>
			)}
			<Sheet
				open={menuAccount !== null}
				onClose={() => setMenuAccount(null)}
				side="bottom"
				ariaLabel="Row actions"
				title={menuAccount ? menuAccount.handle : undefined}
			>
				{menuAccount && (
					<ul className="flex flex-col gap-1 py-2">
						<li>
							<Button
								type="button"
								onClick={() => {
									const target = menuAccount;
									setMenuAccount(null);
									onViewAnalytics(target);
								}}
								variant="ghost"
								className="w-full justify-start"
							>
								View analytics
							</Button>
						</li>
						<li>
							<Button
								type="button"
								onClick={() => {
									const target = menuAccount;
									setMenuAccount(null);
									onOpen(target);
								}}
								variant="ghost"
								className="w-full justify-start"
							>
								Open detail
							</Button>
						</li>
						<li>
							<Button
								type="button"
								onClick={() => {
									const target = menuAccount;
									setMenuAccount(null);
									onViewScheduler(target);
								}}
								variant="ghost"
								className="w-full justify-start"
							>
								Open in Scheduler
							</Button>
						</li>
						<li>
							<Button
								type="button"
								onClick={() => {
									const target = menuAccount;
									setMenuAccount(null);
									onPause(target);
								}}
								variant="ghost"
								className="w-full justify-start"
							>
								{menuAccount.isActive ? "Pause" : "Resume"}
							</Button>
						</li>
						<li>
							<Button
								type="button"
								onClick={() => {
									const target = menuAccount;
									setMenuAccount(null);
									onMoveGroup(target);
								}}
								variant="ghost"
								className="w-full justify-start"
							>
								Move to group
							</Button>
						</li>
						<li>
							<Button
								type="button"
								onClick={() => {
									const target = menuAccount;
									setMenuAccount(null);
									onSync(target);
								}}
								variant="ghost"
								className="w-full justify-start"
							>
								Sync now
							</Button>
						</li>
						<li>
							<Button
								type="button"
								onClick={() => {
									const target = menuAccount;
									setMenuAccount(null);
									onHealthCheck(target);
								}}
								variant="ghost"
								className="w-full justify-start"
							>
								Health check
							</Button>
						</li>
						<li>
							<Button
								type="button"
								onClick={() => {
									const target = menuAccount;
									setMenuAccount(null);
									onReconnect(target);
								}}
								variant="ghost"
								className="w-full justify-start"
							>
								Reconnect
							</Button>
						</li>
						<li>
							<Button
								type="button"
								onClick={() => {
									const target = menuAccount;
									setMenuAccount(null);
									onToggleSelect(target.id);
								}}
								variant="ghost"
								className="w-full justify-start"
							>
								{selected.has(menuAccount.id) ? "Deselect" : "Select"}
							</Button>
						</li>
						<li>
							<Button
								type="button"
								onClick={() => {
									const target = menuAccount;
									setMenuAccount(null);
									onRemove(target);
								}}
								variant="danger"
								className="w-full justify-start"
							>
								Remove
							</Button>
						</li>
					</ul>
				)}
			</Sheet>
		</MobilePageShell>
	);
}
