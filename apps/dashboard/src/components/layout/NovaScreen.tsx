import type React from "react";
import { cn } from "@/lib/utils";

export interface NovaScreenProps extends React.HTMLAttributes<HTMLDivElement> {
	width?: "default" | "wide" | "narrow" | "full" | undefined;
	density?: "default" | "compact" | undefined;
	mode?: "default" | "workflow" | "dense" | undefined;
}

const WIDTH_CLASS: Record<NonNullable<NovaScreenProps["width"]>, string> = {
	default: "max-w-[1440px]",
	wide: "max-w-[1560px]",
	narrow: "max-w-[1120px]",
	full: "max-w-none",
};

export function NovaScreen({
	mode = "default",
	width = mode === "workflow" ? "wide" : "default",
	density = mode === "dense" ? "compact" : "default",
	className,
	...props
}: NovaScreenProps) {
	return (
		<div
			className={cn(
				"nova-screen mx-auto flex w-full flex-col bg-background text-foreground",
				WIDTH_CLASS[width],
				density === "compact"
					? "gap-4 px-4 py-5 md:px-6"
					: "gap-6 px-4 py-6 md:px-8 md:py-8",
				className,
			)}
			{...props}
		/>
	);
}
