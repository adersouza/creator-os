import { useMemo, useState } from "react";
import type React from "react";
import { Check, Edit3, Plus, Trash2, Users, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Input } from "@/components/ui/Input";
import { Separator } from "@/components/ui/Separator";
import type { AccountGroup } from "@/hooks/useAccountGroups";
import type { FleetAccount, FleetGroupMeta } from "@/hooks/useFleetAccounts";
import { appToast } from "@/lib/toast";
import { UNASSIGNED_COLOR } from "./shared";

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

interface AccountGroupsPanelProps {
	groups: FleetGroupMeta[];
	accounts: FleetAccount[];
	selectedRows: FleetAccount[];
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
}

export function AccountGroupsPanel({
	groups,
	accounts,
	selectedRows,
	onCreateGroup,
	onUpdateGroup,
	onDeleteGroup,
	onFilterGroup,
	onMoveSelectedToGroup,
	onUnassignSelected,
}: AccountGroupsPanelProps) {
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
		<NovaCard
			className="mb-5"
			title="Groups"
			description="Create networks and move accounts into them."
		>
			<div className="grid gap-4 lg:grid-cols-[minmax(280px,360px)_1fr]">
				<NovaCard variant="panel" contentClassName="p-3 md:p-4">
					<div className="flex items-center gap-2">
						<span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-muted text-muted-foreground">
							<Users className="h-3.5 w-3.5" aria-hidden="true" />
						</span>
						<div>
							<h2 className="text-[0.875rem] font-semibold text-foreground">
								Groups
							</h2>
							<p className="text-[0.71875rem] text-muted-foreground">
								Create networks and move accounts into them.
							</p>
						</div>
					</div>

					<div className="mt-4 grid gap-2">
						<label
							htmlFor="account-group-name"
							className="grid gap-1 text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
						>
							Group name
							<Input
								id="account-group-name"
								value={name}
								onChange={(event) => setName(event.target.value)}
								onKeyDown={(event) => {
									if (event.key === "Enter") {
										event.preventDefault();
										void submitCreate();
									}
								}}
								placeholder="e.g. Launch accounts"
								maxLength={40}
								className="h-11 rounded-lg bg-background font-medium normal-case tracking-normal md:h-9"
							/>
						</label>
						<ColorPicker value={color} onChange={setColor} />
						<Button
							type="button"
							onClick={() => void submitCreate()}
							disabled={!name.trim() || saving}
							className="mt-1 w-full"
						>
							<Plus data-icon="inline-start" />
							{selectedIds.length > 0
								? `Create with ${selectedIds.length} selected`
								: "Create group"}
						</Button>
					</div>
				</NovaCard>

				<NovaCard variant="panel" contentClassName="p-3 md:p-4">
					<div className="mb-2 flex items-center justify-between gap-3">
						<div className="text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
							Current groups
						</div>
						<Button
							type="button"
							onClick={() => onFilterGroup("all")}
							variant="ghost"
							size="sm"
						>
							Show all
						</Button>
					</div>

					<div className="overflow-hidden rounded-lg border border-border bg-card">
						{groups.length === 0 ? (
							<NovaEmpty
								className="m-3 min-h-24"
								title="No groups yet"
								description="Create one here, or select accounts first to seed it."
							/>
						) : (
							groups.map((group) => {
								const count = accountCountByGroup.get(group.id) ?? 0;
								const isEditing = editingId === group.id;
								return (
									<div key={group.id}>
										<div className="px-3 py-2.5">
											{isEditing ? (
												<div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
													<div className="min-w-0">
														<Input
															value={editingName}
															onChange={(event) =>
																setEditingName(event.target.value)
															}
															maxLength={40}
															aria-label={`Edit group name for ${group.name}`}
															className="h-10 rounded-md px-2 md:h-8"
														/>
														<div className="mt-2">
															<ColorPicker
																value={editingColor}
																onChange={setEditingColor}
																compact
															/>
														</div>
													</div>
													<div className="flex items-center gap-1.5">
														<IconButton
															label="Save group"
															onClick={() => void submitEdit()}
														>
															<Check className="h-3.5 w-3.5" />
														</IconButton>
														<IconButton
															label="Cancel edit"
															onClick={() => setEditingId(null)}
														>
															<X className="h-3.5 w-3.5" />
														</IconButton>
													</div>
												</div>
											) : (
												<div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
													<Button
														type="button"
														onClick={() => onFilterGroup(group.id)}
														variant="ghost"
														className="min-w-0 justify-start gap-2.5 px-0 text-left hover:bg-transparent"
													>
														<span
															className="h-2.5 w-2.5 rounded-full shrink-0"
															style={{ backgroundColor: group.color }}
														/>
														<span className="min-w-0">
															<span className="block truncate text-[0.8125rem] font-semibold text-foreground">
																{group.name}
															</span>
															<span className="block text-[0.6875rem] text-muted-foreground tabular-nums">
																{count} account{count === 1 ? "" : "s"}
															</span>
														</span>
													</Button>
													<div className="flex items-center gap-1.5">
														{selectedRows.length > 0 && (
															<Button
																type="button"
																onClick={() =>
																	void onMoveSelectedToGroup(group)
																}
																variant="outline"
																size="sm"
															>
																Move selected
															</Button>
														)}
														<IconButton
															label={`Edit ${group.name}`}
															onClick={() => startEditing(group)}
														>
															<Edit3 className="h-3.5 w-3.5" />
														</IconButton>
														<IconButton
															label={`Delete ${group.name}`}
															destructive
															onClick={() => setDeleteTarget(group)}
														>
															<Trash2 className="h-3.5 w-3.5" />
														</IconButton>
													</div>
												</div>
											)}
										</div>
										<Separator />
									</div>
								);
							})
						)}
						{(unassignedCount > 0 || selectedRows.length > 0) && (
							<>
								{groups.length > 0 ? null : <Separator />}
								<div className="px-3 py-2.5 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
									<Button
										type="button"
										onClick={() => onFilterGroup("unassigned")}
										variant="ghost"
										className="min-w-0 justify-start gap-2.5 px-0 text-left hover:bg-transparent"
									>
										<span
											className="h-2.5 w-2.5 rounded-full shrink-0"
											style={{ backgroundColor: UNASSIGNED_COLOR }}
										/>
										<span>
											<span className="block text-[0.8125rem] font-semibold text-foreground">
												Unassigned
											</span>
											<span className="block text-[0.6875rem] text-muted-foreground tabular-nums">
												{unassignedCount} account
												{unassignedCount === 1 ? "" : "s"}
											</span>
										</span>
									</Button>
									{selectedRows.length > 0 && (
										<Button
											type="button"
											onClick={() => void onUnassignSelected()}
											variant="outline"
											size="sm"
										>
											Unassign selected
										</Button>
									)}
								</div>
							</>
						)}
					</div>
				</NovaCard>
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

function ColorPicker({
	value,
	onChange,
	compact = false,
}: {
	value: string;
	onChange: (value: string) => void;
	compact?: boolean | undefined;
}) {
	return (
		<div
			className={compact ? "flex flex-wrap gap-1" : "flex flex-wrap gap-1.5"}
			role="group"
			aria-label="Group color"
		>
			{GROUP_COLORS.map((hex) => (
				<Button
					key={hex}
					type="button"
					onClick={() => onChange(hex)}
					aria-label={`Use ${hex}`}
					variant="ghost"
					size="icon"
					className={`${compact ? "h-8 w-8 md:h-5 md:w-5" : "h-10 w-10 md:h-6 md:w-6"} rounded-full p-0`}
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

function IconButton({
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
			onClick={onClick}
			variant="ghost"
			size="icon"
			className="h-10 w-10 text-muted-foreground md:h-8 md:w-8"
			style={destructive ? { color: "var(--color-danger)" } : undefined}
		>
			{children}
		</Button>
	);
}
