import type { ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

export interface MobileSegmentedOption<TId extends string = string> {
	id: TId;
	label: ReactNode;
	trailing?: ReactNode;
}

interface MobileSegmentedProps<TId extends string> {
	value: TId;
	onChange: (id: TId) => void;
	options: MobileSegmentedOption<TId>[];
	ariaLabel: string;
	/**
	 * `pill` — rounded full-pill row (Dashboard mobile platform / timeframe).
	 * `segmented` — boxed iOS-style segmented control (Calendar mobile platform).
	 * `tab` — borderless small pill row (timeframe-style buttons).
	 */
	variant?: "pill" | "segmented" | "tab";
	className?: string | undefined;
	scrollOnOverflow?: boolean;
}

export function MobileSegmented<TId extends string>({
	value,
	onChange,
	options,
	ariaLabel,
	variant = "pill",
	className,
	scrollOnOverflow = true,
}: MobileSegmentedProps<TId>) {
	if (variant === "segmented") {
		return (
			<div
				role="group"
				aria-label={ariaLabel}
				className={cn(
					"inline-flex items-center rounded-md border border-border bg-card p-0.5 gap-0.5 shrink-0 min-h-11",
					className,
				)}
			>
				{options.map((opt) => {
					const isActive = opt.id === value;
					return (
						<Button
							key={opt.id}
							type="button"
							variant={isActive ? "default" : "ghost"}
							onClick={() => onChange(opt.id)}
							aria-pressed={isActive}
							className={cn(
								"h-11 px-2.5 rounded text-[0.71875rem] font-medium transition-colors whitespace-nowrap",
								isActive
									? "bg-foreground text-background"
									: "text-muted-foreground",
							)}
						>
							{opt.label}
							{opt.trailing}
						</Button>
					);
				})}
			</div>
		);
	}

	if (variant === "tab") {
		return (
			<div
				role="group"
				aria-label={ariaLabel}
				className={cn(
					"mobile-timeframe-pills flex items-center gap-1 min-h-11",
					className,
				)}
			>
				{options.map((opt) => {
					const isActive = opt.id === value;
					return (
						<Button
							key={opt.id}
							type="button"
							variant={isActive ? "default" : "ghost"}
							onClick={() => onChange(opt.id)}
							aria-pressed={isActive}
							className={cn(
								"px-3 h-11 sm:h-8 rounded-md text-[0.75rem] font-semibold transition-colors tabular-nums active:scale-[0.97] outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]",
								isActive
									? "bg-primary text-primary-foreground"
									: "text-muted-foreground",
							)}
						>
							{opt.label}
							{opt.trailing}
						</Button>
					);
				})}
			</div>
		);
	}

	// pill variant (default)
	return (
		<div
			role="group"
			aria-label={ariaLabel}
			className={cn(
				"mobile-segmented flex items-center gap-1.5 min-h-11",
				scrollOnOverflow && "overflow-x-auto scrollbar-hide -mx-1 px-1",
				className,
			)}
			style={
				scrollOnOverflow
					? { WebkitOverflowScrolling: "touch", scrollbarWidth: "none" }
					: undefined
			}
		>
			{options.map((opt) => {
				const isActive = opt.id === value;
				return (
					<Button
						key={opt.id}
						type="button"
						variant={isActive ? "default" : "ghost"}
						onClick={() => onChange(opt.id)}
						aria-pressed={isActive}
						className={cn(
							"shrink-0 px-3.5 h-11 sm:h-9 rounded-full text-[0.75rem] font-medium transition-colors whitespace-nowrap border active:scale-[0.97] outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]",
							isActive
								? "bg-primary text-primary-foreground border-primary"
								: "bg-card text-muted-foreground border-border",
						)}
					>
						{opt.label}
						{opt.trailing}
					</Button>
				);
			})}
		</div>
	);
}
