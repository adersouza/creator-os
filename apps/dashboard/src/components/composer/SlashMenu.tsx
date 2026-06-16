import { useEffect, useMemo, useState } from "react";
import {
	Command,
	CommandEmpty,
	CommandGroup,
	CommandItem,
	CommandList,
	CommandShortcut,
} from "@/components/ui/Command";
import { CommandMenuActionRow } from "@/components/ui/CommandMenuShell";
import { cn } from "@/lib/utils";

export interface SlashCommand {
	id: string;
	label: string;
	hint: string;
	run: () => void;
}

export function SlashMenu({
	open,
	anchor,
	commands,
	onClose,
}: {
	open: boolean;
	anchor: { x: number; y: number } | null;
	commands: SlashCommand[];
	onClose: () => void;
}) {
	const [query, setQuery] = useState("");
	const [selected, setSelected] = useState(0);
	useEffect(() => {
		if (open) {
			setQuery("");
			setSelected(0);
		}
	}, [open]);

	const filtered = useMemo(() => {
		if (!query) return commands;
		return commands.filter(
			(command) =>
				command.id.includes(query) ||
				command.label.toLowerCase().includes(query),
		);
	}, [commands, query]);

	useEffect(() => {
		if (!open) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape" || event.key === " ") onClose();
			if (event.key === "Backspace") {
				setQuery((value) => value.slice(0, -1));
				setSelected(0);
			}
			if (event.key === "ArrowDown") {
				event.preventDefault();
				setSelected((value) => Math.min(filtered.length - 1, value + 1));
			}
			if (event.key === "ArrowUp") {
				event.preventDefault();
				setSelected((value) => Math.max(0, value - 1));
			}
			if (event.key === "Enter" && filtered[selected]) {
				event.preventDefault();
				filtered[selected].run();
				onClose();
			}
			if (/^[a-z]$/i.test(event.key)) {
				setQuery((value) => `${value}${event.key.toLowerCase()}`);
				setSelected(0);
			}
		};
		const onPointer = () => onClose();
		window.addEventListener("keydown", onKey);
		window.addEventListener("pointerdown", onPointer);
		return () => {
			window.removeEventListener("keydown", onKey);
			window.removeEventListener("pointerdown", onPointer);
		};
	}, [filtered, onClose, open, selected]);

	if (!open || !anchor) return null;
	return (
		<Command
			aria-label="Slash commands"
			shouldFilter={false}
			className="command-menu-shell fixed z-[120] h-auto w-80 max-w-[calc(100vw-24px)] rounded-xl border border-border bg-card p-1 shadow-lg"
			style={{ left: anchor.x, top: anchor.y }}
			onPointerDown={(event) => event.stopPropagation()}
		>
			<div className="px-2 py-1.5 flex items-center justify-between gap-2">
				<span className="text-[0.65625rem] uppercase tracking-[0.12em] text-muted-foreground">
					Slash commands
				</span>
				{query && (
					<CommandShortcut className="ml-0 font-mono text-[0.65625rem]">
						/{query}
					</CommandShortcut>
				)}
			</div>
			<CommandList className="max-h-[280px] overflow-y-auto p-0">
				{filtered.length === 0 ? (
					<CommandEmpty className="px-2 py-3 text-left text-[0.75rem]">
						No command matches /{query}
					</CommandEmpty>
				) : (
					<CommandGroup>
						{filtered.map((command, index) => (
							<CommandItem
								key={command.id}
								value={command.id}
								onMouseEnter={() => setSelected(index)}
								onSelect={() => {
									command.run();
									onClose();
								}}
								className={cn(
									"rounded-lg px-2 py-2",
									selected === index && "bg-muted text-foreground",
								)}
							>
								<CommandMenuActionRow
									label={command.label}
									description={command.hint}
									shortcut={`/${command.id}`}
								/>
							</CommandItem>
						))}
					</CommandGroup>
				)}
			</CommandList>
		</Command>
	);
}
