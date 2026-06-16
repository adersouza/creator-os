import React from "react";
import {
	Controller,
	FormProvider,
	useFormContext,
	type Control,
	type ControllerFieldState,
	type ControllerRenderProps,
	type FieldPath,
	type FieldValues,
	type SubmitHandler,
	type UseFormReturn,
} from "react-hook-form";
import { Checkbox } from "@/components/ui/Checkbox";
import { Field } from "@/components/ui/Field";
import { Input, type InputProps } from "@/components/ui/Input";
import { Select, type SelectOption, type SelectProps } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";
import { Textarea, type TextareaProps } from "@/components/ui/Textarea";
import { cn } from "@/lib/utils";

export interface FormProps<TFieldValues extends FieldValues>
	extends Omit<React.FormHTMLAttributes<HTMLFormElement>, "onSubmit"> {
	form: UseFormReturn<TFieldValues>;
	onSubmit: SubmitHandler<TFieldValues>;
}

export function Form<TFieldValues extends FieldValues>({
	form,
	onSubmit,
	children,
	className,
	...props
}: FormProps<TFieldValues>) {
	return (
		<FormProvider {...form}>
			<form
				noValidate
				className={cn("flex flex-col gap-4", className)}
				onSubmit={form.handleSubmit(onSubmit)}
				{...props}
			>
				{children}
			</form>
		</FormProvider>
	);
}

export interface FormFieldRenderProps<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
> {
	field: ControllerRenderProps<TFieldValues, TName>;
	fieldState: ControllerFieldState;
	controlProps: {
		id: string;
		"aria-labelledby"?: string | undefined;
		"aria-describedby"?: string | undefined;
		"aria-invalid"?: boolean | undefined;
	};
}

export interface FormFieldProps<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
> {
	name: TName;
	control?: Control<TFieldValues> | undefined;
	label?: React.ReactNode | undefined;
	hint?: React.ReactNode | undefined;
	disabled?: boolean | undefined;
	className?: string | undefined;
	children: (props: FormFieldRenderProps<TFieldValues, TName>) => React.ReactNode;
}

export function FormField<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
>({
	name,
	control,
	label,
	hint,
	disabled,
	className,
	children,
}: FormFieldProps<TFieldValues, TName>) {
	const context = useFormContext<TFieldValues>();
	const activeControl = control ?? context.control;
	const reactId = React.useId();
	const idBase = `${reactId}-${String(name).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
	const labelId = `${idBase}-label`;
	const hintId = `${idBase}-hint`;
	const errorId = `${idBase}-error`;

	return (
		<Controller
			name={name}
			control={activeControl}
			render={({ field, fieldState }) => {
				const describedBy = [
					fieldState.error?.message ? errorId : undefined,
					hint ? hintId : undefined,
				]
					.filter(Boolean)
					.join(" ");
				const controlProps = {
					id: idBase,
					"aria-labelledby": label ? labelId : undefined,
					"aria-describedby": describedBy || undefined,
					"aria-invalid": fieldState.invalid || undefined,
				};
				return (
					<Field
						label={label}
						hint={hint}
						error={fieldState.error?.message}
						labelProps={{ id: labelId, htmlFor: idBase }}
						hintProps={{ id: hintId }}
						errorProps={{ id: errorId }}
						data-invalid={fieldState.invalid ? "" : undefined}
						data-disabled={disabled ? "" : undefined}
						className={className}
					>
						{children({ field, fieldState, controlProps })}
					</Field>
				);
			}}
		/>
	);
}

export function FormControl({
	fieldState,
	children,
}: {
	fieldState?: ControllerFieldState | undefined;
	children: React.ReactElement<{ "aria-invalid"?: boolean | undefined }>;
}) {
	return React.cloneElement(children, {
		"aria-invalid": fieldState?.invalid ? true : children.props["aria-invalid"],
	});
}

export type FormInputFieldProps<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
> = Omit<FormFieldProps<TFieldValues, TName>, "children"> &
	Omit<InputProps, "name" | "value" | "defaultValue" | "onChange" | "onBlur" | "ref">;

export function FormInputField<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
>({ disabled, ...props }: FormInputFieldProps<TFieldValues, TName>) {
	const { name, label, hint, control, className, ...inputProps } = props;
	return (
		<FormField
			name={name}
			control={control}
			label={label}
			hint={hint}
			disabled={disabled}
			className={className}
		>
			{({ field, fieldState, controlProps }) => (
				<Input
					{...inputProps}
					{...field}
					{...controlProps}
					value={stringValue(field.value)}
					disabled={disabled}
					tone={fieldState.invalid ? "invalid" : "default"}
				/>
			)}
		</FormField>
	);
}

export type FormTextareaFieldProps<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
> = Omit<FormFieldProps<TFieldValues, TName>, "children"> &
	Omit<TextareaProps, "name" | "value" | "defaultValue" | "onChange" | "onBlur" | "ref">;

export function FormTextareaField<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
>({ disabled, ...props }: FormTextareaFieldProps<TFieldValues, TName>) {
	const { name, label, hint, control, className, ...textareaProps } = props;
	return (
		<FormField
			name={name}
			control={control}
			label={label}
			hint={hint}
			disabled={disabled}
			className={className}
		>
			{({ field, fieldState, controlProps }) => (
				<Textarea
					{...textareaProps}
					{...field}
					{...controlProps}
					value={stringValue(field.value)}
					disabled={disabled}
					tone={fieldState.invalid ? "invalid" : "default"}
				/>
			)}
		</FormField>
	);
}

export interface FormSelectFieldProps<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
> extends Omit<FormFieldProps<TFieldValues, TName>, "children">,
		Omit<SelectProps, "name" | "value" | "defaultValue" | "onChange" | "onBlur" | "ref" | "options"> {
	options: SelectOption[];
}

export function FormSelectField<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
>({ disabled, ...props }: FormSelectFieldProps<TFieldValues, TName>) {
	const { name, label, hint, control, className, options, ...selectProps } = props;
	return (
		<FormField
			name={name}
			control={control}
			label={label}
			hint={hint}
			disabled={disabled}
			className={className}
		>
			{({ field, fieldState, controlProps }) => (
				<Select
					{...selectProps}
					{...field}
					{...controlProps}
					value={stringValue(field.value)}
					options={options}
					disabled={disabled}
					tone={fieldState.invalid ? "invalid" : "default"}
				/>
			)}
		</FormField>
	);
}

export type FormSwitchFieldProps<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
> = Omit<FormFieldProps<TFieldValues, TName>, "children"> &
	Omit<React.ComponentProps<typeof Switch>, "name" | "checked" | "defaultChecked" | "onCheckedChange" | "ref">;

export function FormSwitchField<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
>({ disabled, ...props }: FormSwitchFieldProps<TFieldValues, TName>) {
	const { name, label, hint, control, className, ...switchProps } = props;
	return (
		<FormField
			name={name}
			control={control}
			label={label}
			hint={hint}
			disabled={disabled}
			className={className}
		>
			{({ field, controlProps }) => (
				<div className="flex min-h-9 items-center">
					<Switch
						{...switchProps}
						{...controlProps}
						ref={field.ref}
						name={field.name}
						checked={Boolean(field.value)}
						onCheckedChange={field.onChange}
						onBlur={field.onBlur}
						disabled={disabled}
					/>
				</div>
			)}
		</FormField>
	);
}

export type FormCheckboxFieldProps<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
> = Omit<FormFieldProps<TFieldValues, TName>, "children"> &
	Omit<React.ComponentProps<typeof Checkbox>, "name" | "checked" | "defaultChecked" | "onCheckedChange" | "ref">;

export function FormCheckboxField<
	TFieldValues extends FieldValues,
	TName extends FieldPath<TFieldValues>,
>({ disabled, ...props }: FormCheckboxFieldProps<TFieldValues, TName>) {
	const { name, label, hint, control, className, ...checkboxProps } = props;
	return (
		<FormField
			name={name}
			control={control}
			label={label}
			hint={hint}
			disabled={disabled}
			className={className}
		>
			{({ field, controlProps }) => (
				<div className="flex min-h-9 items-center">
					<Checkbox
						{...checkboxProps}
						{...controlProps}
						ref={field.ref}
						name={field.name}
						checked={Boolean(field.value)}
						onCheckedChange={field.onChange}
						onBlur={field.onBlur}
						disabled={disabled}
					/>
				</div>
			)}
		</FormField>
	);
}

function stringValue(value: unknown) {
	if (value === null || value === undefined) return "";
	if (typeof value === "string") return value;
	if (typeof value === "number") return String(value);
	return String(value);
}
