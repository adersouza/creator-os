import React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

interface Props extends React.ButtonHTMLAttributes<HTMLButtonElement> {
	/** Drives both the `aria-label` and the tooltip text. */
	label: string;
	side?: "top" | "bottom" | "left" | "right" | undefined;
	children: React.ReactNode;
}

/**
 * Icon-only button with Radix Tooltip + 44pt hit region baked in.
 * Assumes a <TooltipProvider> is mounted above (Layout.tsx root covers it).
 */
export const IconTooltipButton = React.forwardRef<HTMLButtonElement, Props>(
	function IconTooltipButton(
		{ label, side = "bottom", children, className, ...rest },
		ref,
	) {
		return (
			<TooltipPrimitive.Root>
				<TooltipPrimitive.Trigger asChild>
					<Button
						ref={ref}
						variant="ghost"
						size="icon"
						type="button"
						aria-label={label}
						className={cn(
							"app-icon-button min-w-11 min-h-11 rounded-md disabled:cursor-not-allowed disabled:opacity-50",
							className,
						)}
						{...rest}
					>
						{children}
					</Button>
				</TooltipPrimitive.Trigger>
				<TooltipPrimitive.Portal>
					<TooltipPrimitive.Content
						side={side}
						sideOffset={6}
						className="z-[90] rounded-md bg-primary text-primary-foreground px-2.5 py-1.5 text-[0.6875rem] font-medium shadow-md animate-in fade-in-0 zoom-in-95"
					>
						{label}
						<TooltipPrimitive.Arrow className="fill-primary" />
					</TooltipPrimitive.Content>
				</TooltipPrimitive.Portal>
			</TooltipPrimitive.Root>
		);
	},
);
