import { Check, FileText, Search, X } from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import {
	avatarGradient,
	type MediaItem,
} from "@/components/composer/PreviewSection";
import { Button } from "@/components/ui/Button";
import { IconTooltipButton } from "@/components/ui/IconTooltipButton";
import { Input } from "@/components/ui/Input";
import {
	PopoverContent,
	PopoverRoot,
	PopoverTrigger,
} from "@/components/ui/Popover";
import { Sheet } from "@/components/ui/Sheet";
import type { AccountGroup } from "@/hooks/useAccountGroups";
import type { ConnectedAccount } from "@/hooks/useConnectedAccounts";
import { shortLabelFor } from "@/lib/socialPlatform";
import { cn } from "@/lib/utils";

/**
 * Hook: matches `(max-width: 767px)` so desktop gets an anchored popover and
 * phones get a bottom sheet (CLAUDE.md mobile spec: "layered picker sheet").
 */
function useIsMobile(): boolean {
	const [isMobile, setIsMobile] = useState(
		() =>
			typeof window !== "undefined" &&
			window.matchMedia("(max-width: 767px)").matches,
	);
	useEffect(() => {
		if (typeof window === "undefined") return;
		const mql = window.matchMedia("(max-width: 767px)");
		const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches);
		mql.addEventListener("change", onChange);
		return () => mql.removeEventListener("change", onChange);
	}, []);
	return isMobile;
}

function cloneMobileTrigger(
	trigger: React.ReactElement,
	onOpenChange: (open: boolean) => void,
	open: boolean,
) {
	return React.cloneElement(
		trigger as React.ReactElement<{
			onClick?: (e: React.MouseEvent) => void;
		}>,
		{
			onClick: (e: React.MouseEvent) => {
				(
					trigger.props as {
						onClick?: (e: React.MouseEvent) => void;
					}
				).onClick?.(e);
				onOpenChange(!open);
			},
		},
	);
}

function MobilePopoverSheet({
	open,
	onOpenChange,
	trigger,
	ariaLabel,
	children,
	panelClassName,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	trigger: React.ReactElement;
	ariaLabel: string;
	children: React.ReactNode;
	panelClassName?: string | undefined;
}) {
	return (
		<>
			{cloneMobileTrigger(trigger, onOpenChange, open)}
			<Sheet
				open={open}
				onClose={() => onOpenChange(false)}
				ariaLabel={ariaLabel}
				side="bottom"
				widthClass="w-full md:hidden"
				hideCloseButton
				panelClassName={cn("max-h-[85vh] overflow-hidden", panelClassName)}
			>
				{children}
			</Sheet>
		</>
	);
}

/* =========================================================================
   Account + group + drafts selection surfaces for the Composer.
   Includes:
     - AccountChip — target chip with network dot + remove
     - AccountPickerPopover — search + group-filter list (desktop popover
       / mobile bottom sheet) for adding/removing targets
     - GroupPopover — saved group presets + inline "Create group" flow
     - DraftsPopover — list of saved drafts with load / delete actions
   All state owned here is popover-internal (search query, filter, creating).
   Target selection, active group, and draft persistence live in the parent.
   ========================================================================= */

type Account = ConnectedAccount;

export const UNASSIGNED_COLOR = "#6B6B70";

export interface GroupPreset {
	id: string;
	label: string;
	description: string;
	color: string;
	accountIds: string[];
}

/** Shape of a saved draft, surfaced by DraftsPopover. */
export interface DraftSummary {
	id: string;
	updatedAt: number;
	caption: string;
	targetIds: string[];
	media: MediaItem[];
	pollEnabled: boolean;
	pollOptions: string[];
	trialReel: boolean;
	threadChain: boolean;
	ghostPost: boolean;
	ghostDuration: "24h" | "48h" | "7d";
}

function formatDraftTime(ts: number): string {
	const mins = Math.round((Date.now() - ts) / 60000);
	if (mins < 1) return "just now";
	if (mins < 60) return `${mins}m ago`;
	const hrs = Math.round(mins / 60);
	if (hrs < 24) return `${hrs}h ago`;
	const days = Math.round(hrs / 24);
	return `${days}d ago`;
}

export function AccountChip({
	account,
	onRemove,
}: {
	account: Account;
	onRemove: () => void;
}) {
	const { from, to, initial } = avatarGradient(account.handle);
	const chipColor = account.groupId ? account.groupColor : UNASSIGNED_COLOR;
	return (
		<span className="inline-flex items-center gap-1.5 h-7 pl-1 pr-1.5 rounded-full bg-[color-mix(in_srgb,var(--color-foreground)_4%,transparent)] dark:bg-[color-mix(in_srgb,var(--color-foreground)_5%,transparent)] border border-border">
			<span
				className="w-5 h-5 rounded-full inline-flex items-center justify-center text-[0.59375rem] font-semibold text-white shrink-0"
				style={{ background: `linear-gradient(135deg, ${from}, ${to})` }}
				aria-hidden="true"
			>
				{initial}
			</span>
			<span className="text-[0.71875rem] font-medium text-foreground max-w-[140px] truncate">
				{account.handle}
			</span>
			<span
				className="w-1 h-1 rounded-full"
				style={{ background: chipColor }}
				aria-hidden="true"
			/>
			<Button
				type="button"
				variant="ghost"
				onClick={onRemove}
				aria-label={`Remove ${account.handle}`}
				className="h-4 w-4 rounded-full p-0 text-muted-foreground hover:text-[color:var(--color-oxblood)]"
			>
				<X className="w-2.5 h-2.5" aria-hidden="true" />
			</Button>
		</span>
	);
}

export function AccountPickerPopover({
	open,
	onOpenChange,
	trigger,
	selectedIds,
	accounts,
	onToggle,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	trigger: React.ReactElement;
	selectedIds: string[];
	accounts: ConnectedAccount[];
	onToggle: (id: string) => void;
}) {
	const [query, setQuery] = useState("");
	const [groupFilter, setGroupFilter] = useState<string>("all");
	const isMobile = useIsMobile();

	// Derive the chip strip filter options from the real groups present in the
	// operator's roster. Platform stays as a secondary badge on each row.
	const groupFilterOptions = useMemo(() => {
		const seen = new Map<
			string,
			{ key: string; label: string; color: string }
		>();
		for (const a of accounts) {
			const key = a.groupId ?? "__unassigned";
			if (seen.has(key)) continue;
			seen.set(key, {
				key,
				label: a.groupId ? a.groupName : "Unassigned",
				color: a.groupId ? a.groupColor : UNASSIGNED_COLOR,
			});
		}
		return Array.from(seen.values()).sort((a, b) =>
			a.label.localeCompare(b.label),
		);
	}, [accounts]);

	const filtered = useMemo(() => {
		const q = query.trim().toLowerCase();
		return accounts
			.filter((a) => {
				if (groupFilter !== "all") {
					const key = a.groupId ?? "__unassigned";
					if (key !== groupFilter) return false;
				}
				if (
					q &&
					!a.handle.toLowerCase().includes(q) &&
					!a.displayName.toLowerCase().includes(q)
				)
					return false;
				return true;
			})
			.slice(0, 80);
	}, [accounts, query, groupFilter]);

	if (typeof document === "undefined") return null;

	const body = (
		<>
			<div className="p-2.5 flex items-center gap-1.5 border-b border-border">
				<Input
					type="search"
					placeholder="Search accounts"
					value={query}
					onChange={(event) => setQuery(event.target.value)}
					leadingIcon={<Search className="h-3.5 w-3.5" />}
					sizeVariant="sm"
				/>
			</div>

			{groupFilterOptions.length > 0 && (
				<div className="px-2.5 py-1.5 flex items-center gap-1 border-b border-border overflow-x-auto hide-scrollbar">
					<Button
						type="button"
						variant={groupFilter === "all" ? "secondary" : "ghost"}
						size="sm"
						onClick={() => setGroupFilter("all")}
						className="h-6 whitespace-nowrap rounded-full px-2 text-[0.65625rem]"
					>
						All
					</Button>
					{groupFilterOptions.map((opt) => {
						const active = groupFilter === opt.key;
						return (
							<Button
								key={opt.key}
								type="button"
								variant={active ? "secondary" : "ghost"}
								size="sm"
								onClick={() => setGroupFilter(opt.key)}
								className="h-6 gap-1 whitespace-nowrap rounded-full px-2 text-[0.65625rem]"
							>
								<span
									className="w-1.5 h-1.5 rounded-full"
									style={{ background: opt.color }}
									aria-hidden="true"
								/>
								{opt.label}
							</Button>
						);
					})}
				</div>
			)}

			<div
				className={cn(
					"overflow-y-auto p-1",
					isMobile ? "flex-1 min-h-0" : "max-h-[320px]",
				)}
			>
				{accounts.length === 0 ? (
					<div className="p-6 text-center">
						<div className="text-[0.75rem] font-medium text-foreground">
							No accounts connected
						</div>
						<div className="mt-1 text-[0.65625rem] text-muted-foreground">
							Connect accounts during onboarding to publish from the composer.
						</div>
					</div>
				) : filtered.length === 0 ? (
					<div className="p-6 text-center text-[0.71875rem] text-muted-foreground">
						No accounts match.
					</div>
				) : (
					filtered.map((a) => {
						const selected = selectedIds.includes(a.id);
						const { from, to, initial } = avatarGradient(a.handle);
						const dotColor = a.groupId ? a.groupColor : UNASSIGNED_COLOR;
						return (
							<Button
								key={a.id}
								type="button"
								variant="ghost"
								onClick={() => onToggle(a.id)}
								className={cn(
									"h-auto w-full justify-start gap-2.5 px-2.5 py-2 text-left",
									selected
										? "bg-[color-mix(in_srgb,var(--color-oxblood)_10%,transparent)]"
										: "hover:bg-muted",
								)}
							>
								<span
									className="w-7 h-7 rounded-full inline-flex items-center justify-center text-[0.6875rem] font-semibold text-white shrink-0"
									style={{
										background: `linear-gradient(135deg, ${from}, ${to})`,
									}}
									aria-hidden="true"
								>
									{initial}
								</span>
								<div className="flex-1 min-w-0">
									<div className="flex items-center gap-1.5 min-w-0">
										<span className="text-[0.78125rem] font-medium text-foreground truncate">
											{a.handle}
										</span>
										<span
											className="w-1 h-1 rounded-full shrink-0"
											style={{ background: dotColor }}
											aria-hidden="true"
										/>
										<span className="text-[0.625rem] text-muted-foreground capitalize shrink-0">
											{shortLabelFor(a.platform)}
										</span>
									</div>
									<div className="text-[0.65625rem] text-muted-foreground tabular-nums mt-0.5 truncate">
										{a.displayName}
										{a.groupId && (
											<>
												{" · "}
												{a.groupName}
											</>
										)}
									</div>
								</div>
								<div
									className={cn(
										"w-4 h-4 rounded-sm border inline-flex items-center justify-center shrink-0 transition-colors",
										selected
											? "border-transparent"
											: "border-[color-mix(in_srgb,var(--color-foreground)_20%,transparent)]",
									)}
									style={
										selected
											? { background: "var(--color-oxblood)" }
											: undefined
									}
								>
									{selected && (
										<Check className="w-3 h-3 text-white" aria-hidden="true" />
									)}
								</div>
							</Button>
						);
					})
				)}
			</div>

			<div className="p-2 border-t border-border flex items-center justify-between text-[0.65625rem] text-muted-foreground">
				<span className="tabular-nums">
					{selectedIds.length} selected · {filtered.length} shown
				</span>
				<Button
					type="button"
					onClick={() => onOpenChange(false)}
					variant="ghost"
					size="sm"
					className="h-7 px-2"
				>
					Done
				</Button>
			</div>
		</>
	);

	// Mobile: render trigger inline + bottom-sheet in portal. The trigger's
	// own onClick is replaced so parent state plumbing isn't needed — we
	// fully own open/close via onOpenChange. Desktop: Radix Popover handles
	// anchoring, focus, dismiss, and portaling.
	if (isMobile) {
		return (
			<MobilePopoverSheet
				open={open}
				onOpenChange={onOpenChange}
				trigger={trigger}
				ariaLabel="Choose accounts"
			>
				{body}
			</MobilePopoverSheet>
		);
	}

	return (
		<PopoverRoot open={open} onOpenChange={onOpenChange}>
			<PopoverTrigger asChild>{trigger}</PopoverTrigger>
			<PopoverContent
				side="bottom"
				align="start"
				sideOffset={6}
				className="w-[380px] p-0 rounded-xl overflow-hidden"
			>
				{body}
			</PopoverContent>
		</PopoverRoot>
	);
}

export function DraftsPopover({
	open,
	onOpenChange,
	trigger,
	drafts,
	currentDraftId,
	onLoad,
	onDelete,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	trigger: React.ReactNode;
	drafts: DraftSummary[];
	currentDraftId: string | null;
	onLoad: (id: string) => void;
	onDelete: (id: string) => void;
}) {
	const sorted = useMemo(
		() => [...drafts].sort((a, b) => b.updatedAt - a.updatedAt),
		[drafts],
	);
	const isMobile = useIsMobile();

	const body = (
		<>
			<header className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
				<span className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
					Drafts
				</span>
				<span className="text-[0.65625rem] tabular-nums text-muted-foreground">
					{drafts.length} saved
				</span>
			</header>
			<div
				className={cn(
					"overflow-y-auto p-1",
					isMobile ? "flex-1 min-h-0" : "max-h-[320px]",
				)}
			>
				{sorted.length === 0 ? (
					<div className="p-6 flex flex-col items-center justify-center text-center">
						<div className="w-10 h-10 rounded-full bg-muted border border-border inline-flex items-center justify-center mb-2">
							<FileText
								className="w-4 h-4 text-muted-foreground"
								aria-hidden="true"
							/>
						</div>
						<div className="text-[0.78125rem] font-medium text-foreground">
							No drafts yet
						</div>
						<p className="mt-0.5 text-[0.6875rem] text-muted-foreground max-w-[240px]">
							Saved drafts show up here. Click{" "}
							<span className="font-semibold">Save draft</span> to stash the
							current composer.
						</p>
					</div>
				) : (
					sorted.map((d) => {
						const isCurrent = d.id === currentDraftId;
						const preview = d.caption.trim();
						const mediaCount = d.media.length;
						const pollCount = d.pollEnabled
							? d.pollOptions.filter((o) => o.trim()).length
							: 0;
						const badges: string[] = [];
						if (mediaCount > 0) badges.push(`${mediaCount} media`);
						if (pollCount > 0) badges.push(`Poll · ${pollCount}`);
						if (d.trialReel) badges.push("Trial Reel");
						if (d.threadChain) badges.push("Chain");
						if (d.ghostPost) badges.push(`Ghost · ${d.ghostDuration}`);
						return (
							<div
								key={d.id}
								className={cn(
									"group relative flex items-start gap-2 px-2.5 py-2 rounded-md transition-colors",
									isCurrent
										? "bg-[color-mix(in_srgb,var(--color-oxblood)_8%,transparent)]"
										: "hover:bg-muted",
								)}
							>
								<Button
									type="button"
									variant="ghost"
									onClick={() => onLoad(d.id)}
									className="h-auto flex-1 min-w-0 justify-start rounded-md p-0 text-left"
								>
									<div className="flex items-baseline justify-between gap-2">
										<span
											className={cn(
												"text-[0.78125rem] font-medium truncate",
												preview
													? "text-foreground"
													: "text-muted-foreground italic",
											)}
										>
											{preview || "Empty caption"}
										</span>
										<span className="text-[0.65625rem] tabular-nums text-muted-foreground shrink-0">
											{formatDraftTime(d.updatedAt)}
										</span>
									</div>
									<div className="mt-1 flex items-center gap-1.5 flex-wrap text-[0.65625rem] text-muted-foreground tabular-nums">
										<span>
											{d.targetIds.length}{" "}
											{d.targetIds.length === 1 ? "account" : "accounts"}
										</span>
										{badges.map((b) => (
											<React.Fragment key={b}>
												<span className="text-muted-foreground">·</span>
												<span>{b}</span>
											</React.Fragment>
										))}
										{isCurrent && (
											<>
												<span className="text-muted-foreground">·</span>
												<span
													className="font-semibold"
													style={{ color: "var(--color-oxblood)" }}
												>
													Editing
												</span>
											</>
										)}
									</div>
								</Button>
								<IconTooltipButton
									label="Delete draft"
									onClick={() => onDelete(d.id)}
									className={cn(
										"shrink-0 text-muted-foreground hover:text-[color:var(--color-oxblood)]",
										isMobile
											? "opacity-100"
											: "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
									)}
									side="left"
								>
									<span className="w-6 h-6 inline-flex items-center justify-center rounded-md hover:bg-[color-mix(in_srgb,var(--color-oxblood)_8%,transparent)] active:bg-[color-mix(in_srgb,var(--color-oxblood)_14%,transparent)] transition-all">
										<X className="w-3 h-3" aria-hidden="true" />
									</span>
								</IconTooltipButton>
							</div>
						);
					})
				)}
			</div>
		</>
	);

	// Mobile: render trigger inline + bottom-sheet in portal. Mirrors the
	// pattern used by AccountPickerPopover / GroupPopover above.
	if (isMobile) {
		return (
			<MobilePopoverSheet
				open={open}
				onOpenChange={onOpenChange}
				trigger={trigger as React.ReactElement}
				ariaLabel="Saved drafts"
			>
				{body}
			</MobilePopoverSheet>
		);
	}

	return (
		<PopoverRoot open={open} onOpenChange={onOpenChange}>
			<PopoverTrigger asChild>{trigger}</PopoverTrigger>
			<PopoverContent
				side="top"
				align="start"
				sideOffset={10}
				className="w-[380px] p-0 rounded-xl overflow-hidden"
			>
				{body}
			</PopoverContent>
		</PopoverRoot>
	);
}

export function GroupPopover({
	open,
	onOpenChange,
	trigger,
	activeGroup,
	presets,
	selectedAccountIds,
	onSelect,
	onCreate,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	trigger: React.ReactElement;
	activeGroup: string | null;
	presets: GroupPreset[];
	selectedAccountIds: string[];
	onSelect: (g: GroupPreset) => void;
	onCreate: (name: string, color: string) => Promise<AccountGroup | null>;
}) {
	const [creating, setCreating] = useState(false);
	const [draftName, setDraftName] = useState("");
	const [draftColor, setDraftColor] = useState("#E5484D");
	const [saving, setSaving] = useState(false);
	const isMobile = useIsMobile();

	const NETWORK_COLORS: { hex: string; label: string }[] = [
		{ hex: "#E5484D", label: "Ray" },
		{ hex: "#B33A3F", label: "Signal" },
		{ hex: "#5F6670", label: "Slate" },
		{ hex: "#6F7078", label: "Graphite" },
		{ hex: "#1A1A1C", label: "Ink" },
		{ hex: "#A67C2D", label: "Amber" },
		{ hex: "#4F7661", label: "Sage" },
		{ hex: "#8A8D94", label: "Mist" },
	];

	useEffect(() => {
		if (!open) {
			setCreating(false);
			setDraftName("");
			setDraftColor("#E5484D");
			setSaving(false);
		}
	}, [open]);

	const handleSubmit = async () => {
		const name = draftName.trim();
		if (!name || selectedAccountIds.length === 0 || saving) return;
		setSaving(true);
		const result = await onCreate(name, draftColor);
		setSaving(false);
		if (result) {
			setCreating(false);
			setDraftName("");
			onOpenChange(false);
		}
	};

	if (typeof document === "undefined") return null;

	const body = (
		<>
			{presets.length === 0 && !creating ? (
				<div className="p-3 text-center">
					<div className="text-[0.71875rem] font-medium text-foreground">
						No groups yet
					</div>
					<div className="mt-1 text-[0.65625rem] text-muted-foreground leading-[1.4]">
						Target a set of accounts, then save them as a group.
					</div>
				</div>
			) : creating ? null : (
				presets.map((g) => {
					const active = activeGroup === g.id;
					const dotColor = active
						? "var(--color-oxblood)"
						: g.color ||
							"color-mix(in_srgb,var(--color-foreground)_30%,transparent)";
					return (
						<Button
							key={g.id}
							type="button"
							variant="ghost"
							onClick={() => onSelect(g)}
							className={cn(
								"h-auto w-full justify-start px-2.5 py-2 text-left",
								active
									? "bg-[color-mix(in_srgb,var(--color-oxblood)_12%,transparent)]"
									: "hover:bg-muted",
							)}
						>
							<span
								className="w-1.5 h-1.5 rounded-full mt-[7px] shrink-0"
								style={{ background: dotColor }}
								aria-hidden="true"
							/>
							<div className="flex-1 min-w-0">
								<div className="flex items-baseline justify-between gap-2">
									<span className="text-[0.78125rem] font-medium text-foreground truncate">
										{g.label}
									</span>
									<span className="text-[0.65625rem] tabular-nums text-muted-foreground shrink-0">
										{g.accountIds.length}
									</span>
								</div>
								<div className="text-[0.65625rem] text-muted-foreground mt-0.5 truncate">
									{g.description}
								</div>
							</div>
						</Button>
					);
				})
			)}
			<div className="mt-1 px-1.5 pt-1.5 border-t border-border">
				{creating ? (
					<div className="flex flex-col gap-2 p-2">
						<div>
							<label
								htmlFor="account-selector-group-name"
								className="block text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground mb-1"
							>
								Group name
							</label>
							<Input
								id="account-selector-group-name"
								type="text"
								value={draftName}
								onChange={(e) => setDraftName(e.target.value)}
								placeholder="e.g. Miami Models"
								maxLength={40}
								onKeyDown={(e) => {
									if (e.key === "Enter") {
										e.preventDefault();
										handleSubmit();
									} else if (e.key === "Escape") {
										setCreating(false);
									}
								}}
								sizeVariant="sm"
								className="h-7 text-[0.75rem]"
							/>
						</div>
						<div>
							<div className="block text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground mb-1">
								Color
							</div>
							<div className="flex flex-wrap gap-1">
								{NETWORK_COLORS.map((c) => (
									<Button
										key={c.hex}
										type="button"
										variant="ghost"
										onClick={() => setDraftColor(c.hex)}
										className="h-5 w-5 rounded-full p-0 transition-transform hover:scale-110"
										style={{
											background: c.hex,
											boxShadow:
												draftColor === c.hex
													? "0 0 0 2px var(--color-background), 0 0 0 4px var(--color-oxblood)"
													: undefined,
										}}
										aria-label={c.label}
									/>
								))}
							</div>
						</div>
						<div className="flex items-center justify-between pt-1">
							<span className="text-[0.65625rem] text-muted-foreground tabular-nums">
								{selectedAccountIds.length}{" "}
								{selectedAccountIds.length === 1 ? "account" : "accounts"}
							</span>
							<div className="flex items-center gap-1.5">
								<Button
									type="button"
									onClick={() => setCreating(false)}
									variant="ghost"
									size="sm"
									className="h-6 px-2 text-[0.6875rem]"
								>
									Cancel
								</Button>
								<Button
									type="button"
									onClick={handleSubmit}
									disabled={
										!draftName.trim() ||
										selectedAccountIds.length === 0 ||
										saving
									}
									size="sm"
									className="h-6 px-2.5 text-[0.6875rem]"
								>
									{saving ? "Saving…" : "Save"}
								</Button>
							</div>
						</div>
					</div>
				) : (
					<Button
						type="button"
						variant="ghost"
						onClick={() => setCreating(true)}
						disabled={selectedAccountIds.length === 0}
						title={
							selectedAccountIds.length === 0
								? "Pick accounts first"
								: undefined
						}
						className="h-8 w-full justify-start gap-2 px-2.5 text-[0.75rem] hover:text-[color:var(--color-oxblood)]"
					>
						<span
							className="inline-flex items-center justify-center w-4 h-4 rounded-full border border-dashed border-[var(--color-ring-oxblood-strong)] text-[0.625rem] leading-none"
							style={{ color: "var(--color-oxblood)" }}
						>
							+
						</span>
						Create group from selection
					</Button>
				)}
			</div>
		</>
	);

	if (isMobile) {
		return (
			<MobilePopoverSheet
				open={open}
				onOpenChange={onOpenChange}
				trigger={trigger}
				ariaLabel="Account groups"
				panelClassName="max-h-[80vh]"
			>
				<div className="p-3 pb-[calc(12px+env(safe-area-inset-bottom,0px))]">
					{body}
				</div>
			</MobilePopoverSheet>
		);
	}

	return (
		<PopoverRoot open={open} onOpenChange={onOpenChange}>
			<PopoverTrigger asChild>{trigger}</PopoverTrigger>
			<PopoverContent
				side="bottom"
				align="start"
				sideOffset={6}
				className="w-[280px] p-1.5 rounded-xl overflow-hidden"
			>
				{body}
			</PopoverContent>
		</PopoverRoot>
	);
}
