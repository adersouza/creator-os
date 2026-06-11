import { Bell, Calendar, Clock, Info, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import { Field } from "@/components/composer/ComposerFormControls";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

/* =========================================================================
   Scheduling primitives — the mode radio, date/time picker grid, and queue
   info card. Desktop and mobile compose them with slightly different sizing
   and wrapping chrome, so we pass a `size` that swaps just the sizing tokens.
   ========================================================================= */

export type ScheduleMode = "now" | "schedule" | "queue";
export type PublishMode = "auto" | "notify";

export function ScheduleModeRadio({
	scheduleMode,
	onScheduleModeChange,
	size = "desktop",
}: {
	scheduleMode: ScheduleMode;
	onScheduleModeChange: (v: ScheduleMode) => void;
	size?: "desktop" | "mobile" | undefined;
}) {
	const buttonHeight = size === "mobile" ? "h-10" : "h-9";
	const buttonText =
		size === "mobile" ? "text-[0.8125rem]" : "text-[0.78125rem]";
	return (
		<div
			className="flex items-center gap-1"
			role="radiogroup"
			aria-label="Schedule mode"
		>
			{[
				{ v: "now" as const, label: "Post now" },
				{ v: "schedule" as const, label: "Schedule" },
				{ v: "queue" as const, label: "Queue" },
			].map(({ v, label }) => {
				const active = scheduleMode === v;
				return (
					<Button
						key={v}
						type="button"
						variant={active ? "secondary" : "outline"}
						role="radio"
						aria-checked={active}
						onClick={() => onScheduleModeChange(v)}
						className={cn(
							"flex-1",
							buttonHeight,
							buttonText,
							active && "border-input",
						)}
					>
						{label}
					</Button>
				);
			})}
		</div>
	);
}

export function ScheduleDateTimePickers({
	scheduleDate,
	onScheduleDateChange,
	scheduleTime,
	onScheduleTimeChange,
	size = "desktop",
}: {
	scheduleDate: string;
	onScheduleDateChange: (v: string) => void;
	scheduleTime: string;
	onScheduleTimeChange: (v: string) => void;
	size?: "desktop" | "mobile" | undefined;
}) {
	const inputHeight = size === "mobile" ? "h-10" : "h-9";
	const inputText = size === "mobile" ? "text-[0.875rem]" : "text-[0.8125rem]";
	// Desktop has a subtle focus-border shift; mobile version doesn't use border shift on focus.
	const focusBorder =
		size === "mobile"
			? ""
			: "focus:border-[color-mix(in_srgb,var(--color-foreground)_14%,transparent)] dark:focus:border-[color-mix(in_srgb,var(--color-foreground)_14%,transparent)]";
	return (
		<div className="grid grid-cols-2 gap-2">
			<Field label="Date">
				<Input
					type="date"
					value={scheduleDate}
					onChange={(event) => onScheduleDateChange(event.target.value)}
					leadingIcon={<Calendar className="h-3.5 w-3.5" />}
					className={cn(inputHeight, inputText, focusBorder)}
				/>
			</Field>
			<Field label="Time">
				<Input
					type="time"
					value={scheduleTime}
					onChange={(event) => onScheduleTimeChange(event.target.value)}
					leadingIcon={<Clock className="h-3.5 w-3.5" />}
					className={cn("tabular-nums", inputHeight, inputText, focusBorder)}
				/>
			</Field>
		</div>
	);
}

export function QueueModeHint({
	size = "desktop",
}: {
	size?: "desktop" | "mobile" | undefined;
}) {
	const text = size === "mobile" ? "text-[0.78125rem]" : "text-[0.71875rem]";
	return (
		<div
			className={cn(
				"px-3 py-2.5 rounded-md border border-[color-mix(in_srgb,var(--color-oxblood)_22%,transparent)] bg-[color-mix(in_srgb,var(--color-oxblood)_5%,transparent)] text-muted-foreground flex items-start gap-2",
				text,
			)}
		>
			<Info
				className="w-3.5 h-3.5 shrink-0 mt-0.5"
				style={{ color: "var(--color-oxblood)" }}
				aria-hidden="true"
			/>
			<span>
				Adds to each account's queue. Juno33 auto-schedules at each audience's
				peak window.
			</span>
		</div>
	);
}

export function PublishModeRadio({
	publishMode,
	onPublishModeChange,
	size = "desktop",
}: {
	publishMode: PublishMode;
	onPublishModeChange: (v: PublishMode) => void;
	size?: "desktop" | "mobile" | undefined;
}) {
	const buttonText = size === "mobile" ? "text-[0.8125rem]" : "text-[0.75rem]";
	const options = [
		{ v: "auto" as const, label: "Auto-publish", icon: Send },
		{ v: "notify" as const, label: "Notify me", icon: Bell },
	];
	return (
		<div
			className="grid grid-cols-2 gap-2"
			role="radiogroup"
			aria-label="Instagram publish mode"
		>
			{options.map(({ v, label, icon: Icon }) => {
				const active = publishMode === v;
				return (
					<Button
						key={v}
						type="button"
						variant={active ? "default" : "outline"}
						role="radio"
						aria-checked={active}
						onClick={() => onPublishModeChange(v)}
						className={cn("h-9 gap-1.5", buttonText)}
					>
						<Icon className="h-3.5 w-3.5" aria-hidden="true" />
						{label}
					</Button>
				);
			})}
		</div>
	);
}
