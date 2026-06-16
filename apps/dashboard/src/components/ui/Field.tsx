import type React from "react";
import {
	Field as ShadField,
	FieldDescription as ShadFieldDescription,
	FieldError as ShadFieldError,
	FieldGroup as ShadFieldGroup,
	FieldLabel as ShadFieldLabel,
	FieldSeparator as ShadFieldSeparator,
} from "@/components/shadcn/field";
import { cn } from "@/lib/utils";

export interface FieldProps extends Omit<React.ComponentProps<typeof ShadField>, "children"> {
	label?: React.ReactNode | undefined;
	hint?: React.ReactNode | undefined;
	error?: React.ReactNode | undefined;
	labelProps?: React.ComponentProps<typeof ShadFieldLabel> | undefined;
	hintProps?: React.ComponentProps<typeof ShadFieldDescription> | undefined;
	errorProps?: React.ComponentProps<typeof ShadFieldError> | undefined;
	children: React.ReactNode;
}

export function Field({
	label,
	hint,
	error,
	labelProps,
	hintProps,
	errorProps,
	children,
	className,
	...props
}: FieldProps) {
	return (
		<ShadField className={cn("gap-1.5", className)} {...props}>
			{label ? <FieldLabel {...labelProps}>{label}</FieldLabel> : null}
			{children}
			{error ? <FieldError {...errorProps}>{error}</FieldError> : null}
			{hint ? <FieldDescription {...hintProps}>{hint}</FieldDescription> : null}
		</ShadField>
	);
}

export function FieldGroup({
	className,
	...props
}: React.ComponentProps<typeof ShadFieldGroup>) {
	return <ShadFieldGroup className={cn("gap-4", className)} {...props} />;
}

export function FieldLabel({
	className,
	...props
}: React.ComponentProps<typeof ShadFieldLabel>) {
	return (
		<ShadFieldLabel
			className={cn(
				"mb-0 block w-fit text-[0.75rem] font-medium text-muted-foreground",
				className,
			)}
			{...props}
		/>
	);
}

export function FieldDescription({
	className,
	...props
}: React.ComponentProps<typeof ShadFieldDescription>) {
	return (
		<ShadFieldDescription
			className={cn("mt-0 text-[0.6875rem] leading-relaxed text-muted-foreground", className)}
			{...props}
		/>
	);
}

export function FieldSeparator({
	className,
	...props
}: React.ComponentProps<typeof ShadFieldSeparator>) {
	return (
		<ShadFieldSeparator
			className={cn(
				"*:data-[slot=field-separator-content]:bg-card",
				className,
			)}
			{...props}
		/>
	);
}

export function FieldError({
	className,
	...props
}: React.ComponentProps<typeof ShadFieldError>) {
	return (
		<ShadFieldError
			className={cn("mt-0 text-[0.6875rem] leading-relaxed text-[color:var(--color-danger)]", className)}
			{...props}
		/>
	);
}
