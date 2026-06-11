import type React from "react";
import { Badge as ShadBadge } from "@/components/shadcn/badge";
import { cn } from "@/lib/utils";

export type BadgeTone = "default" | "secondary" | "outline" | "danger" | "oxblood";

export interface BadgeProps extends React.ComponentProps<typeof ShadBadge> {
	tone?: BadgeTone | undefined;
}

const TONE_VARIANT: Record<BadgeTone, React.ComponentProps<typeof ShadBadge>["variant"]> = {
	default: "default",
	secondary: "secondary",
	outline: "outline",
	danger: "destructive",
	oxblood: "outline",
};

export function Badge({ tone = "secondary", className, ...props }: BadgeProps) {
	return (
		<ShadBadge
			variant={TONE_VARIANT[tone]}
			className={cn(
				"app-control-text inline-flex items-center gap-1 whitespace-nowrap",
				tone === "oxblood" &&
					"border-[color-mix(in_srgb,var(--color-oxblood)_28%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-oxblood)_10%,transparent)] text-[color:var(--color-oxblood)]",
				className,
			)}
			{...props}
		/>
	);
}
