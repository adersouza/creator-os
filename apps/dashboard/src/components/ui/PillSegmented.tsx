import { motion } from "motion/react";
import { useId, type Dispatch, type SetStateAction } from "react";

export interface PillSegmentedOption<T extends string> {
	id: T;
	label: string;
}

interface PillSegmentedProps<T extends string> {
	options: PillSegmentedOption<T>[];
	value: T;
	/** Either a React setState dispatcher or a plain handler. */
	onChange: Dispatch<SetStateAction<T>> | ((id: T) => void);
	ariaLabel: string;
	size?: "sm" | "md" | undefined;
}

/**
 * Pill-shaped segmented control. Active segment is a selected pill that slides
 * between positions via framer-motion layoutId. Shared between Dashboard and
 * Analytics so platform switchers read identically on both pages.
 *
 * 2026 polish: each segment scales down on tap (98%) and pops back, active
 * pill has a faint inner highlight + outer selected glow, container has
 * subtle inner shadow so the pill reads as "recessed track."
 */
export function PillSegmented<T extends string>({
	options,
	value,
	onChange,
	ariaLabel,
	size = "md",
}: PillSegmentedProps<T>) {
	const layoutId = useId();
	const sizing =
		size === "sm"
			? {
					container: "p-0.5",
					button: "h-6 px-2.5",
					font: "text-[0.625rem] font-semibold uppercase tracking-[0.08em]",
				}
			: { container: "p-1", button: "h-8 px-4", font: "app-control-text" };

	return (
		<div
			role="radiogroup"
			aria-label={ariaLabel}
			className={`inline-flex max-w-full min-w-0 items-center overflow-x-auto rounded-full ${sizing.container} bg-card border border-border td-control-shadow`}
		>
			{options.map((opt) => {
				const active = opt.id === value;
				return (
					<motion.button
						key={opt.id}
						type="button"
						role="radio"
						onClick={() => onChange(opt.id)}
						aria-checked={active}
						whileTap={{ scale: 0.96 }}
						transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
						className={`relative ${sizing.button} flex shrink-0 items-center justify-center rounded-full ${sizing.font} transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-card)]`}
						style={{
							color: active
								? "var(--color-primary-foreground)"
								: "var(--color-muted-foreground)",
						}}
					>
						{active && (
							<motion.span
								layoutId={layoutId}
								className="absolute inset-0 rounded-full"
								transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
								style={{
									background: "var(--color-primary)",
									boxShadow:
										"0 1px 2px color-mix(in srgb, var(--color-foreground) 20%, transparent), inset 0 1px 0 color-mix(in srgb, var(--color-primary-foreground) 18%, transparent), 0 0 0 1px color-mix(in srgb, var(--color-primary) 35%, transparent)",
								}}
								aria-hidden="true"
							/>
						)}
						<span className="relative">{opt.label}</span>
					</motion.button>
				);
			})}
		</div>
	);
}
