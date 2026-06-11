import React from "react";
import { Input as ShadInput } from "@/components/shadcn/input";
import { cn } from "@/lib/utils";

/**
 * Primitive input. Matches the inline recipe that's been copy-pasted across
 * Settings, Team, Composer, Auth — selected focus ring
 * and border swap. Use `leadingIcon` for search/mail glyphs so callers stop
 * hand-rolling absolute-positioned SVGs.
 */
export interface InputProps
	extends React.InputHTMLAttributes<HTMLInputElement> {
	/** Visual size token. Default 'md' → h-9. */
	sizeVariant?: "sm" | "md" | "lg" | undefined;
	/** Left-side icon (lucide-react svg). */
	leadingIcon?: React.ReactNode | undefined;
	/** Right-side adornment (clear button, chip count, etc.). */
	trailing?: React.ReactNode | undefined;
	/** Tone: 'default' uses border-border; 'invalid' uses semantic danger. */
	tone?: "default" | "invalid" | undefined;
}

// Mobile uses 16px (`text-base`) to suppress iOS Safari's auto-zoom on
// focus — anything < 16px triggers it. Desktop overrides back to the
// compact size.
export const inputHeightClass: Record<NonNullable<InputProps["sizeVariant"]>, string> = {
	sm: "h-8 text-base md:text-[0.75rem]",
	md: "h-9 text-base md:text-[0.8125rem]",
	lg: "h-10 text-base md:text-[0.84375rem]",
};

export const inputControlClass = cn(
	"w-full rounded-md border bg-muted/45 text-foreground placeholder:text-muted-foreground tabular-nums shadow-xs",
	"outline-none transition-[background-color,border-color,box-shadow]",
	"focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] disabled:cursor-not-allowed disabled:opacity-50",
);

export const inputDefaultToneClass =
	"border-border focus-visible:border-[color:var(--color-selected)]";

export const inputInvalidToneClass =
	"border-[color:var(--color-danger)] focus-visible:border-[color:var(--color-danger)]";

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
	(
		{
			className,
			sizeVariant = "md",
			leadingIcon,
			trailing,
			tone = "default",
			...rest
		},
		ref,
	) => {
		const ariaInvalid =
			rest["aria-invalid"] ?? (tone === "invalid" ? true : undefined);
		const input = (
			<ShadInput
				ref={ref}
				aria-invalid={ariaInvalid}
				className={cn(
					inputControlClass,
					"px-3",
					tone === "invalid"
						? inputInvalidToneClass
						: inputDefaultToneClass,
					inputHeightClass[sizeVariant],
					leadingIcon && "pl-8",
					trailing && "pr-8",
					className,
				)}
				{...rest}
			/>
		);

		if (!leadingIcon && !trailing) return input;

		return (
			<div className="relative w-full">
				{leadingIcon && (
					<span
						className="pointer-events-none absolute left-3 top-1/2 inline-flex -translate-y-1/2 items-center text-muted-foreground"
						aria-hidden="true"
					>
						{leadingIcon}
					</span>
				)}
				{input}
				{trailing && (
					<span className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex items-center">
						{trailing}
					</span>
				)}
			</div>
		);
	},
);
Input.displayName = "Input";
