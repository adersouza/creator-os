import React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { Field as UiField } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";

/* =========================================================================
   Reusable form primitives used throughout the Composer.
   Pure, zero-dependency presentational components.
   ========================================================================= */

export function CounterPill({
	current,
	max,
	label,
}: {
	current: number;
	max: number;
	label: string;
}) {
	const pct = Math.min(1, current / max);
	const warn = pct >= 0.9;
	const over = current > max;
	return (
		<span
			className={cn(
				"inline-flex items-center gap-1 tabular-nums",
				over
					? "text-[color:var(--color-oxblood)]"
					: warn
						? "text-[color:var(--color-health-warn)]"
						: "text-muted-foreground",
			)}
		>
			<span
				className="w-1.5 h-1.5 rounded-full"
				style={{ background: "currentColor" }}
				aria-hidden="true"
			/>
			<span className="font-medium">{label}</span>
			<span>
				{current} / {max}
			</span>
		</span>
	);
}

export function CollapsibleSection({
	title,
	icon,
	open,
	onToggle,
	children,
	scopeHint,
}: {
	title: string;
	icon: React.ReactNode;
	open: boolean;
	onToggle: () => void;
	children: React.ReactNode;
	scopeHint?: { tone: "active" | "muted"; text: string } | undefined;
}) {
	return (
		<NovaCard className="p-0" contentClassName="p-0">
			<Button
				type="button"
				variant="ghost"
				onClick={onToggle}
				className="h-10 w-full justify-between rounded-none px-4 text-left"
				aria-expanded={open}
			>
				<span className="inline-flex items-center gap-2 min-w-0">
					{icon}
					<span className="text-[0.8125rem] font-medium text-foreground shrink-0">
						{title}
					</span>
					{scopeHint && (
						<span
							className={cn(
								"text-[0.65625rem] font-medium tabular-nums truncate",
								scopeHint.tone === "active"
									? "text-muted-foreground"
									: "text-muted-foreground italic",
							)}
						>
							· {scopeHint.text}
						</span>
					)}
				</span>
				<ChevronDown
					className={cn(
						"w-3.5 h-3.5 text-muted-foreground transition-transform shrink-0",
						open && "rotate-180",
					)}
					aria-hidden="true"
				/>
			</Button>
			<div
				className={cn(
					"grid transition-[grid-template-rows,opacity] duration-[220ms] ease-[cubic-bezier(0.23,1,0.32,1)]",
					open
						? "grid-rows-[1fr] opacity-100 border-t border-border"
						: "grid-rows-[0fr] opacity-0",
				)}
				aria-hidden={!open}
			>
				<div className="overflow-hidden">
					<div className="p-4 flex flex-col gap-3">{children}</div>
				</div>
			</div>
		</NovaCard>
	);
}

const FieldContext = React.createContext<{ inputId?: string | undefined }>({});

export function Field({
	label,
	children,
}: {
	label: string;
	children: React.ReactNode;
}) {
	const reactId = React.useId();
	const inputId = `field-${reactId}`;
	const ctx = React.useMemo(() => ({ inputId }), [inputId]);
	return (
		<UiField label={label}>
			<FieldContext.Provider value={ctx}>{children}</FieldContext.Provider>
		</UiField>
	);
}

export function TextInput({
	value,
	onChange,
	placeholder,
	icon,
}: {
	value: string;
	onChange: (v: string) => void;
	placeholder?: string | undefined;
	icon?: React.ReactNode | undefined;
}) {
	const { inputId } = React.useContext(FieldContext);
	return (
		<Input
			id={inputId}
			type="text"
			value={value}
			onChange={(event) => onChange(event.target.value)}
			placeholder={placeholder}
			leadingIcon={icon}
		/>
	);
}

export function SelectInput<T extends string>({
	value,
	onChange,
	options,
	icon,
}: {
	value: T;
	onChange: (v: T) => void;
	options: { value: T; label: string }[];
	icon?: React.ReactNode | undefined;
}) {
	const { inputId } = React.useContext(FieldContext);
	return (
		<div className="relative w-full">
			{icon ? (
				<span
					className="absolute left-3 top-1/2 z-10 -translate-y-1/2 text-muted-foreground pointer-events-none"
					aria-hidden="true"
				>
					{icon}
				</span>
			) : null}
			<Select
				id={inputId}
				value={value}
				onChange={(event) => onChange(event.target.value as T)}
				className={cn(icon && "pl-8")}
				options={options}
			/>
			<ChevronDown
				className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none"
				aria-hidden="true"
			/>
		</div>
	);
}

export function Toggle({
	label,
	detail,
	checked,
	onChange,
	icon,
}: {
	label: string;
	detail?: string | undefined;
	checked: boolean;
	onChange: (v: boolean) => void;
	icon?: React.ReactNode | undefined;
}) {
	return (
		<div className="flex items-start gap-3 select-none">
			<div className="flex-1 min-w-0">
				<div className="inline-flex items-center gap-1.5 text-[0.78125rem] font-medium text-foreground">
					{icon}
					{label}
				</div>
				{detail && (
					<p className="mt-0.5 text-[0.6875rem] text-muted-foreground leading-[1.35]">
						{detail}
					</p>
				)}
			</div>
			<Switch checked={checked} onCheckedChange={onChange} aria-label={label} />
		</div>
	);
}
