import type * as React from "react";
import { Calendar as ShadCalendar } from "@/components/shadcn/calendar";
import { cn } from "@/lib/utils";

export type CalendarProps = React.ComponentProps<typeof ShadCalendar>;

export function Calendar({ className, ...props }: CalendarProps) {
	return (
		<ShadCalendar
			className={cn("rounded-md border border-border bg-card", className)}
			{...props}
		/>
	);
}
