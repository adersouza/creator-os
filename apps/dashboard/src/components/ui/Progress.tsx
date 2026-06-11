import type * as React from "react";
import { Progress as ShadProgress } from "@/components/shadcn/progress";
import { cn } from "@/lib/utils";

export interface ProgressProps
	extends React.ComponentProps<typeof ShadProgress> {
	tone?: "default" | "good" | "warn" | "critical" | undefined;
}

const TONE_CLASS: Record<NonNullable<ProgressProps["tone"]>, string> = {
	default: "[&>div]:bg-[color:var(--color-oxblood)]",
	good: "[&>div]:bg-[color:var(--color-health-good)]",
	warn: "[&>div]:bg-[color:var(--color-health-warn)]",
	critical: "[&>div]:bg-[color:var(--color-critical)]",
};

export function Progress({
	className,
	tone = "default",
	value,
	...props
}: ProgressProps) {
	return (
		<ShadProgress
			value={value}
			className={cn(
				"h-1.5 bg-[color-mix(in_srgb,var(--color-foreground)_8%,transparent)]",
				TONE_CLASS[tone],
				className,
			)}
			{...props}
		/>
	);
}
