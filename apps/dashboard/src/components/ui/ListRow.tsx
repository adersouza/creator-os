import React from "react";
import { cn } from "@/lib/utils";

/**
 * ListRow — the shared primitive for 2-pane list surfaces (Inbox, Reports,
 * SmartLinks, Autopilot failures). Before this existed, each page rolled
 * its own `border-l px-4 py-3 focus-visible:ring-2 …` block with slightly
 * different paddings and hover/focus tokens. The /critique pass flagged
 * the drift as a consistency issue.
 *
 * Locked defaults (do not override via className unless you know what you're
 * doing):
 *   - py-3 px-4 (medium density)
 *   - border-l + border-b separators, last:border-b-0
 *   - hover + focus-visible tints at CLAUDE.md alpha values
 *   - active state: inline-styled left border color via `accentColor`
 *
 * Pass `selected` for the active row. Pass `accentColor` to tint the 1px
 * left border on the selected row (defaults to oxblood).
 */
export interface ListRowProps
	extends Omit<React.HTMLAttributes<HTMLDivElement>, "onClick"> {
	selected?: boolean | undefined;
	accentColor?: string | undefined;
	density?: "compact" | "medium" | "comfortable" | undefined;
	/** Render the 1px bottom separator between rows. Default true. Set false
	 *  for lists that have their own internal separation (e.g. Inbox's card
	 *  shell draws its own dividers). */
	separator?: boolean | undefined;
	/** Add `active:bg-*` press-down feedback. Default false. Opt in for
	 *  lists surfaced on touch devices where the tap target wants a
	 *  visible pressed state (e.g. mobile Inbox conversation list). */
	pressFeedback?: boolean | undefined;
	onClick?: () => void;
	children: React.ReactNode;
}

const DENSITY_CLASS: Record<NonNullable<ListRowProps["density"]>, string> = {
	compact: "px-3 py-3",
	medium: "px-4 py-3",
	comfortable: "px-5 py-3.5",
};

export const ListRow = React.forwardRef<HTMLDivElement, ListRowProps>(
	function ListRow(
		{
			selected = false,
			accentColor,
			density = "medium",
			separator = true,
			pressFeedback = false,
			onClick,
			className,
			children,
			...rest
		},
		ref,
	) {
		const style: React.CSSProperties | undefined = selected
			? ({
					"--row-accent": accentColor ?? "var(--color-oxblood)",
				} as React.CSSProperties)
			: undefined;

		return (
			<div
				ref={ref}
				role={onClick ? "button" : undefined}
				tabIndex={onClick ? 0 : undefined}
				onClick={onClick}
				onKeyDown={
					onClick
						? (e) => {
								if (e.key === "Enter" || e.key === " ") {
									e.preventDefault();
									onClick();
								}
							}
						: undefined
				}
				className={cn(
					"app-interactive group relative border-l-2 border-l-transparent transition-colors outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] focus-visible:ring-offset-1 focus-visible:ring-offset-background",
					DENSITY_CLASS[density],
					separator && "border-b border-b-border last:border-b-0",
					onClick && "cursor-pointer",
					pressFeedback && "active:bg-muted",
					"focus-visible:bg-muted",
					"focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-ring-oxblood)]",
					selected
						? "border-l-[var(--row-accent)] bg-muted"
						: "hover:bg-muted",
					className,
				)}
				style={style}
				{...rest}
			>
				{children}
			</div>
		);
	},
);
