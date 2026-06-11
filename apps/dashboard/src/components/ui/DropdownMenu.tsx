import * as RDM from "@radix-ui/react-dropdown-menu";
import React from "react";
import { cn } from "@/lib/utils";

/**
 * DropdownMenu — thin Radix wrapper styled to match ContextMenu and Popover.
 * Radix handles focus management, keyboard navigation (↑↓ Home End type-ahead),
 * dismiss (outside click + Esc + Tab), and portaling. We add the glass shell
 * and color rules (destructive → semantic danger).
 *
 * Use this for menu-shaped surfaces (action lists, assignment pickers, row
 * action menus). For rich non-menu popovers (filter panels, form snippets),
 * use Popover instead.
 */

export const DropdownMenuRoot = RDM.Root;
export const DropdownMenuTrigger = RDM.Trigger;
export const DropdownMenuGroup = RDM.Group;
export const DropdownMenuPortal = RDM.Portal;
export const DropdownMenuSub = RDM.Sub;
export const DropdownMenuRadioGroup = RDM.RadioGroup;

const BASE_ITEM =
	"relative flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[0.8125rem] text-foreground cursor-default select-none outline-none " +
	"data-[highlighted]:bg-muted " +
	"data-[disabled]:text-muted-foreground data-[disabled]:pointer-events-none transition-colors";

export const DropdownMenuContent = React.forwardRef<
	React.ElementRef<typeof RDM.Content>,
	React.ComponentPropsWithoutRef<typeof RDM.Content>
>(function DropdownMenuContent(
	{ className, sideOffset = 6, collisionPadding = 8, ...props },
	ref,
) {
	return (
		<RDM.Portal>
			<RDM.Content
				ref={ref}
				sideOffset={sideOffset}
				collisionPadding={collisionPadding}
				className={cn(
					"composer-popover z-[95] min-w-[200px] p-1 rounded-[10px]",
					"data-[state=open]:animate-ctx-in",
					className,
				)}
				{...props}
			/>
		</RDM.Portal>
	);
});

export const DropdownMenuItem = React.forwardRef<
	React.ElementRef<typeof RDM.Item>,
	React.ComponentPropsWithoutRef<typeof RDM.Item> & {
		destructive?: boolean | undefined;
	}
>(function DropdownMenuItem({ className, destructive, ...props }, ref) {
	return (
		<RDM.Item
			ref={ref}
			className={cn(
				BASE_ITEM,
				destructive &&
					"text-[color:var(--color-danger)] data-[highlighted]:bg-[color-mix(in_srgb,var(--color-danger)_8%,transparent)] data-[highlighted]:text-[color:var(--color-danger)]",
				className,
			)}
			{...props}
		/>
	);
});

export const DropdownMenuSeparator = React.forwardRef<
	React.ElementRef<typeof RDM.Separator>,
	React.ComponentPropsWithoutRef<typeof RDM.Separator>
>(function DropdownMenuSeparator({ className, ...props }, ref) {
	return (
		<RDM.Separator
			ref={ref}
			className={cn("my-1 h-px bg-border opacity-70", className)}
			{...props}
		/>
	);
});

export const DropdownMenuLabel = React.forwardRef<
	React.ElementRef<typeof RDM.Label>,
	React.ComponentPropsWithoutRef<typeof RDM.Label>
>(function DropdownMenuLabel({ className, ...props }, ref) {
	return (
		<RDM.Label
			ref={ref}
			className={cn(
				"px-2.5 pt-2 pb-1 text-[0.625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground",
				className,
			)}
			{...props}
		/>
	);
});
