import type React from "react";
import { Search } from "lucide-react";
import {
	CommandDialog,
	CommandEmpty,
	CommandGroup,
	CommandInput,
	CommandItem,
	CommandList,
	CommandShortcut,
} from "@/components/ui/Command";
import { Badge } from "@/components/ui/Badge";
import { Kbd } from "@/components/ui/Kbd";
import { cn } from "@/lib/utils";

export interface CommandMenuAction {
	id: string;
	label: React.ReactNode;
	description?: React.ReactNode | undefined;
	icon?: React.ReactNode | undefined;
	shortcut?: React.ReactNode | undefined;
	disabled?: boolean | undefined;
	onSelect: () => void;
	value?: string | undefined;
}

export interface CommandMenuGroup {
	id: string;
	heading?: React.ReactNode | undefined;
	items: CommandMenuAction[];
}

export interface CommandMenuShellProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	title?: React.ReactNode | undefined;
	description?: React.ReactNode | undefined;
	value?: string | undefined;
	onValueChange?: ((value: string) => void) | undefined;
	placeholder?: string | undefined;
	shortcut?: React.ReactNode | undefined;
	groups?: CommandMenuGroup[] | undefined;
	empty?: React.ReactNode | undefined;
	children?: React.ReactNode | undefined;
	footer?: React.ReactNode | undefined;
	listClassName?: string | undefined;
	inputRef?: React.Ref<HTMLInputElement> | undefined;
}

export function CommandMenuShell({
	open,
	onOpenChange,
	title = "Command menu",
	description,
	value,
	onValueChange,
	placeholder = "Search commands...",
	shortcut,
	groups,
	empty = "No command found.",
	children,
	footer,
	listClassName,
	inputRef,
}: CommandMenuShellProps) {
	return (
		<CommandDialog
			open={open}
			onOpenChange={onOpenChange}
			title={title}
			description={description}
		>
			<div className="command-menu-shell">
				<div className="relative border-b border-border">
					<CommandInput
						ref={inputRef}
						value={value ?? ""}
						onValueChange={onValueChange ?? (() => undefined)}
						placeholder={placeholder}
						className="h-12 pr-24"
					/>
					<div className="pointer-events-none absolute right-3 top-1/2 flex -translate-y-1/2 items-center gap-1.5">
						{shortcut ?? <Kbd>⌘K</Kbd>}
					</div>
				</div>
				<CommandList className={cn("max-h-[420px] overflow-y-auto p-2", listClassName)}>
					{children ??
						(groups && groups.length > 0 ? (
							groups.map((group, groupIndex) => (
								<CommandGroup
									key={group.id}
									heading={group.heading}
									className={groupIndex > 0 ? "mt-2" : undefined}
								>
									{group.items.map((item) => (
										<CommandItem
											key={item.id}
											value={item.value ?? item.id}
											disabled={item.disabled === true}
											onSelect={() => {
												if (!item.disabled) item.onSelect();
											}}
											className="command-menu-item px-2 py-2"
										>
											<CommandMenuActionRow
												icon={item.icon}
												label={item.label}
												description={item.description}
												shortcut={item.shortcut}
												disabled={item.disabled}
											/>
										</CommandItem>
									))}
								</CommandGroup>
							))
						) : (
							<CommandEmpty>{empty}</CommandEmpty>
						))}
				</CommandList>
				{footer ? (
					<div className="border-t border-border bg-muted/45 px-4 py-2">
						{footer}
					</div>
				) : null}
			</div>
		</CommandDialog>
	);
}

export function CommandMenuActionRow({
	icon,
	label,
	description,
	shortcut,
	disabled = false,
	className,
}: {
	icon?: React.ReactNode | undefined;
	label: React.ReactNode;
	description?: React.ReactNode | undefined;
	shortcut?: React.ReactNode | undefined;
	disabled?: boolean | undefined;
	className?: string | undefined;
}) {
	return (
		<div
			className={cn(
				"command-menu-action-row grid w-full min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3",
				disabled && "opacity-55",
				className,
			)}
		>
			<span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground">
				{icon ?? <Search data-icon="stacked" aria-hidden="true" />}
			</span>
			<span className="min-w-0">
				<span className="block truncate text-sm font-semibold text-foreground">
					{label}
				</span>
				{description ? (
					<span className="mt-0.5 block truncate text-xs text-muted-foreground">
						{description}
					</span>
				) : null}
			</span>
			{shortcut ? (
				typeof shortcut === "string" ? (
					<CommandShortcut>
						<Badge tone="outline">{shortcut}</Badge>
					</CommandShortcut>
				) : (
					<CommandShortcut>{shortcut}</CommandShortcut>
				)
			) : null}
		</div>
	);
}
