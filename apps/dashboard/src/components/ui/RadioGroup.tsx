import React from "react";
import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import { Circle } from "lucide-react";
import { cn } from "@/lib/utils";

export const RadioGroup = React.forwardRef<
	React.ElementRef<typeof RadioGroupPrimitive.Root>,
	React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Root>
>(({ className, ...props }, ref) => (
	<RadioGroupPrimitive.Root
		ref={ref}
		className={cn("grid gap-2", className)}
		{...props}
	/>
));
RadioGroup.displayName = RadioGroupPrimitive.Root.displayName;

export const RadioGroupItem = React.forwardRef<
	React.ElementRef<typeof RadioGroupPrimitive.Item>,
	React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Item>
>(({ className, ...props }, ref) => (
	<RadioGroupPrimitive.Item
		ref={ref}
		className={cn(
			"grid size-4 shrink-0 place-content-center rounded-full border border-border bg-card text-primary",
			"transition-colors data-[state=checked]:border-primary",
			"focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]",
			"disabled:cursor-not-allowed disabled:opacity-50",
			className,
		)}
		{...props}
	>
		<RadioGroupPrimitive.Indicator className="grid place-content-center text-current">
			<Circle className="size-2 fill-current" aria-hidden="true" />
		</RadioGroupPrimitive.Indicator>
	</RadioGroupPrimitive.Item>
));
RadioGroupItem.displayName = RadioGroupPrimitive.Item.displayName;
