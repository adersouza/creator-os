import React from "react";
import { Switch as ShadSwitch } from "@/components/shadcn/switch";
import { cn } from "@/lib/utils";

export const Switch = React.forwardRef<
	React.ElementRef<typeof ShadSwitch>,
	React.ComponentPropsWithoutRef<typeof ShadSwitch>
>(({ className, ...props }, ref) => (
	<ShadSwitch
		ref={ref}
		className={cn(
			"relative h-5 w-[34px] shrink-0 rounded-full",
			"bg-[color-mix(in_srgb,var(--color-foreground)_12%,transparent)] dark:bg-[color-mix(in_srgb,var(--color-card)_14%,transparent)]",
			"data-[state=checked]:bg-[color:var(--color-oxblood)]",
			"outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-50",
			"focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood-strong)]",
			className,
		)}
		{...props}
	/>
));
Switch.displayName = ShadSwitch.displayName;
