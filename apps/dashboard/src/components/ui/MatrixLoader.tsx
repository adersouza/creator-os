import type React from "react";
import { cn } from "@/lib/utils";

export interface MatrixLoaderProps extends React.HTMLAttributes<HTMLDivElement> {
	label?: string | undefined;
	size?: "sm" | "md" | "lg" | undefined;
	tone?: "default" | "muted" | "good" | "warn" | "critical" | undefined;
	active?: boolean | undefined;
}

const SIZE_CLASS: Record<NonNullable<MatrixLoaderProps["size"]>, string> = {
	sm: "h-5 w-10 gap-0.5",
	md: "h-6 w-14 gap-1",
	lg: "h-8 w-20 gap-1.5",
};

const CELL_CLASS: Record<NonNullable<MatrixLoaderProps["size"]>, string> = {
	sm: "h-1 w-1 rounded-[1px]",
	md: "h-1.5 w-1.5 rounded-[2px]",
	lg: "h-2 w-2 rounded-[2px]",
};

const TONE_CLASS: Record<NonNullable<MatrixLoaderProps["tone"]>, string> = {
	default: "bg-[color:var(--color-oxblood)]",
	muted: "bg-label-tertiary",
	good: "bg-[color:var(--color-health-good)]",
	warn: "bg-[color:var(--color-health-warn)]",
	critical: "bg-[color:var(--color-critical)]",
};

const CELLS = Array.from({ length: 15 }, (_, index) => index);

export function MatrixLoader({
	label = "Loading",
	size = "md",
	tone = "default",
	active = true,
	className,
	...props
}: MatrixLoaderProps) {
	return (
		<div
			role="status"
			aria-label={label}
			className={cn("inline-flex items-center", className)}
			{...props}
		>
			<span
				aria-hidden="true"
				className={cn(
					"grid grid-cols-5 place-items-center",
					SIZE_CLASS[size],
				)}
			>
				{CELLS.map((cell) => (
					<span
						key={cell}
						className={cn(
							CELL_CLASS[size],
							TONE_CLASS[tone],
							active ? "animate-pulse" : "opacity-35",
						)}
						style={{
							animationDelay: `${(cell % 5) * 90 + Math.floor(cell / 5) * 55}ms`,
							animationDuration: "900ms",
							opacity: active ? 0.18 + ((cell * 7) % 6) * 0.12 : undefined,
						}}
					/>
				))}
			</span>
			<span className="sr-only">{label}</span>
		</div>
	);
}
