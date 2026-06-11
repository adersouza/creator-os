import {
	forwardRef,
	type ButtonHTMLAttributes,
	type ComponentProps,
	type ReactNode,
} from "react";
import { motion } from "motion/react";

/**
 * TogglePill — standalone pill button with on/off state. For strips of
 * filter toggles where positions are meaningful but the control is NOT
 * a connected segmented group (those use <PillSegmented>).
 *
 * Two active variants:
 *   filled — bg-foreground / text-background (default; used for tab-style strips)
 *   ox     — selected/live tint (used for "unread only" / highlighted toggles)
 *
 * Consolidates five hand-rolled implementations across Inbox.tsx and
 * AnalyticsMobileLayout.tsx that had drifted to h-8 vs h-9 with subtly
 * different padding and hover states.
 */

// Omit React drag/animation handlers that conflict with Framer Motion's.
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

interface TogglePillProps extends ButtonPropsSansMotionConflicts {
	active: boolean;
	/** Visual treatment when active. Default is "filled". */
	variant?: "filled" | "ox" | undefined;
	/** Optional left content — dot, count, icon. */
	leading?: ReactNode | undefined;
	/** Optional right content — count badges etc. */
	trailing?: ReactNode | undefined;
	children: ReactNode;
}
type MotionButtonStyle = NonNullable<
	ComponentProps<typeof motion.button>["style"]
>;

export const TogglePill = forwardRef<HTMLButtonElement, TogglePillProps>(
	function TogglePill(
		{
			active,
			variant = "filled",
			leading,
			trailing,
			children,
			className = "",
			disabled,
			style,
			...rest
		},
		ref,
	) {
		const activeClass =
			variant === "ox"
				? "border bg-[color-mix(in_srgb,var(--color-selected)_8%,transparent)] border-[color-mix(in_srgb,var(--color-selected)_25%,transparent)]"
				: "bg-foreground text-background border border-transparent";
		const inactiveClass =
			"bg-card border border-border text-muted-foreground hover:text-foreground active:bg-muted";
		const mergedStyle =
			active && variant === "ox"
				? { color: "var(--color-selected)", ...style }
				: style;

		return (
			<motion.button
				ref={ref}
				type="button"
				aria-pressed={active}
				transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
				disabled={disabled}
				className={`app-control-text h-10 md:h-8 px-3.5 md:px-3 rounded-full inline-flex items-center gap-1.5 whitespace-nowrap transition-colors shrink-0 outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-50 disabled:cursor-not-allowed ${
					active ? activeClass : inactiveClass
				} ${className}`}
				{...(!disabled
					? { whileHover: { y: -1 }, whileTap: { scale: 0.97 } }
					: {})}
				{...(mergedStyle ? { style: mergedStyle as MotionButtonStyle } : {})}
				{...rest}
			>
				{leading}
				<span>{children}</span>
				{trailing}
			</motion.button>
		);
	},
);
