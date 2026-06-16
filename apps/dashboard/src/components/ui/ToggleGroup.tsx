import { ToggleGroup as ToggleGroupPrimitive } from "radix-ui";
import React from "react";
import { cn } from "@/lib/utils";

export const ToggleGroup = React.forwardRef<
	React.ElementRef<typeof ToggleGroupPrimitive.Root>,
	React.ComponentPropsWithoutRef<typeof ToggleGroupPrimitive.Root>
>(({ className, ...props }, ref) => (
	<ToggleGroupPrimitive.Root
		ref={ref}
		className={cn(
			"inline-flex max-w-full min-w-0 items-center overflow-x-auto rounded-full border border-border bg-card p-1 td-control-shadow",
			className,
		)}
		{...props}
	/>
));
ToggleGroup.displayName = ToggleGroupPrimitive.Root.displayName;

export const ToggleGroupItem = React.forwardRef<
	React.ElementRef<typeof ToggleGroupPrimitive.Item>,
	React.ComponentPropsWithoutRef<typeof ToggleGroupPrimitive.Item> & {
		sizeVariant?: "sm" | "md" | undefined;
	}
>(({ className, sizeVariant = "md", ...props }, ref) => (
	<ToggleGroupPrimitive.Item
		ref={ref}
		className={cn(
			"relative flex shrink-0 items-center justify-center rounded-full transition-colors",
			"focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-card)]",
			"disabled:pointer-events-none disabled:opacity-50",
			"data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:shadow-sm",
			sizeVariant === "sm"
				? "h-6 px-2.5 text-[0.625rem] font-semibold uppercase tracking-[0.08em]"
				: "app-control-text h-8 px-4",
			className,
		)}
		{...props}
	/>
));
ToggleGroupItem.displayName = ToggleGroupPrimitive.Item.displayName;
