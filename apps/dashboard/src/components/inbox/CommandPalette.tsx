import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Inbox, Search } from "lucide-react";
import {
	Command,
	CommandEmpty,
	CommandGroup,
	CommandInput,
	CommandItem,
	CommandList,
} from "@/components/ui/Command";
import { cn } from "@/lib/utils";
import type { Conversation } from "./types";

export interface InboxCommand {
	id: string;
	label: string;
	group: string;
	keywords?: string[] | undefined;
	icon?: React.ComponentType<{ className?: string | undefined }> | undefined;
	run: () => void;
}

export function CommandPalette({
	open,
	conversations,
	commands,
	onClose,
	onJump,
}: {
	open: boolean;
	conversations: Conversation[];
	commands: InboxCommand[];
	onClose: () => void;
	onJump: (id: string) => void;
}) {
	const [query, setQuery] = useState("");
	const [selected, setSelected] = useState(0);
	const inputRef = useRef<HTMLInputElement>(null);
	const focusTimerRef = useRef<number | null>(null);

	useEffect(() => {
		if (open) {
			setQuery("");
			setSelected(0);
			if (focusTimerRef.current) {
				window.clearTimeout(focusTimerRef.current);
			}
			focusTimerRef.current = window.setTimeout(() => {
				inputRef.current?.focus();
				focusTimerRef.current = null;
			}, 0);
		}
		return () => {
			if (focusTimerRef.current) {
				window.clearTimeout(focusTimerRef.current);
				focusTimerRef.current = null;
			}
		};
	}, [open]);

	const visible = useMemo(() => {
		const jumpCommands: InboxCommand[] = conversations
			.slice(0, 50)
			.map((c) => ({
				id: `jump:${c.id}`,
				label: `Jump to conversation: ${c.user.name}`,
				group: "Jump",
				keywords: [c.user.handle, c.snippet],
				icon: Search,
				run: () => onJump(c.id),
			}));
		const all = [...commands, ...jumpCommands];
		const q = query.trim().toLowerCase();
		if (!q) return all;
		return all.filter((command) => {
			const hay = [command.label, command.group, ...(command.keywords ?? [])]
				.join(" ")
				.toLowerCase();
			return fuzzyMatch(hay, q);
		});
	}, [commands, conversations, onJump, query]);

	if (!open) return null;

	const runSelected = () => {
		const command = visible[selected];
		if (!command) return;
		command.run();
		onClose();
	};

	return (
		<div
			className="fixed inset-0 z-[120] td-overlay backdrop-blur-[10px]"
			onMouseDown={onClose}
			role="presentation"
		>
			<div
				role="dialog"
				aria-modal="true"
				aria-label="Inbox command palette"
				className="fixed left-1/2 top-[18vh] w-[min(640px,92vw)] -translate-x-1/2 rounded-xl border border-border bg-card td-modal-shadow overflow-hidden"
				onMouseDown={(event) => event.stopPropagation()}
			>
				<Command shouldFilter={false} className="rounded-none">
					<CommandInput
						ref={inputRef}
						aria-label="Search commands"
						value={query}
						onValueChange={(value) => {
							setQuery(value);
							setSelected(0);
						}}
						onKeyDown={(event) => {
							if (event.key === "Escape") onClose();
							if (event.key === "ArrowDown") {
								event.preventDefault();
								setSelected((value) => Math.min(visible.length - 1, value + 1));
							}
							if (event.key === "ArrowUp") {
								event.preventDefault();
								setSelected((value) => Math.max(0, value - 1));
							}
							if (event.key === "Enter") {
								event.preventDefault();
								runSelected();
							}
						}}
						placeholder="Search inbox actions"
					/>
					<CommandList className="max-h-[420px] overflow-y-auto p-1">
						{visible.length === 0 ? (
							<CommandEmpty>No matching commands</CommandEmpty>
						) : (
							<CommandGroup>
								{visible.map((command, index) => {
									const Icon = command.icon ?? defaultIcon(command.group);
									return (
										<CommandItem
											key={command.id}
											value={command.id}
											onMouseEnter={() => setSelected(index)}
											onSelect={() => {
												command.run();
												onClose();
											}}
											className={cn(
												"w-full justify-start gap-3 text-left",
												selected === index
													? "bg-muted text-foreground"
													: "text-muted-foreground",
											)}
										>
											<Icon className="size-4 text-muted-foreground" />
											<span className="min-w-0 flex-1">
												<span className="block truncate text-[0.8125rem] font-medium">
													{command.label}
												</span>
												<span className="block text-[0.65625rem] text-muted-foreground">
													{command.group}
												</span>
											</span>
											<span className="rounded-full border border-border bg-card px-2 py-0.5 font-mono text-[0.625rem] text-muted-foreground">
												{command.group === "Filters"
													? `${conversations.length}`
													: "↵"}
											</span>
										</CommandItem>
									);
								})}
							</CommandGroup>
						)}
					</CommandList>
				</Command>
				<div className="flex items-center gap-4 border-t border-border px-3 py-2 text-[0.65625rem] text-muted-foreground">
					<span>
						<span className="font-mono text-foreground">↵</span> run
					</span>
					<span>
						<span className="font-mono text-foreground">↑↓</span> move
					</span>
					<span>
						<span className="font-mono text-foreground">Esc</span> close
					</span>
					<span className="ml-auto rounded-full border border-border bg-muted px-2 py-0.5 font-mono">
						{visible.length} matches
					</span>
				</div>
			</div>
		</div>
	);
}

function fuzzyMatch(haystack: string, needle: string): boolean {
	if (haystack.includes(needle)) return true;
	let i = 0;
	for (const char of haystack) {
		if (char === needle[i]) i += 1;
		if (i === needle.length) return true;
	}
	return false;
}

function defaultIcon(_group: string) {
	return Inbox;
}
