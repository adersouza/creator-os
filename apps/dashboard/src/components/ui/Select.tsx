import React from "react";
import { cn } from "@/lib/utils";
import {
	inputControlClass,
	inputDefaultToneClass,
	inputHeightClass,
	inputInvalidToneClass,
} from "./Input";

export interface SelectOption<T extends string = string> {
	value: T;
	label: React.ReactNode;
	disabled?: boolean | undefined;
}

export interface SelectProps<T extends string = string>
	extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size"> {
	options?: SelectOption<T>[] | undefined;
	sizeVariant?: "sm" | "md" | "lg" | undefined;
	tone?: "default" | "invalid" | undefined;
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
	(
		{
			className,
			children,
			options,
			sizeVariant = "md",
			tone = "default",
			...props
		},
		ref,
	) => {
		const ariaInvalid =
			props["aria-invalid"] ?? (tone === "invalid" ? true : undefined);

		return (
			<select
				ref={ref}
				aria-invalid={ariaInvalid}
				className={cn(
					inputControlClass,
					tone === "invalid" ? inputInvalidToneClass : inputDefaultToneClass,
					inputHeightClass[sizeVariant],
					"appearance-none px-3 pr-8",
					className,
				)}
				{...props}
			>
				{options
					? options.map((option) => (
							<option
								key={option.value}
								value={option.value}
								disabled={option.disabled}
							>
								{option.label}
							</option>
						))
					: children}
			</select>
		);
	},
);
Select.displayName = "Select";
