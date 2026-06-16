import { useMemo, useState } from "react";
import type React from "react";
import {
	Check,
	Edit3,
	FolderInput,
	Plus,
	Trash2,
	Users,
	X,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Input } from "@/components/ui/Input";
import { Separator } from "@/components/ui/Separator";
import type { AccountGroup } from "@/hooks/useAccountGroups";
import type { FleetAccount, FleetGroupMeta } from "@/hooks/useFleetAccounts";
import { appToast } from "@/lib/toast";
import { UNASSIGNED_COLOR, type GroupFilter } from "./shared";

const GROUP_COLORS = [
	"#E5484D",
	"#B33A3F",
	"#A67C2D",
	"#4F7661",
	"#5F6670",
	"#6F7078",
	"#8A8D94",
	"#1A1A1C",
];
const DEFAULT_GROUP_COLOR = "#E5484D";

interface AccountGroupsRailProps {
	groups: FleetGroupMeta[];
	accounts: FleetAccount[];
	selectedRows: FleetAccount[];
	activeGroup: GroupFilter;
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
	onFilterGroup: (id: GroupFilter) => void;
	onMoveSelectedToGroup: (group: FleetGroupMeta) => Promise<void>;
	onUnassignSelected: () => Promise<void>;
}

export function AccountGroupsRail({
	groups,
	accounts,
	selectedRows,
	activeGroup,
	onCreateGroup,
	onUpdateGroup,
	onDeleteGroup,
	onFilterGroup,
	onMoveSelectedToGroup,
	onUnassignSelected,
}: AccountGroupsRailProps) {
	const [name, setName] = useState("");
	const [color, setColor] = useState(DEFAULT_GROUP_COLOR);
	const [saving, setSaving] = useState(false);
	const [editingId, setEditingId] = useState<string | null>(null);
	const [editingName, setEditingName] = useState("");
	const [editingColor, setEditingColor] = useState(DEFAULT_GROUP_COLOR);
	const [deleteTarget, setDeleteTarget] = useState<FleetGroupMeta | null>(null);
	const [deleteBusy, setDeleteBusy] = useState(false);

	const accountCountByGroup = useMemo(() => {
		const counts = new Map<string, number>();
		for (const account of accounts) {
			if (!account.groupId) continue;
			counts.set(account.groupId, (counts.get(account.groupId) ?? 0) + 1);
		}
		return counts;
	}, [accounts]);

	const unassignedCount = accounts.filter((account) => !account.groupId).length;
	const selectedIds = selectedRows.map((account) => account.id);

	const submitCreate = async () => {
		const nextName = name.trim();
		if (!nextName || saving) return;
		setSaving(true);
		try {
			const created = await onCreateGroup({
				name: nextName,
				color,
				accountIds: selectedIds,
			});
			if (!created) throw new Error("Group could not be created");
			appToast.success(
				selectedIds.length > 0
					? `Created ${created.name} and moved ${selectedIds.length} account${selectedIds.length === 1 ? "" : "s"}`
					: `Created ${created.name}`,
			);
			setName("");
			setColor(DEFAULT_GROUP_COLOR);
		} catch (error) {
			appToast.error("Could not create group", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setSaving(false);
		}
	};

	const startEditing = (group: FleetGroupMeta) => {
		setEditingId(group.id);
		setEditingName(group.name);
		setEditingColor(group.color);
	};

	const submitEdit = async () => {
		if (!editingId) return;
		const nextName = editingName.trim();
		if (!nextName || saving) return;
		setSaving(true);
		try {
			const updated = await onUpdateGroup({
				id: editingId,
				name: nextName,
				color: editingColor,
			});
			if (!updated) throw new Error("Group could not be updated");
			appToast.success(`Updated ${updated.name}`);
			setEditingId(null);
		} catch (error) {
			appToast.error("Could not update group", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setSaving(false);
		}
	};

	const confirmDelete = async () => {
		if (!deleteTarget) return;
		setDeleteBusy(true);
		try {
			await onDeleteGroup(deleteTarget.id);
			appToast.success(`Deleted ${deleteTarget.name}`);
			setDeleteTarget(null);
		} catch (error) {
			appToast.error("Could not delete group", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setDeleteBusy(false);
		}
	};

	return (
		<NovaCard className="sticky top-4 max-h-[calc(100dvh-2rem)] overflow-hidden p-0">
			<div className="flex h-full max-h-[calc(100dvh-2rem)] flex-col">
				<div className="border-b border-border px-4 py-4">
					<div className="flex items-start justify-between gap-3">
						<div className="min-w-0">
							<div className="text-[0.6875rem] font-semibold uppercase tracking-[0.11em] text-muted-foreground">
								Groups
							</div>
							<div className="mt-1 text-[0.9375rem] font-semibold text-foreground">
								Account sets
							</div>
							<p className="mt-1 text-[0.75rem] leading-snug text-muted-foreground">
								Filter and move accounts by group.
							</p>
						</div>
						<span className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
							<Users className="size-4" aria-hidden="true" />
						</span>
					</div>
					{selectedIds.length > 0 && (
						<div className="mt-3 rounded-lg border border-border bg-muted/50 px-3 py-2">
							<div className="text-[0.75rem] font-semibold text-foreground tabular-nums">
								{selectedIds.length} selected
							</div>
							<div className="mt-1 text-[0.6875rem] leading-snug text-muted-foreground">
								Use a group row to move them, or unassign below.
							</div>
						</div>
					)}
				</div>

				<div className="flex-1 overflow-y-auto px-2.5 py-2.5">
					<RailButton
						active={activeGroup === "all"}
						label="All accounts"
						count={accounts.length}
						onClick={() => onFilterGroup("all")}
					/>
					<RailButton
						active={activeGroup === "unassigned"}
						label="Unassigned"
						count={unassignedCount}
						color={UNASSIGNED_COLOR}
						onClick={() => onFilterGroup("unassigned")}
						trailing={
							selectedIds.length > 0 ? (
								<MiniAction
									label="Unassign selected"
									onClick={() => void onUnassignSelected()}
								>
									<X data-icon="icon" />
								</MiniAction>
							) : null
						}
					/>

					<Separator className="my-2" />

					{groups.length === 0 ? (
						<NovaEmpty
							className="mx-2 min-h-24"
							title="No custom groups yet"
							description="Create a group below to organize accounts."
						/>
					) : (
						<div className="flex flex-col gap-1">
							{groups.map((group) => {
								const count = accountCountByGroup.get(group.id) ?? 0;
								const isEditing = editingId === group.id;
								if (isEditing) {
									return (
										<div
											key={group.id}
											className="rounded-lg border border-border bg-background p-2"
										>
											<Input
												value={editingName}
												onChange={(event) => setEditingName(event.target.value)}
												maxLength={40}
												aria-label={`Edit group name for ${group.name}`}
												className="h-9 rounded-lg px-2"
											/>
											<div className="mt-2">
												<ColorPicker
													value={editingColor}
													onChange={setEditingColor}
												/>
											</div>
											<div className="mt-2 flex items-center justify-end gap-1.5">
												<MiniAction
													label="Save group"
													onClick={() => void submitEdit()}
												>
													<Check data-icon="icon" />
												</MiniAction>
												<MiniAction
													label="Cancel edit"
													onClick={() => setEditingId(null)}
												>
													<X data-icon="icon" />
												</MiniAction>
											</div>
										</div>
									);
								}
								return (
									<RailButton
										key={group.id}
										active={activeGroup === group.id}
										label={group.name}
										count={count}
										color={group.color}
										onClick={() => onFilterGroup(group.id)}
										trailing={
											<div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
												{selectedIds.length > 0 && (
													<MiniAction
														label={`Move selected to ${group.name}`}
														onClick={() => void onMoveSelectedToGroup(group)}
													>
														<FolderInput data-icon="icon" />
													</MiniAction>
												)}
												<MiniAction
													label={`Edit ${group.name}`}
													onClick={() => startEditing(group)}
												>
													<Edit3 data-icon="icon" />
												</MiniAction>
												<MiniAction
													label={`Delete ${group.name}`}
													destructive
													onClick={() => setDeleteTarget(group)}
												>
													<Trash2 data-icon="icon" />
												</MiniAction>
											</div>
										}
									/>
								);
							})}
						</div>
					)}
				</div>

				<div className="border-t border-border bg-card p-3">
					<label
						htmlFor="account-groups-rail-name"
						className="grid gap-1.5 text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
					>
						New group
						<Input
							id="account-groups-rail-name"
							value={name}
							onChange={(event) => setName(event.target.value)}
							onKeyDown={(event) => {
								if (event.key === "Enter") {
									event.preventDefault();
									void submitCreate();
								}
							}}
							placeholder="Launch accounts"
							maxLength={40}
							className="h-9 rounded-lg bg-background font-medium normal-case tracking-normal"
						/>
					</label>
					<div className="mt-2">
						<ColorPicker value={color} onChange={setColor} />
					</div>
					<Button
						type="button"
						onClick={() => void submitCreate()}
						disabled={!name.trim() || saving}
						className="mt-3 w-full"
					>
						<Plus data-icon="inline-start" />
						{selectedIds.length > 0
							? `Create with ${selectedIds.length}`
							: "Create group"}
					</Button>
				</div>
			</div>

			<ConfirmDialog
				open={deleteTarget !== null}
				onClose={() => {
					if (!deleteBusy) setDeleteTarget(null);
				}}
				onConfirm={confirmDelete}
				title={`Delete ${deleteTarget?.name ?? "group"}?`}
				description="Accounts in this group will become unassigned. Scheduled posts and historical analytics stay intact."
				confirmLabel="Delete group"
				destructive
				busy={deleteBusy}
			/>
		</NovaCard>
	);
}

function RailButton({
	active,
	label,
	count,
	color,
	trailing,
	onClick,
}: {
	active: boolean;
	label: string;
	count: number;
	color?: string | undefined;
	trailing?: React.ReactNode;
	onClick: () => void;
}) {
	return (
		<div className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1 rounded-lg">
			<Button
				type="button"
				onClick={onClick}
				aria-pressed={active}
				variant="ghost"
				className={`h-11 min-w-0 justify-start rounded-lg px-3 text-left ${active ? "bg-muted text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground"}`}
			>
				<span className="flex min-w-0 flex-1 items-center gap-2">
					{color && (
						<span
							className="size-2 shrink-0 rounded-full"
							style={{ backgroundColor: active ? "currentColor" : color }}
						/>
					)}
					<span className="min-w-0 flex-1 truncate text-[0.8125rem] font-medium">
						{label}
					</span>
					<Badge
						tone={active ? "secondary" : "outline"}
						className="h-5 min-w-6 justify-center px-1.5 text-[0.6875rem] tabular-nums"
					>
						{count}
					</Badge>
				</span>
			</Button>
			{trailing}
		</div>
	);
}

function ColorPicker({
	value,
	onChange,
}: {
	value: string;
	onChange: (value: string) => void;
}) {
	return (
		<div className="flex flex-wrap gap-1.5" role="group" aria-label="Group color">
			{GROUP_COLORS.map((hex) => (
				<Button
					key={hex}
					type="button"
					onClick={() => onChange(hex)}
					aria-label={`Use ${hex}`}
					variant="ghost"
					size="icon"
					className="size-8 rounded-full p-0"
					style={{
						backgroundColor: hex,
						boxShadow:
							value === hex
								? "0 0 0 2px var(--color-background), 0 0 0 4px var(--color-oxblood)"
								: undefined,
					}}
				/>
			))}
		</div>
	);
}

function MiniAction({
	label,
	destructive,
	onClick,
	children,
}: {
	label: string;
	destructive?: boolean | undefined;
	onClick: () => void;
	children: React.ReactNode;
}) {
	return (
		<Button
			type="button"
			aria-label={label}
			title={label}
			onClick={(event) => {
				event.stopPropagation();
				onClick();
			}}
			variant="ghost"
			size="icon"
			className="size-8 rounded-lg text-muted-foreground"
			style={destructive ? { color: "var(--color-danger)" } : undefined}
		>
			{children}
		</Button>
	);
}
