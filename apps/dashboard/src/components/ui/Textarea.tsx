import React from "react";
import { Textarea as ShadTextarea } from "@/components/shadcn/textarea";
import { cn } from "@/lib/utils";
import {
	inputControlClass,
	inputDefaultToneClass,
	inputInvalidToneClass,
} from "./Input";

export interface TextareaProps
	extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
	tone?: "default" | "invalid" | undefined;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
	({ className, tone = "default", ...props }, ref) => {
		const ariaInvalid =
			props["aria-invalid"] ?? (tone === "invalid" ? true : undefined);

		return (
			<ShadTextarea
				ref={ref}
				aria-invalid={ariaInvalid}
				className={cn(
					inputControlClass,
					tone === "invalid" ? inputInvalidToneClass : inputDefaultToneClass,
					"min-h-24 px-3 py-2 text-base leading-relaxed md:text-[0.8125rem]",
					"resize-y",
					className,
				)}
				{...props}
			/>
		);
	},
);
Textarea.displayName = "Textarea";
