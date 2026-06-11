// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.

import {
	AtSign,
	Calendar,
	Copy,
	Download,
	Moon,
	PenSquare,
	Save,
	Search,
	Sparkles,
	Command as CommandIcon,
	Trash2,
	X,
} from "lucide-react";
import {
	Command,
	CommandEmpty,
	CommandGroup,
	CommandInput,
	CommandItem as CommandPrimitiveItem,
	CommandList,
} from "@/components/ui/Command";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Kbd } from "@/components/ui/Kbd";
import { Z } from "@/components/ui/overlayZ";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import {
	type NlQueryResult,
	type NlQuerySpec,
	useNlQuery,
} from "@/hooks/useNlQuery";
import { isMacLike } from "@/lib/platform";
import { persistThemeToRemote } from "@/lib/themeSync";
import { APP_ROUTE_COMMANDS } from "@/routes/routeRegistry";
import { appToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { supabase } from "@/services/supabase";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";

interface CommandPaletteProps {
	isOpen: boolean;
	onClose: () => void;
	onNavigate?: (route: string) => void;
}

interface CommandItem {
	id: string;
	label: string;
	icon: React.ElementType;
	shortcut?: string | undefined;
	subtitle?: string | undefined;
	action: () => void;
	category: string;
}

export { APP_ROUTE_COMMANDS };

const RECENTS_KEY = "juno33-cmdk-recents";
const RECENTS_MAX = 5;
const ASK_HISTORY_KEY = "juno33:ask-history:v1";
const ASK_STARTERS = [
	"Compare reach week over week",
	"Top 10 accounts by save rate",
	"Show non-follower reach % per account",
	"Total replies last 30 days",
	"Reposts and quotes by day",
];

interface SavedNlQuery {
	id: string;
	prompt: string;
	spec: NlQuerySpec;
	name: string | null;
	created_at: string | null;
}

function loadRecentIds(): string[] {
	if (typeof window === "undefined") return [];
	try {
		const raw = window.localStorage.getItem(RECENTS_KEY);
		if (!raw) return [];
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed)
			? parsed
					.filter((x): x is string => typeof x === "string")
					.slice(0, RECENTS_MAX)
			: [];
	} catch {
		return [];
	}
}

function pushRecentId(id: string) {
	if (typeof window === "undefined") return;
	try {
		const current = loadRecentIds();
		const next = [id, ...current.filter((x) => x !== id)].slice(0, RECENTS_MAX);
		window.localStorage.setItem(RECENTS_KEY, JSON.stringify(next));
	} catch {
		/* localStorage full or blocked — recents are best-effort */
	}
}

function readAskHistory(): string[] {
	if (typeof window === "undefined") return [];
	try {
		const parsed = JSON.parse(
			window.localStorage.getItem(ASK_HISTORY_KEY) ?? "[]",
		);
		return Array.isArray(parsed)
			? parsed
					.filter((item): item is string => typeof item === "string")
					.slice(0, 20)
			: [];
	} catch {
		return [];
	}
}

function writeAskHistory(value: string): string[] {
	const next = [
		value,
		...readAskHistory().filter((entry) => entry !== value),
	].slice(0, 20);
	try {
		window.localStorage.setItem(ASK_HISTORY_KEY, JSON.stringify(next));
	} catch {
		/* best-effort */
	}
	return next;
}

function formatAskNumber(value: number): string {
	if (!Number.isFinite(value)) return "-";
	const abs = Math.abs(value);
	if (abs >= 1_000_000)
		return `${(value / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
	if (abs >= 1_000)
		return `${(value / 1_000).toFixed(abs >= 100_000 ? 0 : 1)}K`;
	return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(
		value,
	);
}

function metricLabel(metric: string): string {
	return (
		metric
			.replace(/^total/i, "")
			.replace(/^ig/i, "IG ")
			.replace(/([a-z])([A-Z])/g, "$1 $2")
			.replace(/\s+/g, " ")
			.trim()
			.replace(/^./, (char) => char.toUpperCase()) || metric
	);
}

function groupLabel(groupBy: NlQuerySpec["groupBy"]): string {
	if (groupBy === "account") return "Account";
	if (groupBy === "day") return "Day";
	return "Single total";
}

function encodeCell(value: string, separator: "," | "\t"): string {
	if (separator === "\t") return value.replace(/\t/g, " ").replace(/\n/g, " ");
	const escaped = value.replace(/"/g, '""');
	return /[",\n]/.test(escaped) ? `"${escaped}"` : escaped;
}

function tableText(data: NlQueryResult, separator: "," | "\t"): string {
	const firstHeader =
		data.spec.groupBy === "account"
			? "Account"
			: data.spec.groupBy === "day"
				? "Day"
				: "Metric";
	const rows = [
		["Rank", firstHeader, data.spec.metric, "Share of fleet", "Platform"],
		...data.rows.map((row, index) => [
			String(index + 1),
			row.label,
			String(row.value),
			data.aggregate
				? `${((row.value / data.aggregate) * 100).toFixed(2)}%`
				: "0%",
			data.spec.platform === "all" ? "all" : data.spec.platform,
		]),
	];
	return rows
		.map((row) =>
			row.map((cell) => encodeCell(cell, separator)).join(separator),
		)
		.join("\n");
}

function useSavedNlQueries() {
	const [savedQueries, setSavedQueries] = useState<SavedNlQuery[]>([]);
	const [saving, setSaving] = useState(false);

	const loadSavedQueries = useCallback(async () => {
		const { data: auth } = await supabase.auth.getUser();
		if (!auth.user) return;
		const { data: rows, error } = await supabase
			.from("saved_nl_queries")
			.select("id, prompt, spec, name, created_at")
			.eq("user_id", auth.user.id)
			.order("created_at", { ascending: false })
			.limit(30);
		if (!error) setSavedQueries((rows ?? []) as SavedNlQuery[]);
	}, []);

	useEffect(() => {
		void loadSavedQueries();
	}, [loadSavedQueries]);

	const saveQuery = async ({
		prompt,
		spec,
		name,
	}: {
		prompt: string;
		spec: NlQuerySpec;
		name?: string | null;
	}) => {
		if (saving) return;
		const { data: auth } = await supabase.auth.getUser();
		if (!auth.user) {
			appToast.error("Sign in to save queries");
			return;
		}
		setSaving(true);
		const { error } = await supabase.from("saved_nl_queries").insert({
			user_id: auth.user.id,
			prompt,
			spec: spec as never,
			name: name?.trim() || null,
		});
		setSaving(false);
		if (error) {
			appToast.error("Could not save query", { description: error.message });
			return;
		}
		appToast.success("Query saved");
		await loadSavedQueries();
	};

	const deleteSavedQuery = async (query: SavedNlQuery) => {
		const { error } = await supabase
			.from("saved_nl_queries")
			.delete()
			.eq("id", query.id);
		if (error) {
			appToast.error("Could not delete query", { description: error.message });
			return;
		}
		setSavedQueries((current) =>
			current.filter((item) => item.id !== query.id),
		);
	};

	return { savedQueries, saving, saveQuery, deleteSavedQuery };
}

export function CommandPalette({
	isOpen,
	onClose,
	onNavigate,
}: CommandPaletteProps) {
	const [query, setQuery] = useState("");
	const [selectedIndex, setSelectedIndex] = useState(0);
	const [recentIds, setRecentIds] = useState<string[]>(() => loadRecentIds());
	const [askHistory, setAskHistory] = useState<string[]>(() =>
		readAskHistory(),
	);
	const [lastAskPrompt, setLastAskPrompt] = useState("");
	const inputRef = useRef<HTMLInputElement>(null);
	const focusTimerRef = useRef<number | null>(null);
	// Tab-cycle trap. The palette already focuses the search input on open
	// via the timeout below — this hook adds Shift+Tab/Tab cycling and
	// return-focus on close.
	const trapRef = useFocusTrap<HTMLDivElement>(onClose, isOpen);
	const setScope = useAccountScopeStore((s) => s.setScope);
	const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const selectedGroupId = useWorkspaceStore((s) => s.selectedGroupId);
	const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);
	const { accounts } = useConnectedAccounts();
	const nlQuery = useNlQuery();
	const {
		savedQueries,
		saving: savingQuery,
		saveQuery,
		deleteSavedQuery,
	} = useSavedNlQueries();

	const runAsk = useCallback(
		(value: string) => {
			const trimmed = value.trim();
			if (!trimmed || nlQuery.isPending) return;
			const groupAccountIds =
				!scopedAccount && selectedGroupId
					? accounts
							.filter((account) => account.groupId === selectedGroupId)
							.map((account) => account.id)
					: [];
			setLastAskPrompt(trimmed);
			setAskHistory(writeAskHistory(trimmed));
			nlQuery.mutate({
				prompt: trimmed,
				workspaceId: currentWorkspace?.id ?? null,
				...(scopedAccount
					? {
							accountId: scopedAccount.id,
							platform: scopedAccount.platform,
						}
					: {}),
				...(!scopedAccount && selectedGroupId
					? {
							groupId: selectedGroupId,
							accountIds: groupAccountIds,
						}
					: {}),
			});
		},
		[accounts, currentWorkspace?.id, nlQuery, scopedAccount, selectedGroupId],
	);

	const runAskOverride = useCallback(
		(override: Partial<NlQuerySpec>) => {
			if (!nlQuery.data?.spec || nlQuery.isPending) return;
			const groupAccountIds =
				!scopedAccount && selectedGroupId
					? accounts
							.filter((account) => account.groupId === selectedGroupId)
							.map((account) => account.id)
					: [];
			nlQuery.mutate({
				specOverride: { ...nlQuery.data.spec, ...override },
				workspaceId: currentWorkspace?.id ?? null,
				...(scopedAccount
					? {
							accountId: scopedAccount.id,
							platform: scopedAccount.platform,
						}
					: {}),
				...(!scopedAccount && selectedGroupId
					? {
							groupId: selectedGroupId,
							accountIds: groupAccountIds,
						}
					: {}),
			});
		},
		[accounts, currentWorkspace?.id, nlQuery, scopedAccount, selectedGroupId],
	);

	const navigateTo = (route: string) => {
		onNavigate?.(route);
		onClose();
	};

	const switchScope = (
		id: string,
		handle: string,
		platform: "threads" | "instagram",
	) => {
		setScope({ id, handle, platform });
		navigateTo("dashboard");
	};

	// Focus input + re-read recents from localStorage when palette opens. Recents
	// may have been updated from a different tab; re-hydrating on every open is
	// cheap and keeps the list in sync without a storage event listener.
	useEffect(() => {
		if (isOpen) {
			setQuery("");
			setSelectedIndex(0);
			setRecentIds(loadRecentIds());
			setAskHistory(readAskHistory());
			if (focusTimerRef.current) {
				window.clearTimeout(focusTimerRef.current);
			}
			focusTimerRef.current = window.setTimeout(() => {
				inputRef.current?.focus();
				focusTimerRef.current = null;
			}, 50);
		}
		return () => {
			if (focusTimerRef.current) {
				window.clearTimeout(focusTimerRef.current);
				focusTimerRef.current = null;
			}
		};
	}, [isOpen]);

	const accountCommands: CommandItem[] = accounts
		.filter((account) => account.id !== scopedAccount?.id)
		.slice()
		.sort((a, b) => a.handle.localeCompare(b.handle))
		.slice(0, 5)
		.map((account) => ({
			id: `rec-${account.id}`,
			label: `Switch to ${account.handle}`,
			subtitle: `${account.platform === "instagram" ? "Instagram" : "Threads"} account · set global scope`,
			icon: AtSign,
			category: "Accounts",
			action: () => {
				switchScope(account.id, account.handle, account.platform);
			},
		}));

	// Common actions — top 3 by frequency (also Linear pattern)
	const commonActions: CommandItem[] = [
		{
			id: "act-post",
			label: "Create new post",
			subtitle: "Open Composer with current account scope",
			icon: PenSquare,
			shortcut: "C",
			category: "Common",
			action: () => {
				navigateTo("composer");
			},
		},
		{
			id: "act-schedule",
			label: "Reschedule pending posts",
			subtitle: "Open Scheduler in bulk reschedule mode",
			icon: Calendar,
			shortcut: "R",
			category: "Common",
			action: () => {
				navigateTo("calendar?bulk=reschedule");
			},
		},
		{
			id: "act-ask",
			label: "Ask analytics",
			subtitle: "Run a natural-language analytics query here",
			icon: Sparkles,
			shortcut: "A",
			category: "Common",
			action: () => {
				setQuery("");
				inputRef.current?.focus();
			},
		},
		{
			id: "act-ai",
			label: "Generate ideas with AI",
			subtitle: "Start from the Composer AI tool rail",
			icon: Sparkles,
			shortcut: "I",
			category: "Common",
			action: () => {
				navigateTo("composer?aiRail=1");
			},
		},
		{
			id: "act-composer-command",
			label: "Open Composer actions",
			subtitle: "Upload media, switch Reel/Story, Notify Me, readiness",
			icon: CommandIcon,
			shortcut: "⌘J",
			category: "Common",
			action: () => {
				navigateTo("composer");
				window.setTimeout(() => {
					window.dispatchEvent(new CustomEvent("juno33:composer-command"));
				}, 120);
			},
		},
	];

	const routeCommands: CommandItem[] = APP_ROUTE_COMMANDS.map((command) => ({
		...command,
		action: () => navigateTo(command.route),
	}));

	const allCommands: CommandItem[] = [
		...accountCommands,
		...commonActions,
		...routeCommands,
		{
			id: "pref-theme",
			label: "Toggle Dark Mode",
			subtitle: "Switch the current browser theme",
			icon: Moon,
			category: "Preferences",
			action: () => {
				const el = document.documentElement;
				el.classList.toggle("dark");
				const next = el.classList.contains("dark") ? "dark" : "light";
				try {
					localStorage.setItem("juno33-theme", next);
				} catch (_e) {
					/* ignore */
				}
				void persistThemeToRemote(next);
				onClose();
			},
		},
	];

	const savedAskCommands: CommandItem[] = savedQueries
		.slice(0, 5)
		.map((saved) => ({
			id: `ask-saved-${saved.id}`,
			label: saved.name ?? saved.prompt,
			subtitle: saved.prompt,
			icon: Sparkles,
			category: "Saved Ask",
			action: () => runAsk(saved.prompt),
		}));

	const historyAskCommands: CommandItem[] = askHistory
		.slice(0, 5)
		.map((prompt) => ({
			id: `ask-history-${prompt}`,
			label: prompt,
			subtitle: "Recent analytics question",
			icon: Search,
			category: "Recent Ask",
			action: () => runAsk(prompt),
		}));

	const starterAskCommands: CommandItem[] = ASK_STARTERS.map((prompt) => ({
		id: `ask-starter-${prompt}`,
		label: prompt,
		subtitle: "Starter analytics question",
		icon: Sparkles,
		category: "Ask Starters",
		action: () => runAsk(prompt),
	}));

	// Map localStorage recent IDs back to live commands. Silently drops any ID
	// whose command no longer exists (e.g., an account got disconnected).
	const recentCommands = useMemo<CommandItem[]>(() => {
		if (recentIds.length === 0) return [];
		return recentIds
			.map((id) => allCommands.find((c) => c.id === id))
			.filter((c): c is CommandItem => c !== undefined)
			.map((c) => ({ ...c, category: "Recent" }));
		// allCommands is derived from `accounts` (prop) — safe to re-derive each
		// render, the memo only shields the map/filter pass.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [recentIds, allCommands.find]);

	// Empty query = show Recent + Accounts + Common (zero-typing path, HIG/Linear
	// default). Pull any Recent command out of its home category so it only
	// appears once. Typed query = filter across everything; no dedupe needed.
	const trimmedQuery = query.trim();
	const visibleCommands =
		trimmedQuery === ""
			? (() => {
					const recentSet = new Set(recentCommands.map((c) => c.id));
					const rest = [
						...accountCommands,
						...commonActions,
						...savedAskCommands,
						...historyAskCommands,
						...starterAskCommands,
					].filter((c) => !recentSet.has(c.id));
					return [...recentCommands, ...rest];
				})()
			: (() => {
					const lower = trimmedQuery.toLowerCase();
					const matches = [
						...allCommands,
						...savedAskCommands,
						...historyAskCommands,
						...starterAskCommands,
					].filter(
						(cmd) =>
							cmd.label.toLowerCase().includes(lower) ||
							cmd.category.toLowerCase().includes(lower) ||
							(cmd.subtitle?.toLowerCase().includes(lower) ?? false),
					);
					return [
						{
							id: "ask-run-query",
							label: `Ask analytics: ${trimmedQuery}`,
							subtitle: "Run this as a natural-language analytics query",
							icon: Sparkles,
							category: "Ask",
							action: () => runAsk(trimmedQuery),
						},
						...matches.filter((cmd) => cmd.id !== "ask-run-query"),
					];
				})();

	const runCommand = useCallback((cmd: CommandItem) => {
		pushRecentId(cmd.id);
		setRecentIds((prev) =>
			[cmd.id, ...prev.filter((x) => x !== cmd.id)].slice(0, RECENTS_MAX),
		);
		cmd.action();
	}, []);
	const filteredCommands = visibleCommands;

	const copyAskTable = async () => {
		if (!nlQuery.data) return;
		try {
			await navigator.clipboard.writeText(tableText(nlQuery.data, "\t"));
			appToast.success("Table copied");
		} catch {
			appToast.error("Could not copy table");
		}
	};

	const exportAskCsv = () => {
		if (!nlQuery.data) return;
		const blob = new Blob([tableText(nlQuery.data, ",")], {
			type: "text/csv;charset=utf-8",
		});
		const url = URL.createObjectURL(blob);
		const link = document.createElement("a");
		link.href = url;
		link.download = `ask-results-${Date.now()}.csv`;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		setTimeout(() => URL.revokeObjectURL(url), 0);
	};

	const saveCurrentAskQuery = async () => {
		if (!nlQuery.data?.spec || !lastAskPrompt) return;
		await saveQuery({
			prompt: lastAskPrompt,
			spec: nlQuery.data.spec,
			name: lastAskPrompt,
		});
	};

	// Group commands by category
	const groups = filteredCommands.reduce(
		(acc, cmd) => {
			if (!acc[cmd.category]) acc[cmd.category] = [];
			acc[cmd.category]!.push(cmd);
			return acc;
		},
		{} as Record<string, CommandItem[]>,
	);

	// Flattened ordered list for keyboard navigation
	const visibleItems = Object.values(groups).flat();

	useEffect(() => {
		const handleKeyDown = (e: KeyboardEvent) => {
			if (!isOpen) return;

			switch (e.key) {
				case "ArrowDown":
					e.preventDefault();
					setSelectedIndex((prev) => (prev + 1) % visibleItems.length);
					break;
				case "ArrowUp":
					e.preventDefault();
					setSelectedIndex(
						(prev) => (prev - 1 + visibleItems.length) % visibleItems.length,
					);
					break;
				case "Enter":
					e.preventDefault();
					if (visibleItems[selectedIndex]) {
						runCommand(visibleItems[selectedIndex]);
					}
					break;
				case "Escape":
					e.preventDefault();
					onClose();
					break;
			}
		};

		window.addEventListener("keydown", handleKeyDown);
		return () => window.removeEventListener("keydown", handleKeyDown);
	}, [isOpen, visibleItems, selectedIndex, onClose, runCommand]);

	if (!isOpen) return null;

	return (
		<>
			{/* Backdrop Blur */}
			<div
				className="fixed inset-0 bg-foreground/40 backdrop-blur-[4px] dark:bg-background/60"
				style={{ zIndex: Z.paletteBackdrop }}
				onClick={onClose}
			/>

			{/* Modal Container */}
			<div
				className="pointer-events-none fixed inset-0 flex items-start justify-center px-4 pt-[15vh]"
				style={{ zIndex: Z.palette }}
			>
				<div
					ref={trapRef}
					role="dialog"
					aria-modal="true"
					aria-label="Command palette"
					className="pointer-events-auto flex w-full max-w-[860px] flex-col overflow-hidden rounded-xl border border-border bg-popover/95 shadow-[0_32px_64px_-12px_color-mix(in_srgb,var(--color-foreground)_36%,transparent)]"
					style={{
						WebkitBackdropFilter: "blur(20px) saturate(150%)",
						backdropFilter: "blur(20px) saturate(150%)",
					}}
					onClick={(e) => e.stopPropagation()}
				>
							<Command shouldFilter={false} className="rounded-none bg-transparent">
							{/* Search Header */}
							<div className="relative">
								<CommandInput
									ref={inputRef}
									value={query}
									onValueChange={(value) => {
										setQuery(value);
										setSelectedIndex(0);
									}}
									placeholder="Search commands, accounts, routes, or ask analytics"
									className="h-12 pr-24 font-semibold"
								/>
								<div className="pointer-events-none absolute right-3 top-1/2 flex -translate-y-1/2 items-center gap-1.5">
									{isMacLike() ? (
										<Kbd>⌘</Kbd>
									) : (
										<Kbd>Ctrl</Kbd>
									)}
									<Kbd>K</Kbd>
								</div>
							</div>

							{(nlQuery.isPending || nlQuery.isError || nlQuery.data) && (
								<AskResultPanel
									result={nlQuery.data}
									pending={nlQuery.isPending}
									error={nlQuery.error}
									saving={savingQuery}
									onSpecChange={runAskOverride}
									onCopy={() => void copyAskTable()}
									onExport={exportAskCsv}
									onSave={() => void saveCurrentAskQuery()}
									onClear={() => nlQuery.reset()}
								/>
							)}

							{/* Command List */}
							<CommandList className="max-h-[420px] overflow-y-auto p-2 scrollbar-hide">
								{visibleItems.length === 0 ? (
									<CommandEmpty className="py-8 text-center text-label-tertiary text-base">
										No commands found for "{query}"
									</CommandEmpty>
								) : (
									Object.entries(groups).map(([category, items], groupIdx) => (
										<CommandGroup
											key={category}
											heading={category}
											className={groupIdx > 0 ? "mt-4" : ""}
										>
											{items.map((cmd) => {
												const isSelected =
													visibleItems.indexOf(cmd) === selectedIndex;
												return (
													<CommandPrimitiveItem
														key={cmd.id}
														value={cmd.id}
														className={cn(
															"grid grid-cols-[24px_minmax(0,1fr)_auto] items-center gap-3 px-3 py-2.5 rounded-lg cursor-default transition-all duration-100",
															isSelected
																? "bg-[color-mix(in_srgb,var(--color-oxblood)_13%,transparent)] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-oxblood)_34%,transparent)]"
																: "hover:bg-muted",
														)}
														onMouseEnter={() =>
															setSelectedIndex(visibleItems.indexOf(cmd))
														}
														onSelect={() => runCommand(cmd)}
													>
														<span
															className={cn(
																"h-6 w-6 rounded-md border border-border bg-card inline-flex items-center justify-center",
																isSelected &&
																	"border-[color-mix(in_srgb,var(--color-oxblood)_28%,var(--color-border))]",
															)}
														>
															<cmd.icon
																className={cn(
																	"w-3.5 h-3.5",
																	isSelected
																		? "text-foreground"
																		: "text-label-tertiary",
																)}
															/>
														</span>
														<div className="min-w-0">
															<div
																className={cn(
																	"truncate text-[0.8125rem] font-semibold",
																	isSelected
																		? "text-foreground"
																		: "text-label-secondary",
																)}
															>
																{cmd.label}
															</div>
															{cmd.subtitle ? (
																<div className="mt-0.5 truncate font-mono text-[0.625rem] text-label-quaternary">
																	{cmd.subtitle}
																</div>
															) : null}
														</div>
														{cmd.shortcut && (
															<Badge tone={isSelected ? "oxblood" : "secondary"}>
																{cmd.shortcut}
															</Badge>
														)}
													</CommandPrimitiveItem>
												);
											})}
										</CommandGroup>
									))
								)}
							</CommandList>

							{trimmedQuery === "" && savedQueries.length > 0 && (
								<div className="border-t border-border px-3 py-2">
									<div className="app-label mb-1.5 text-label-tertiary">
										Saved Ask Queries
									</div>
									<div className="flex gap-1.5 overflow-x-auto pb-1">
										{savedQueries.slice(0, 8).map((saved) => (
											<span
												key={saved.id}
												className="inline-flex max-w-[240px] shrink-0 items-center gap-1 rounded-md border border-border bg-card px-2 py-1"
											>
												<Button
													type="button"
													onClick={() => runAsk(saved.prompt)}
													variant="ghost"
													size="sm"
													className="h-6 min-w-0 truncate px-1 text-[0.71875rem]"
												>
													{saved.name ?? saved.prompt}
												</Button>
												<Button
													type="button"
													onClick={() => void deleteSavedQuery(saved)}
													aria-label={`Delete ${saved.name ?? saved.prompt}`}
													variant="ghost"
													size="icon"
													className="size-6 text-label-quaternary"
												>
													<Trash2 data-icon="inline-start" aria-hidden="true" />
												</Button>
											</span>
										))}
									</div>
								</div>
							)}

							{/* Footer */}
							<div className="border-t border-border px-4 py-2 flex items-center justify-between bg-[color-mix(in_srgb,var(--color-foreground)_2.5%,transparent)]">
								<div className="flex items-center gap-3 font-mono text-[0.625rem] text-label-tertiary">
									<span className="flex items-center gap-1">
										<Kbd>↵</Kbd> select
									</span>
									<span className="flex items-center gap-1">
										<Kbd>↓</Kbd>
										<Kbd>↑</Kbd> navigate
									</span>
									<span className="flex items-center gap-1">
										<Kbd>Esc</Kbd> close
									</span>
								</div>
								<div className="app-label text-label-tertiary">
									Juno33
								</div>
							</div>
							</Command>
				</div>
			</div>
		</>
	);
}

function AskResultPanel({
	result,
	pending,
	error,
	saving,
	onSpecChange,
	onCopy,
	onExport,
	onSave,
	onClear,
}: {
	result: NlQueryResult | undefined;
	pending: boolean;
	error: Error | null;
	saving: boolean;
	onSpecChange: (override: Partial<NlQuerySpec>) => void;
	onCopy: () => void;
	onExport: () => void;
	onSave: () => void;
	onClear: () => void;
}) {
	return (
		<div className="border-b border-border bg-[color-mix(in_srgb,var(--color-foreground)_2.5%,transparent)] px-4 py-3">
			<div className="mb-2 flex items-center justify-between gap-3">
				<div className="inline-flex min-w-0 items-center gap-2">
					<span className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-border bg-card">
						<Sparkles className="h-3.5 w-3.5 text-label-secondary" />
					</span>
					<div className="min-w-0">
						<div className="text-[0.8125rem] font-semibold text-foreground">
							Ask analytics
						</div>
						<div className="truncate font-mono text-[0.625rem] text-label-quaternary">
							{pending
								? "Routing analytics question"
								: (result?.interpretation ?? error?.message ?? "Ready")}
						</div>
					</div>
				</div>
				<div className="flex items-center gap-1.5">
					<AskPanelButton
						label="Copy"
						disabled={!result || pending}
						onClick={onCopy}
					>
						<Copy className="h-3.5 w-3.5" />
					</AskPanelButton>
					<AskPanelButton
						label="CSV"
						disabled={!result || pending}
						onClick={onExport}
					>
						<Download className="h-3.5 w-3.5" />
					</AskPanelButton>
					<AskPanelButton
						label={saving ? "Saving" : "Save"}
						disabled={!result || pending || saving}
						onClick={onSave}
					>
						<Save className="h-3.5 w-3.5" />
					</AskPanelButton>
					<Button
						type="button"
						aria-label="Clear Ask result"
						onClick={onClear}
						variant="ghost"
						size="icon"
						className="size-7 text-label-tertiary"
					>
						<X data-icon="inline-start" aria-hidden="true" />
					</Button>
				</div>
			</div>

			{pending ? (
				<div className="grid gap-2">
					<div className="h-2 w-44 rounded-full bg-muted/60" />
					<div className="h-2 w-[72%] rounded-full bg-muted/35" />
					<div className="h-2 w-[58%] rounded-full bg-muted/25" />
				</div>
			) : error ? (
				<div className="rounded-md border border-[color-mix(in_srgb,var(--color-oxblood)_28%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-oxblood)_7%,transparent)] px-3 py-2 text-[0.78125rem] text-[var(--color-oxblood)]">
					{error.message}
				</div>
			) : result ? (
				<div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
					<div className="min-w-0 overflow-hidden rounded-md border border-border bg-card">
						<div className="app-label grid grid-cols-[minmax(0,1fr)_110px_90px] border-b border-border px-3 py-1.5 text-label-quaternary">
							<span>{groupLabel(result.spec.groupBy)}</span>
							<span className="text-right">
								{metricLabel(result.spec.metric)}
							</span>
							<span className="text-right">Share</span>
						</div>
						<div className="max-h-[190px] overflow-y-auto">
							{result.rows.length > 0 ? (
								result.rows.slice(0, 30).map((row) => (
									<div
										key={row.label}
										className="grid grid-cols-[minmax(0,1fr)_110px_90px] border-b border-border px-3 py-1.5 last:border-b-0"
									>
										<span className="truncate text-[0.78125rem] font-medium text-foreground">
											{row.label}
										</span>
										<span className="text-right font-mono text-[0.78125rem] tabular-nums text-label-secondary">
											{formatAskNumber(row.value)}
										</span>
										<span className="text-right font-mono text-[0.71875rem] tabular-nums text-label-tertiary">
											{result.aggregate
												? `${((row.value / result.aggregate) * 100).toFixed(1)}%`
												: "0%"}
										</span>
									</div>
								))
							) : (
								<div className="px-3 py-3 text-[0.8125rem] text-label-tertiary">
									Aggregate: {formatAskNumber(result.aggregate)} across{" "}
									{result.matchedAccounts} account
									{result.matchedAccounts === 1 ? "" : "s"}
								</div>
							)}
						</div>
					</div>

					<div className="min-w-0 rounded-md border border-border bg-card p-2">
						<div className="app-label mb-2 text-label-quaternary">
							Refine
						</div>
						{result.scope && (
							<div className="mb-2 rounded-md border border-border bg-muted/35 px-2 py-1.5 text-[0.6875rem] leading-snug text-label-secondary">
								Grounded in{" "}
								{result.scope.accountId
									? "the selected account"
									: result.scope.groupId
										? "the selected group"
										: "all connected accounts"}
								{" "}({result.scope.accountCount} matched)
							</div>
						)}
						<AskSegment
							label="Platform"
							value={result.spec.platform}
							options={[
								{ value: "all", label: "All" },
								{ value: "threads", label: "Threads" },
								{ value: "instagram", label: "Instagram" },
							]}
							onChange={(platform) => onSpecChange({ platform })}
						/>
						<AskSegment
							label="Group"
							value={result.spec.groupBy}
							options={[
								{ value: "account", label: "Account" },
								{ value: "day", label: "Day" },
								{ value: "none", label: "Total" },
							]}
							onChange={(groupBy) => onSpecChange({ groupBy })}
						/>
						<AskSegment
							label="Window"
							value={String(result.spec.timeframeDays)}
							options={[
								{ value: "7", label: "7d" },
								{ value: "30", label: "30d" },
								{ value: "60", label: "60d" },
								{ value: "90", label: "90d" },
							]}
							onChange={(days) => onSpecChange({ timeframeDays: Number(days) })}
						/>
					</div>
				</div>
			) : null}
		</div>
	);
}

function AskPanelButton({
	label,
	disabled,
	onClick,
	children,
}: {
	label: string;
	disabled?: boolean | undefined;
	onClick: () => void;
	children: React.ReactNode;
}) {
	return (
		<Button
			type="button"
			onClick={onClick}
			disabled={disabled}
			variant="outline"
			size="sm"
			className="h-7 px-2 text-[0.71875rem]"
		>
			{children}
			{label}
		</Button>
	);
}

function AskSegment<T extends string>({
	label,
	value,
	options,
	onChange,
}: {
	label: string;
	value: T;
	options: { value: T; label: string }[];
	onChange: (value: T) => void;
}) {
	return (
		<div className="mb-2 last:mb-0">
			<div className="mb-1 text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-label-quaternary">
				{label}
			</div>
			<div
				className="flex flex-wrap gap-1"
				role="radiogroup"
				aria-label={label}
			>
				{options.map((option) => (
					<Button
						key={option.value}
						type="button"
						aria-pressed={value === option.value}
						onClick={() => onChange(option.value)}
						variant={value === option.value ? "default" : "secondary"}
						size="sm"
						className={cn(
							"h-6 px-2 text-[0.6875rem]",
						)}
					>
						{option.label}
					</Button>
				))}
			</div>
		</div>
	);
}
