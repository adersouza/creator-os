import React from "react";
import { Checkbox as ShadCheckbox } from "@/components/shadcn/checkbox";
import { cn } from "@/lib/utils";

export const Checkbox = React.forwardRef<
	React.ElementRef<typeof ShadCheckbox>,
	React.ComponentPropsWithoutRef<typeof ShadCheckbox>
>(({ className, ...props }, ref) => (
	<ShadCheckbox
		ref={ref}
		className={cn(
			"grid size-4 shrink-0 place-content-center rounded border border-border bg-card text-primary-foreground",
			"transition-colors data-[state=checked]:border-primary data-[state=checked]:bg-primary",
			"focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]",
			"disabled:cursor-not-allowed disabled:opacity-50",
			className,
		)}
		{...props}
	/>
));
Checkbox.displayName = ShadCheckbox.displayName;
