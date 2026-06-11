import {
	forwardRef,
	type ButtonHTMLAttributes,
	type ComponentProps,
	type ReactNode,
} from "react";
import { motion } from "motion/react";
import { ChevronDown } from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * FilterChip — canonical pill trigger for filter bars.
 *
 * Single shell: h-8 rounded-full border bg-card. Consumers slot an optional
 * leading icon, optional trailing chevron (for dropdowns) or kbd hint (for
 * shortcut affordances), and optional active state (selected border/text).
 * Spring-on-hover via motion — subtle 1px lift, no flash.
 *
 * Why a primitive: Analytics filter bar alone had 7 hand-rolled copies of
 * this shell (DateRange, Breakdown, Cohort, Export, Share, compare toggle,
 * HeroTile pin). Size drift (px-3 vs px-3.5, h-8 vs py-1) meant every chip
 * looked *almost* the same. One source of truth fixes that.
 */

// Omit the React drag/animation handlers that conflict with Framer Motion's.
type ButtonPropsSansMotionConflicts = Omit<
	ButtonHTMLAttributes<HTMLButtonElement>,
	| "children"
	| "onDrag"
	| "onDragStart"
	| "onDragEnd"
	| "onAnimationStart"
	| "onAnimationEnd"
	| "onAnimationIteration"
>;

interface FilterChipProps extends ButtonPropsSansMotionConflicts {
	/** Leading icon. Rendered at h-3.5 w-3.5. */
	icon?: LucideIcon | undefined;
	/** Label text or rich children. */
	children: ReactNode;
	/** Trailing chevron — indicates dropdown. Mutually exclusive with `kbd`. */
	chevron?: boolean | undefined;
	/** Trailing keyboard hint badge — e.g. "D", "⌘K". Mutually exclusive with `chevron`. */
	kbd?: string | undefined;
	/** Active/selected state. Selected border + text. */
	active?: boolean | undefined;
	/** Tone override — oxblood maps to selected styling regardless of `active`. */
	tone?: "default" | "oxblood" | undefined;
}
type MotionButtonStyle = NonNullable<
	ComponentProps<typeof motion.button>["style"]
>;

export const FilterChip = forwardRef<HTMLButtonElement, FilterChipProps>(
	function FilterChip(
		{
			icon: Icon,
			children,
			chevron = false,
			kbd,
			active = false,
			tone = "default",
			className = "",
			disabled,
			style,
			...rest
		},
		ref,
	) {
		const toneClass =
			active || tone === "oxblood"
				? "border-[var(--color-selected)] text-[var(--color-selected)] bg-card"
				: "border-border bg-card text-muted-foreground hover:text-foreground";

		return (
			<motion.button
				ref={ref}
				type="button"
				transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
				disabled={disabled}
				aria-pressed={active}
				className={`inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-full border h-8 px-3 text-[0.75rem] font-medium transition-colors shadow-[inset_0_1px_0_color-mix(in_srgb,var(--color-card)_50%,transparent),0_1px_2px_color-mix(in_srgb,var(--color-foreground)_2%,transparent)] dark:shadow-[inset_0_1px_0_color-mix(in_srgb,var(--color-card)_4%,transparent)] disabled:opacity-50 disabled:cursor-not-allowed outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] focus-visible:ring-offset-2 focus-visible:ring-offset-background ${toneClass} ${className}`}
				{...(!disabled ? { whileHover: { y: -1 }, whileTap: { y: 0 } } : {})}
				{...(style ? { style: style as MotionButtonStyle } : {})}
				{...rest}
			>
				{Icon && <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
				<span className="truncate">{children}</span>
				{chevron && (
					<ChevronDown
						className="h-3 w-3 shrink-0 opacity-70"
						aria-hidden="true"
					/>
				)}
				{kbd && (
					<kbd className="ml-0.5 rounded border border-border px-1 py-[1px] font-mono text-[0.5rem] leading-none text-muted-foreground">
						{kbd}
					</kbd>
				)}
			</motion.button>
		);
	},
);
