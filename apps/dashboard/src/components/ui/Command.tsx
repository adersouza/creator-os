import type * as React from "react";
import {
	Command as ShadCommand,
	CommandEmpty as ShadCommandEmpty,
	CommandGroup as ShadCommandGroup,
	CommandInput as ShadCommandInput,
	CommandItem as ShadCommandItem,
	CommandList as ShadCommandList,
	CommandSeparator as ShadCommandSeparator,
	CommandShortcut as ShadCommandShortcut,
} from "@/components/shadcn/command";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogTitle,
} from "@/components/shadcn/dialog";
import { cn } from "@/lib/utils";

export function Command({
	className,
	...props
}: React.ComponentProps<typeof ShadCommand>) {
	return (
		<ShadCommand
			className={cn("bg-transparent text-foreground", className)}
			{...props}
		/>
	);
}

export function CommandDialog({
	children,
	title = "Command menu",
	description,
	...props
}: React.ComponentProps<typeof Dialog> & {
	title?: React.ReactNode;
	description?: React.ReactNode;
}) {
	return (
		<Dialog {...props}>
			<DialogContent className="overflow-hidden p-0">
				<DialogTitle className="sr-only">{title}</DialogTitle>
				{description ? (
					<DialogDescription className="sr-only">
						{description}
					</DialogDescription>
				) : null}
				<ShadCommand className="bg-popover text-popover-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-group]]:px-2">
					{children}
				</ShadCommand>
			</DialogContent>
		</Dialog>
	);
}

export function CommandInput({
	className,
	...props
}: React.ComponentProps<typeof ShadCommandInput>) {
	return (
		<ShadCommandInput
			className={cn(
				"h-12 text-base font-medium placeholder:text-muted-foreground md:text-[0.9375rem]",
				className,
			)}
			{...props}
		/>
	);
}

export function CommandList({
	className,
	...props
}: React.ComponentProps<typeof ShadCommandList>) {
	return (
		<ShadCommandList
			className={cn("max-h-[420px] p-1", className)}
			{...props}
		/>
	);
}

export function CommandEmpty({
	className,
	...props
}: React.ComponentProps<typeof ShadCommandEmpty>) {
	return (
		<ShadCommandEmpty
			className={cn(
				"px-3 py-10 text-center text-[0.8125rem] text-muted-foreground",
				className,
			)}
			{...props}
		/>
	);
}

export function CommandGroup({
	className,
	...props
}: React.ComponentProps<typeof ShadCommandGroup>) {
	return (
		<ShadCommandGroup
			className={cn(
				"p-1 text-foreground [&_[cmdk-group-heading]]:text-[0.6875rem] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-muted-foreground",
				className,
			)}
			{...props}
		/>
	);
}

export function CommandItem({
	className,
	...props
}: React.ComponentProps<typeof ShadCommandItem>) {
	return (
		<ShadCommandItem
			className={cn(
				"rounded-lg px-3 py-2.5 text-muted-foreground data-[selected=true]:bg-muted data-[selected=true]:text-foreground",
				className,
			)}
			{...props}
		/>
	);
}

export function CommandSeparator(
	props: React.ComponentProps<typeof ShadCommandSeparator>,
) {
	return <ShadCommandSeparator {...props} />;
}

export function CommandShortcut({
	className,
	...props
}: React.ComponentProps<typeof ShadCommandShortcut>) {
	return (
		<ShadCommandShortcut
			className={cn(
				"font-mono text-[0.625rem] tracking-normal text-muted-foreground",
				className,
			)}
			{...props}
		/>
	);
}
