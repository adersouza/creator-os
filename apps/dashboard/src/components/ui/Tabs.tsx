import * as TabsPrimitive from "@radix-ui/react-tabs";
import React from "react";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export const TabsList = React.forwardRef<
	React.ElementRef<typeof TabsPrimitive.List>,
	React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
	<TabsPrimitive.List
		ref={ref}
		className={cn(
			"inline-flex max-w-full min-w-0 items-center overflow-x-auto rounded-full border border-border bg-card p-1 td-control-shadow",
			className,
		)}
		{...props}
	/>
));
TabsList.displayName = TabsPrimitive.List.displayName;

export const TabsTrigger = React.forwardRef<
	React.ElementRef<typeof TabsPrimitive.Trigger>,
	React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
	<TabsPrimitive.Trigger
		ref={ref}
		className={cn(
			"app-control-text flex h-8 shrink-0 items-center justify-center rounded-full px-4 text-muted-foreground transition-colors",
			"focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-card)]",
			"disabled:pointer-events-none disabled:opacity-50",
			"data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-sm",
			className,
		)}
		{...props}
	/>
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

export const TabsContent = React.forwardRef<
	React.ElementRef<typeof TabsPrimitive.Content>,
	React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
	<TabsPrimitive.Content
		ref={ref}
		className={cn(
			"focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]",
			className,
		)}
		{...props}
	/>
));
TabsContent.displayName = TabsPrimitive.Content.displayName;
