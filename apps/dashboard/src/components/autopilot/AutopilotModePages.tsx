import type React from "react";
import { useMemo, useState } from "react";
import {
	AlertTriangle,
	ChevronRight,
	Clock,
	Lock,
	SlidersHorizontal,
} from "lucide-react";
import type { QueueHealthRow } from "@/services/autopilotService";
import type { AutoPostConfig, GroupConfig } from "@/services/autoPost";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { NovaDataPanel, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { groupColorFromId, groupLabelFromId } from "@/lib/groupPresentation";
import { cn } from "@/lib/utils";

type HealthTone = "good" | "warn" | "critical";

export function QueueModePage({
	rows,
	loading,
	error,
	onOpenCalendar,
}: {
	rows: QueueHealthRow[];
	loading: boolean;
	error: string | null;
	onOpenCalendar: () => void;
}) {
	return (
		<NovaDataPanel contentClassName="p-0">
			<div className="flex flex-col gap-3 border-b border-border px-5 py-4 md:flex-row md:items-center md:justify-between">
				<ModeSectionHeader
					eyebrow="Scheduled inventory"
					meta={
						loading
							? "loading"
							: error
								? "live read unavailable"
								: rows.length === 0
									? "no groups"
									: `${rows.length} group${rows.length === 1 ? "" : "s"} · live`
					}
					inline
				/>
				<Button
					type="button"
					variant="secondary"
					size="sm"
					onClick={onOpenCalendar}
					className="gap-1.5"
				>
					Open calendar
					<ChevronRight data-icon="inline-end" aria-hidden="true" />
				</Button>
			</div>
			{loading ? (
				<div className="divide-y divide-border">
					{Array.from({ length: 4 }).map((_, i) => (
						<QueueModeRowSkeleton key={i} />
					))}
				</div>
			) : error ? (
				<ModeInlineState
					icon={AlertTriangle}
					title="Publishing coverage unavailable"
					body="Automation could not load scheduled-post coverage. Existing posts are not being treated as missing."
				/>
			) : rows.length === 0 ? (
				<ModeInlineState
					icon={Clock}
					title="No scheduled posts"
					body="Schedule a post from Composer and this page will show publishing coverage by account group."
				/>
			) : (
				<div className="divide-y divide-border">
					{rows.map((row) => (
						<QueueModeRow key={row.network} row={row} />
					))}
				</div>
			)}
		</NovaDataPanel>
	);
}

export function ConditionsModePage({
	rows,
	configs,
	workspaceConfig,
	loading,
	error,
	savingKey,
	workspaceSavingKey,
	onUpdateConfig,
	onUpdateWorkspaceConfig,
}: {
	rows: QueueHealthRow[];
	configs: GroupConfig[];
	workspaceConfig: AutoPostConfig | null;
	loading: boolean;
	error: string | null;
	savingKey: string | null;
	workspaceSavingKey: string | null;
	onUpdateConfig: (
		groupId: string,
		patch: Partial<GroupConfig>,
	) => Promise<void>;
	onUpdateWorkspaceConfig: (patch: Partial<AutoPostConfig>) => Promise<void>;
}) {
	const configsByGroup = useMemo(
		() => new Map(configs.map((config) => [config.groupId, config])),
		[configs],
	);
	const displayRows = useMemo(() => {
		const rowsByGroup = new Map(rows.map((row) => [row.network, row]));
		for (const config of configs) {
			if (rowsByGroup.has(config.groupId)) continue;
			rowsByGroup.set(config.groupId, {
				network: config.groupId,
				networkLabel: groupLabelFromId(config.groupId),
				accountCount: 0,
				scheduledCount: 0,
				days: 0,
			});
		}
		return Array.from(rowsByGroup.values());
	}, [configs, rows]);
	const catalog = [
		{
			source: "FH",
			label: "Above-average performance window",
			status: "gated",
		},
		{ source: "FH", label: "Delay X min", status: "live" },
		{ source: "FH", label: "Reaches X likes", status: "gated" },
		{ source: "FH", label: "Reaches X impressions", status: "gated" },
		{ source: "FH", label: "Engagement rate >= X% after Ym", status: "gated" },
		{ source: "HF", label: "Auto-Plug if >= X likes", status: "gated" },
		{ source: "J33", label: "Account daily cap", status: "live" },
		{ source: "J33", label: "Crisis pause active", status: "read-only" },
		{ source: "J33", label: "Originality score >= X", status: "gated" },
	];

	return (
		<div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_280px] gap-5 items-start">
			<NovaDataPanel contentClassName="p-0">
				<div className="px-5 py-4 border-b border-border">
					<ModeSectionHeader
						eyebrow="Publishing rules"
						meta={
							loading
								? "loading"
								: error
									? "live read unavailable"
									: "derived from current schedule coverage"
						}
					/>
				</div>
				{loading ? (
					<div className="flex flex-col gap-3 p-5" aria-hidden="true">
						{Array.from({ length: 3 }).map((_, i) => (
							<Skeleton key={i} className="h-14 rounded-md" />
						))}
					</div>
				) : error ? (
					<ModeInlineState
						icon={AlertTriangle}
						title="Rules unavailable"
						body="Automation could not load group coverage, so schedule rules are hidden until the live read recovers."
					/>
				) : displayRows.length === 0 ? (
					<ModeInlineState
						icon={SlidersHorizontal}
						title="No group rules to show"
						body="When group automation settings exist, this page will show them as readable rules."
					/>
				) : (
					<div className="divide-y divide-border">
						<WorkspaceAutoUnpostRow
							config={workspaceConfig}
							savingKey={workspaceSavingKey}
							onUpdateConfig={onUpdateWorkspaceConfig}
						/>
						{displayRows.map((row) => (
							<ConditionGroupRow
								key={row.network}
								row={row}
								config={configsByGroup.get(row.network) ?? null}
								savingKey={savingKey}
								onUpdateConfig={onUpdateConfig}
							/>
						))}
					</div>
				)}
			</NovaDataPanel>
			<NovaDataPanel contentClassName="p-4">
				<ModeSectionHeader eyebrow="Rule library" meta="available signals" />
				<div className="mt-3 flex flex-col gap-2">
					{catalog.map((item) => (
						<div
							key={`${item.source}-${item.label}`}
							className="flex items-center gap-2 rounded-md bg-muted/50 border border-border px-3 py-2"
						>
							<Badge tone="outline">{item.source}</Badge>
							<span className="min-w-0 flex-1 text-[0.71875rem] text-muted-foreground">
								{item.label}
							</span>
							<span className="text-[0.5625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
								{item.status}
							</span>
						</div>
					))}
				</div>
			</NovaDataPanel>
		</div>
	);
}

function WorkspaceAutoUnpostRow({
	config,
	savingKey,
	onUpdateConfig,
}: {
	config: AutoPostConfig | null;
	savingKey: string | null;
	onUpdateConfig: (patch: Partial<AutoPostConfig>) => Promise<void>;
}) {
	const enabled = !!config;
	return (
		<article className="px-5 py-4">
			<div className="grid grid-cols-1 xl:grid-cols-[minmax(180px,0.7fr)_minmax(0,1.6fr)] gap-4">
				<div className="min-w-0">
					<h3 className="text-[0.875rem] font-medium text-foreground truncate">
						Duplicate cleanup
					</h3>
					<div className="mt-1 text-[0.6875rem] text-muted-foreground">
						Keep the strongest post when a same-platform group creates duplicates.
					</div>
				</div>
				<div className="flex flex-wrap gap-2 items-start">
					<EditableConditionPill
						groupId="workspace"
						enabled={enabled}
						label="Auto-unpost duplicates"
						value={config?.autoUnpostDuplicates ? "on" : "off"}
						source="HF"
						tone={config?.autoUnpostDuplicates ? "critical" : "neutral"}
						saving={savingKey === "autoUnpostDuplicates"}
						edit={{
							kind: "boolean",
							current: Boolean(config?.autoUnpostDuplicates),
							trueLabel: "on",
							falseLabel: "off",
							onCommit: (autoUnpostDuplicates) =>
								onUpdateConfig({ autoUnpostDuplicates }),
						}}
					/>
					<EditableConditionPill
						groupId="workspace"
						enabled={enabled}
						label="After"
						value={`${config?.autoUnpostWindowHours ?? 6}h`}
						source="HF"
						tone="neutral"
						saving={savingKey === "autoUnpostWindowHours"}
						edit={{
							kind: "number",
							current: config?.autoUnpostWindowHours ?? 6,
							min: 1,
							max: 168,
							step: 1,
							suffix: "hours",
							onCommit: (autoUnpostWindowHours) =>
								onUpdateConfig({ autoUnpostWindowHours }),
						}}
					/>
					<EditableConditionPill
						groupId="workspace"
						enabled={enabled}
						label="Keep top"
						value={`${config?.autoUnpostKeepTop ?? 1} performers`}
						source="HF"
						tone="neutral"
						saving={savingKey === "autoUnpostKeepTop"}
						edit={{
							kind: "number",
							current: config?.autoUnpostKeepTop ?? 1,
							min: 1,
							max: 10,
							step: 1,
							suffix: "posts",
							onCommit: (autoUnpostKeepTop) =>
								onUpdateConfig({ autoUnpostKeepTop }),
						}}
					/>
				</div>
			</div>
		</article>
	);
}

function ConditionGroupRow({
	row,
	config,
	savingKey,
	onUpdateConfig,
}: {
	row: QueueHealthRow;
	config: GroupConfig | null;
	savingKey: string | null;
	onUpdateConfig: (
		groupId: string,
		patch: Partial<GroupConfig>,
	) => Promise<void>;
}) {
	const label = networkLabelOf(row.network, row.networkLabel);
	const editable = !!config;
	const coverageTone =
		row.days >= 4 ? "good" : row.days >= 2 ? "warn" : "critical";

	return (
		<article className="px-5 py-4">
			<div className="grid grid-cols-1 xl:grid-cols-[minmax(180px,0.7fr)_minmax(0,1.6fr)] gap-4">
				<div className="min-w-0">
					<h3 className="text-[0.875rem] font-medium text-foreground truncate">
						{label}
					</h3>
					<div className="mt-1 text-[0.6875rem] text-muted-foreground tabular-nums">
						{row.accountCount} account{row.accountCount === 1 ? "" : "s"} ·{" "}
						{row.scheduledCount} scheduled · {row.days.toFixed(1)}d coverage
					</div>
					{!editable && (
						<div className="mt-2 text-[0.6875rem] leading-[1.4] text-muted-foreground">
							No editable group config row exists yet.
						</div>
					)}
				</div>
				<div className="flex flex-wrap gap-2 items-start">
					<EditableConditionPill
						groupId={row.network}
						enabled={editable}
						label="Posting"
						value={config?.enabled ? "on" : "paused"}
						source="J33"
						tone={config?.enabled ? "good" : "warn"}
						saving={savingKey === conditionSavingKey(row.network, ["enabled"])}
						edit={{
							kind: "boolean",
							current: config?.enabled ?? false,
							onCommit: (enabled) => onUpdateConfig(row.network, { enabled }),
						}}
					/>
					<EditableConditionPill
						groupId={row.network}
						enabled={editable}
						label="Account daily cap"
						value={`<= ${config?.postsPerAccountPerDay ?? 4} posts`}
						source="J33"
						tone="neutral"
						saving={
							savingKey ===
							conditionSavingKey(row.network, ["postsPerAccountPerDay"])
						}
						edit={{
							kind: "number",
							min: 1,
							max: 20,
							step: 1,
							current: config?.postsPerAccountPerDay ?? 4,
							suffix: "posts",
							onCommit: (postsPerAccountPerDay) =>
								onUpdateConfig(row.network, { postsPerAccountPerDay }),
						}}
					/>
					<EditableConditionPill
						groupId={row.network}
						enabled={editable}
						label="Delay"
						value={`>= ${config?.minIntervalMinutes ?? 90} min`}
						source="FH"
						tone="neutral"
						saving={
							savingKey ===
							conditionSavingKey(row.network, ["minIntervalMinutes"])
						}
						edit={{
							kind: "number",
							min: 5,
							max: 360,
							step: 5,
							current: config?.minIntervalMinutes ?? 90,
							suffix: "min",
							onCommit: (minIntervalMinutes) =>
								onUpdateConfig(row.network, { minIntervalMinutes }),
						}}
					/>
					<ActiveWindowPill
						groupId={row.network}
						config={config}
						saving={
							savingKey ===
							conditionSavingKey(row.network, [
								"activeHoursStart",
								"activeHoursEnd",
							])
						}
						onUpdateConfig={onUpdateConfig}
					/>
					<EditableConditionPill
						groupId={row.network}
						enabled={editable}
						label="Weekends"
						value={config?.postOnWeekends ? "allowed" : "blocked"}
						source="J33"
						tone={config?.postOnWeekends ? "neutral" : "warn"}
						saving={
							savingKey === conditionSavingKey(row.network, ["postOnWeekends"])
						}
						edit={{
							kind: "boolean",
							current: config?.postOnWeekends ?? true,
							trueLabel: "allowed",
							falseLabel: "blocked",
							onCommit: (postOnWeekends) =>
								onUpdateConfig(row.network, { postOnWeekends }),
						}}
					/>
					<ConditionPill
						label="Coverage target"
						value=">= 4d"
						source="J33"
						tone={coverageTone}
					/>
					<ConditionPill
						label="Crisis pause"
						value="inactive"
						source="J33"
						tone="neutral"
					/>
					<EditableConditionPill
						groupId={row.network}
						enabled={editable}
						label="Auto-unpost"
						value={config?.autoUnpostOptOut ? "opted out" : "eligible"}
						source="HF"
						tone={config?.autoUnpostOptOut ? "warn" : "neutral"}
						saving={
							savingKey ===
							conditionSavingKey(row.network, ["autoUnpostOptOut"])
						}
						edit={{
							kind: "boolean",
							current: !(config?.autoUnpostOptOut ?? false),
							trueLabel: "eligible",
							falseLabel: "opt out",
							onCommit: (eligible) =>
								onUpdateConfig(row.network, { autoUnpostOptOut: !eligible }),
						}}
					/>
				</div>
			</div>
		</article>
	);
}

type PillTone = "good" | "warn" | "critical" | "neutral";

type EditablePillConfig =
	| {
			kind: "number";
			current: number;
			min: number;
			max: number;
			step: number;
			suffix: string;
			onCommit: (value: number) => Promise<void>;
	  }
	| {
			kind: "boolean";
			current: boolean;
			trueLabel?: string | undefined;
			falseLabel?: string | undefined;
			onCommit: (value: boolean) => Promise<void>;
	  };

function EditableConditionPill({
	groupId,
	enabled,
	label,
	value,
	source,
	tone = "neutral",
	saving,
	edit,
}: {
	groupId: string;
	enabled: boolean;
	label: string;
	value: string;
	source: string;
	tone?: PillTone | undefined;
	saving: boolean;
	edit: EditablePillConfig;
}) {
	const [open, setOpen] = useState(false);
	const [draftNumber, setDraftNumber] = useState(
		edit.kind === "number" ? edit.current : 0,
	);
	const [localError, setLocalError] = useState<string | null>(null);

	const commitNumber = async () => {
		if (edit.kind !== "number") return;
		const next = Math.max(
			edit.min,
			Math.min(edit.max, Math.round(draftNumber / edit.step) * edit.step),
		);
		setLocalError(null);
		try {
			await edit.onCommit(next);
			setOpen(false);
		} catch (e) {
			setLocalError(e instanceof Error ? e.message : "Could not save.");
		}
	};

	const commitBoolean = async (next: boolean) => {
		if (edit.kind !== "boolean") return;
		setLocalError(null);
		try {
			await edit.onCommit(next);
			setOpen(false);
		} catch (e) {
			setLocalError(e instanceof Error ? e.message : "Could not save.");
		}
	};

	return (
		<div className="relative">
			<Button
				type="button"
				variant="ghost"
				size="sm"
				onClick={() => {
					if (!enabled) return;
					if (edit.kind === "number") setDraftNumber(edit.current);
					setOpen((v) => !v);
				}}
				disabled={!enabled || saving}
				className="h-auto justify-start rounded-md p-0 text-left disabled:cursor-not-allowed"
			>
				<ConditionPill
					label={label}
					value={saving ? "saving..." : value}
					source={source}
					tone={tone}
				/>
			</Button>
			{open && enabled && (
				<div className="absolute z-20 mt-2 w-56 rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-[var(--shadow-modal)]">
					<div className="text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
						{label}
					</div>
					{edit.kind === "number" ? (
						<>
							<div className="mt-2 flex items-center gap-2">
								<Input
									type="number"
									min={edit.min}
									max={edit.max}
									step={edit.step}
									value={draftNumber}
									onChange={(e) => setDraftNumber(Number(e.target.value))}
									sizeVariant="sm"
									className="min-w-0 flex-1 px-2"
								/>
								<span className="text-[0.6875rem] text-muted-foreground">
									{edit.suffix}
								</span>
							</div>
							<div className="mt-3 flex justify-end gap-2">
								<PillEditorButton
									label="Cancel"
									onClick={() => setOpen(false)}
								/>
								<PillEditorButton
									label={saving ? "Saving" : "Save"}
									onClick={() => void commitNumber()}
									strong
								/>
							</div>
						</>
					) : (
						<div className="mt-3 grid grid-cols-2 gap-2">
							<PillEditorButton
								label={edit.trueLabel ?? "On"}
								onClick={() => void commitBoolean(true)}
								strong={edit.current === true}
							/>
							<PillEditorButton
								label={edit.falseLabel ?? "Off"}
								onClick={() => void commitBoolean(false)}
								strong={edit.current === false}
							/>
						</div>
					)}
					{localError && (
						<div className="mt-2 text-[0.65625rem] leading-[1.35] text-[var(--color-oxblood)]">
							{localError}
						</div>
					)}
					<div className="sr-only">{groupId}</div>
				</div>
			)}
		</div>
	);
}

function ActiveWindowPill({
	groupId,
	config,
	saving,
	onUpdateConfig,
}: {
	groupId: string;
	config: GroupConfig | null;
	saving: boolean;
	onUpdateConfig: (
		groupId: string,
		patch: Partial<GroupConfig>,
	) => Promise<void>;
}) {
	const [open, setOpen] = useState(false);
	const [start, setStart] = useState(config?.activeHoursStart ?? 8);
	const [end, setEnd] = useState(config?.activeHoursEnd ?? 22);
	const [localError, setLocalError] = useState<string | null>(null);
	const enabled = !!config;

	const commit = async () => {
		const nextStart = Math.max(0, Math.min(23, Math.round(start)));
		const nextEnd = Math.max(0, Math.min(24, Math.round(end)));
		setLocalError(null);
		try {
			await onUpdateConfig(groupId, {
				activeHoursStart: nextStart,
				activeHoursEnd: nextEnd,
			});
			setOpen(false);
		} catch (e) {
			setLocalError(e instanceof Error ? e.message : "Could not save.");
		}
	};

	return (
		<div className="relative">
			<Button
				type="button"
				variant="ghost"
				size="sm"
				disabled={!enabled || saving}
				onClick={() => {
					if (!config) return;
					setStart(config.activeHoursStart);
					setEnd(config.activeHoursEnd);
					setOpen((v) => !v);
				}}
				className="h-auto justify-start rounded-md p-0 text-left disabled:cursor-not-allowed"
			>
				<ConditionPill
					label="Active window"
					value={
						saving
							? "saving..."
							: formatHourWindow(
									config?.activeHoursStart ?? 8,
									config?.activeHoursEnd ?? 22,
								)
					}
					source="FH"
					tone="neutral"
				/>
			</Button>
			{open && enabled && (
				<div className="absolute z-20 mt-2 w-60 rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-[var(--shadow-modal)]">
					<div className="text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
						Active window
					</div>
					<div className="mt-2 grid grid-cols-2 gap-2">
						<label
							htmlFor="autopilot-active-window-start"
							className="text-[0.65625rem] text-muted-foreground"
						>
							Start
							<Input
								id="autopilot-active-window-start"
								type="number"
								min={0}
								max={23}
								value={start}
								onChange={(e) => setStart(Number(e.target.value))}
								sizeVariant="sm"
								className="mt-1 px-2"
							/>
						</label>
						<label
							htmlFor="autopilot-active-window-end"
							className="text-[0.65625rem] text-muted-foreground"
						>
							End
							<Input
								id="autopilot-active-window-end"
								type="number"
								min={0}
								max={24}
								value={end}
								onChange={(e) => setEnd(Number(e.target.value))}
								sizeVariant="sm"
								className="mt-1 px-2"
							/>
						</label>
					</div>
					<div className="mt-3 flex justify-end gap-2">
						<PillEditorButton label="Cancel" onClick={() => setOpen(false)} />
						<PillEditorButton
							label={saving ? "Saving" : "Save"}
							onClick={() => void commit()}
							strong
						/>
					</div>
					{localError && (
						<div className="mt-2 text-[0.65625rem] leading-[1.35] text-[var(--color-oxblood)]">
							{localError}
						</div>
					)}
				</div>
			)}
		</div>
	);
}

function PillEditorButton({
	label,
	onClick,
	strong,
}: {
	label: string;
	onClick: () => void;
	strong?: boolean | undefined;
}) {
	return (
		<Button
			type="button"
			onClick={onClick}
			variant={strong ? "default" : "secondary"}
			size="sm"
			className={cn("h-8 px-2.5 text-[0.71875rem]")}
		>
			{label}
		</Button>
	);
}

function conditionSavingKey(groupId: string, keys: string[]) {
	return `${groupId}:${keys.sort().join(",")}`;
}

function formatHourWindow(start: number, end: number) {
	const fmt = (hour: number) => `${String(hour).padStart(2, "0")}:00`;
	return `${fmt(start)}-${fmt(end === 24 ? 0 : end)}`;
}

export function SchemaGatedMode({
	icon: Icon,
	title,
	body,
	rows,
}: {
	icon: React.ComponentType<{ className?: string | undefined }>;
	title: string;
	body: string;
	rows: string[];
}) {
	return (
		<NovaDataPanel contentClassName="p-6">
			<div className="flex flex-col md:flex-row gap-4 md:items-start">
				<div className="size-11 rounded-md bg-muted border border-border inline-flex items-center justify-center shrink-0">
					<Icon data-icon="inline" className="text-muted-foreground" aria-hidden="true" />
				</div>
				<div className="min-w-0">
					<div className="inline-flex items-center gap-1.5 rounded-md bg-muted border border-border px-2 py-1 text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
						<Lock data-icon="inline-start" aria-hidden="true" />
						Backend gated
					</div>
					<h3 className="mt-3 text-[1.125rem] font-medium tracking-[-0.02em] text-foreground">
						{title}
					</h3>
					<p className="mt-2 max-w-[72ch] text-[0.78125rem] leading-[1.55] text-muted-foreground">
						{body}
					</p>
					<div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
						{rows.map((row) => (
							<div
								key={row}
								className="rounded-md bg-muted/50 border border-border px-3 py-3 text-[0.71875rem] leading-[1.45] text-muted-foreground"
							>
								{row}
							</div>
						))}
					</div>
				</div>
			</div>
		</NovaDataPanel>
	);
}

function QueueModeRow({ row }: { row: QueueHealthRow }) {
	const dayTarget = Math.max(1, row.accountCount);
	const capMet = Math.max(
		0,
		Math.min(100, (row.scheduledCount / Math.max(1, dayTarget)) * 100),
	);
	const status =
		row.days < 2 ? "Needs plan" : row.days < 4 ? "Planned" : "Ready";
	const statusTone = row.days < 2 ? "critical" : row.days < 4 ? "warn" : "good";
	const label = networkLabelOf(row.network, row.networkLabel);

	return (
		<article className="px-5 py-4 grid grid-cols-1 lg:grid-cols-[64px_1fr_1.35fr_auto] gap-4 items-center hover:bg-muted/40 transition-colors">
			<RingAvatar label={label} pct={capMet} network={row.network} />
			<div className="min-w-0">
				<div className="flex items-center gap-2 min-w-0">
					<h3 className="text-[0.875rem] font-medium text-foreground truncate">
						{label}
					</h3>
					<span className="text-[0.625rem] uppercase tracking-[0.08em] text-muted-foreground">
						group
					</span>
				</div>
				<div className="mt-1 text-[0.71875rem] text-muted-foreground tabular-nums">
					<strong className="font-medium text-foreground">
						{row.scheduledCount}
					</strong>{" "}
					scheduled · {row.accountCount} account
					{row.accountCount === 1 ? "" : "s"} · {row.days.toFixed(1)}d coverage
				</div>
			</div>
			<div className="text-[0.78125rem] leading-[1.45] text-muted-foreground">
				<ContentSourceTag source={row.days >= 4 ? "Auto" : "Manual"} />
				{row.days >= 4
					? "Inventory is above the safety floor and ready for scheduled publishing."
					: "Coverage is below the target floor; add posts or review this group plan."}
			</div>
			<StatusBadge label={status} tone={statusTone} />
		</article>
	);
}

function QueueModeRowSkeleton() {
	return (
		<div
			className="px-5 py-4 grid grid-cols-[64px_1fr] gap-4 items-center"
			aria-hidden="true"
		>
			<Skeleton className="size-12 rounded-full" />
			<div className="flex flex-col gap-2">
				<Skeleton className="h-4 w-44 rounded-md" />
				<Skeleton className="h-3 w-72 max-w-full rounded-md" />
				<Skeleton className="h-3 w-[80%] rounded-md" />
			</div>
		</div>
	);
}

function RingAvatar({
	label,
	pct,
	network,
}: {
	label: string;
	pct: number;
	network: string;
}) {
	const initials = label
		.split(/\s+/)
		.map((part) => part[0])
		.join("")
		.slice(0, 2)
		.toUpperCase();
	const ringColor =
		pct >= 100
			? "var(--color-health-good)"
			: pct >= 60
				? "var(--color-health-warn)"
				: "var(--color-oxblood)";
	return (
		<div
			className="relative w-12 h-12 rounded-full grid place-items-center"
			style={{
				background: `conic-gradient(${ringColor} ${pct}%, var(--color-border) 0)`,
			}}
			role="img"
			aria-label={`${Math.round(pct)} percent of daily cap queued`}
		>
			<div
				className="w-10 h-10 rounded-full grid place-items-center text-[0.75rem] font-semibold text-white border-2 border-background"
				style={{ background: networkColorOf(network) }}
				aria-hidden="true"
			>
				{initials || "A"}
			</div>
			<span className="absolute -bottom-1 -right-1 min-w-7 h-4 px-1 rounded-[5px] bg-background border border-border text-[0.5625rem] font-semibold tabular-nums text-foreground grid place-items-center">
				{Math.round(pct)}%
			</span>
		</div>
	);
}

function ContentSourceTag({ source }: { source: "Auto" | "Manual" }) {
	return (
		<span
			className={cn(
				"mr-2 inline-flex items-center rounded-[4px] px-1.5 py-0.5 text-[0.5625rem] font-bold uppercase tracking-[0.08em]",
				source === "Auto"
					? "text-[var(--color-oxblood)] bg-[color-mix(in_srgb,var(--color-oxblood)_12%,transparent)]"
					: "text-muted-foreground bg-muted border border-border",
			)}
		>
			{source}
		</span>
	);
}

function StatusBadge({ label, tone }: { label: string; tone: HealthTone }) {
	const color =
		tone === "good"
			? "var(--color-health-good)"
			: tone === "warn"
				? "var(--color-health-warn)"
				: "var(--color-oxblood)";
	return (
		<span
			className="justify-self-start lg:justify-self-end rounded-md px-2.5 py-1 text-[0.625rem] font-semibold uppercase tracking-[0.08em] tabular-nums"
			style={{
				color,
				background: "color-mix(in srgb, currentColor 10%, transparent)",
			}}
		>
			{label}
		</span>
	);
}

function ConditionPill({
	label,
	value,
	source,
	tone = "neutral",
}: {
	label: string;
	value: string;
	source: string;
	tone?: PillTone | undefined;
}) {
	const color =
		tone === "good"
			? "var(--color-health-good)"
			: tone === "critical"
				? "var(--color-oxblood)"
				: tone === "warn"
					? "var(--color-health-warn)"
					: "var(--color-muted-foreground)";
	return (
		<span className="inline-flex items-center gap-1.5 rounded-md bg-muted border border-border px-2 py-1 text-[0.6875rem] font-medium text-muted-foreground">
			<span className="text-[0.5625rem] font-bold uppercase tracking-[0.08em] text-muted-foreground">
				{source}
			</span>
			<span>{label}</span>
			<span className="tabular-nums" style={{ color }}>
				{value}
			</span>
		</span>
	);
}

function ModeInlineState({
	icon: Icon,
	title,
	body,
}: {
	icon: React.ComponentType<{ className?: string | undefined }>;
	title: string;
	body: string;
}) {
	return (
		<NovaEmpty
			className="px-5 py-12"
			icon={<Icon data-icon="inline" className="text-muted-foreground" aria-hidden="true" />}
			title={title}
			description={body}
		/>
	);
}

function ModeSectionHeader({
	eyebrow,
	meta,
	action,
	inline,
}: {
	eyebrow: string;
	meta?: string | undefined;
	action?: React.ReactNode | undefined;
	inline?: boolean | undefined;
}) {
	return (
		<div
			className={cn(
				"flex items-baseline gap-3",
				inline ? "flex-1" : "justify-between",
			)}
		>
			<div className="flex items-baseline gap-2 min-w-0">
				<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
					{eyebrow}
				</span>
				{meta && (
					<span className="text-[0.65625rem] text-muted-foreground tabular-nums truncate">
						{meta}
					</span>
				)}
			</div>
			{action}
		</div>
	);
}

function networkLabelOf(network: string, fallback?: string): string {
	return groupLabelFromId(network, fallback);
}

function networkColorOf(network: string): string {
	return groupColorFromId(network);
}
