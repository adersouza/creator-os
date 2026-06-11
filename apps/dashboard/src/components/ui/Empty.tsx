import type React from "react";
import {
	Empty as ShadEmpty,
	EmptyContent as ShadEmptyContent,
	EmptyDescription as ShadEmptyDescription,
	EmptyHeader as ShadEmptyHeader,
	EmptyMedia as ShadEmptyMedia,
	EmptyTitle as ShadEmptyTitle,
} from "@/components/shadcn/empty";
import { cn } from "@/lib/utils";

export function Empty({ className, ...props }: React.ComponentProps<typeof ShadEmpty>) {
	return (
		<ShadEmpty
			className={cn(
				"min-h-28 gap-3 rounded-lg border border-dashed border-border bg-card/35 p-5 md:p-6",
				className,
			)}
			{...props}
		/>
	);
}

export function EmptyHeader({
	className,
	...props
}: React.ComponentProps<typeof ShadEmptyHeader>) {
	return <ShadEmptyHeader className={cn("max-w-[32rem] gap-1.5", className)} {...props} />;
}

export function EmptyTitle({
	className,
	...props
}: React.ComponentProps<typeof ShadEmptyTitle>) {
	return <ShadEmptyTitle className={cn("app-card-title text-foreground", className)} {...props} />;
}

export function EmptyDescription({
	className,
	...props
}: React.ComponentProps<typeof ShadEmptyDescription>) {
	return (
		<ShadEmptyDescription
			className={cn("app-body text-muted-foreground", className)}
			{...props}
		/>
	);
}

export function EmptyContent({
	className,
	...props
}: React.ComponentProps<typeof ShadEmptyContent>) {
	return <ShadEmptyContent className={cn("max-w-[32rem] gap-3", className)} {...props} />;
}

export function EmptyMedia({
	className,
	...props
}: React.ComponentProps<typeof ShadEmptyMedia>) {
	return (
		<ShadEmptyMedia
			className={cn("text-primary", className)}
			{...props}
		/>
	);
}
