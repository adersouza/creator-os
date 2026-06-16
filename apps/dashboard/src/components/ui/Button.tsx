import React from "react";
import { Button as ShadButton } from "@/components/shadcn/button";
import { cn } from "@/lib/utils";
import { haptics } from "@/utils/haptics";

type ShadButtonProps = React.ComponentProps<typeof ShadButton>;

interface ButtonProps extends Omit<ShadButtonProps, "variant" | "size" | "asChild"> {
	variant?:
		| "default"
		| "secondary"
		| "outline"
		| "ghost"
		| "danger"
		| undefined;
	size?: "sm" | "md" | "lg" | "icon" | undefined;
	asChild?: boolean | undefined;
	haptic?: "none" | "selection" | "success" | "warning" | "error" | undefined;
}

const VARIANT_MAP: Record<
	NonNullable<ButtonProps["variant"]>,
	NonNullable<ShadButtonProps["variant"]>
> = {
	default: "default",
	secondary: "secondary",
	outline: "outline",
	ghost: "ghost",
	danger: "destructive",
};

const SIZE_MAP: Record<
	NonNullable<ButtonProps["size"]>,
	NonNullable<ShadButtonProps["size"]>
> = {
	sm: "sm",
	md: "default",
	lg: "lg",
	icon: "icon",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
	(
		{
			className,
			variant = "default",
			size = "md",
			asChild = false,
			haptic = "none",
			onClick,
			disabled,
			...props
		},
		ref,
	) => {
		const handleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
			onClick?.(event);
			if (disabled || event.defaultPrevented || haptic === "none") return;
			if (haptic === "selection") haptics.selection();
			if (haptic === "success") haptics.success();
			if (haptic === "warning") haptics.warning();
			if (haptic === "error") haptics.error();
		};

		return (
			<ShadButton
				ref={ref}
				asChild={asChild}
				variant={VARIANT_MAP[variant]}
				size={SIZE_MAP[size]}
				disabled={disabled}
				onClick={handleClick}
				className={cn(
					"app-control-text app-interactive relative rounded-md font-medium transition-[background-color,border-color,color,box-shadow] duration-150 ease-out active:scale-[0.985] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
					"after:absolute after:left-1/2 after:top-1/2 after:h-full after:min-h-[44px] after:w-full after:min-w-[44px] after:-translate-x-1/2 after:-translate-y-1/2 after:content-['']",
					{
						"bg-primary text-primary-foreground shadow-sm hover:bg-[color-mix(in_srgb,var(--color-primary)_92%,var(--color-foreground))]":
							variant === "default",
						"border border-border bg-muted/55 text-foreground shadow-xs hover:bg-muted":
							variant === "secondary",
						"border border-border bg-card/60 text-foreground shadow-xs hover:bg-muted":
							variant === "outline",
						"bg-transparent text-muted-foreground hover:bg-muted hover:text-foreground":
							variant === "ghost",
						"bg-[var(--color-danger)] text-[var(--color-danger-foreground)] shadow-sm hover:bg-[color-mix(in_srgb,var(--color-danger)_88%,var(--color-foreground))]":
							variant === "danger",
						"h-8 px-3": size === "sm",
						"h-9 px-4": size === "md",
						"h-10 px-5": size === "lg",
						"h-10 w-10 p-0": size === "icon",
					},
					className,
				)}
				{...props}
			/>
		);
	},
);
Button.displayName = "Button";
