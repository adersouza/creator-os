import type * as React from "react";
import {
	ContextMenu as ShadContextMenu,
	ContextMenuContent as ShadContextMenuContent,
	ContextMenuGroup as ShadContextMenuGroup,
	ContextMenuItem as ShadContextMenuItem,
	ContextMenuLabel as ShadContextMenuLabel,
	ContextMenuPortal as ShadContextMenuPortal,
	ContextMenuSeparator as ShadContextMenuSeparator,
	ContextMenuSub as ShadContextMenuSub,
	ContextMenuTrigger as ShadContextMenuTrigger,
} from "@/components/shadcn/context-menu";
import { cn } from "@/lib/utils";

/**
 * ContextMenu keeps the app's legacy composer-popover shell while delegating
 * behavior and source shape to the generated shadcn/Radix primitive.
 */
export const ContextMenuRoot = ShadContextMenu;
export const ContextMenuTrigger = ShadContextMenuTrigger;
export const ContextMenuGroup = ShadContextMenuGroup;
export const ContextMenuPortal = ShadContextMenuPortal;
export const ContextMenuSub = ShadContextMenuSub;

const BASE_ITEM =
	"relative flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[0.8125rem] text-foreground cursor-default select-none outline-none " +
	"data-[highlighted]:bg-muted data-[selected=true]:bg-muted " +
	"data-[disabled]:text-muted-foreground data-[disabled]:pointer-events-none transition-colors";

export function ContextMenuContent({
	className,
	collisionPadding = 8,
	...props
}: React.ComponentProps<typeof ShadContextMenuContent>) {
	return (
		<ShadContextMenuContent
			collisionPadding={collisionPadding}
			className={cn(
				"composer-popover z-[95] min-w-[200px] rounded-[10px] border-border bg-card p-1 text-foreground",
				"data-[state=open]:animate-ctx-in",
				className,
			)}
			{...props}
		/>
	);
}

export function ContextMenuItem({
	className,
	destructive,
	...props
}: React.ComponentProps<typeof ShadContextMenuItem> & {
	destructive?: boolean | undefined;
}) {
	return (
		<ShadContextMenuItem
			className={cn(
				BASE_ITEM,
				destructive &&
					"text-[color:var(--color-danger)] data-[highlighted]:bg-[color-mix(in_srgb,var(--color-danger)_8%,transparent)] data-[highlighted]:text-[color:var(--color-danger)] data-[selected=true]:bg-[color-mix(in_srgb,var(--color-danger)_8%,transparent)] data-[selected=true]:text-[color:var(--color-danger)]",
				className,
			)}
			{...props}
		/>
	);
}

export function ContextMenuSeparator({
	className,
	...props
}: React.ComponentProps<typeof ShadContextMenuSeparator>) {
	return (
		<ShadContextMenuSeparator
			className={cn("my-1 h-px bg-border opacity-70", className)}
			{...props}
		/>
	);
}

export function ContextMenuLabel({
	className,
	...props
}: React.ComponentProps<typeof ShadContextMenuLabel>) {
	return (
		<ShadContextMenuLabel
			className={cn(
				"px-2.5 pt-2 pb-1 text-[0.625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground",
				className,
			)}
			{...props}
		/>
	);
}
