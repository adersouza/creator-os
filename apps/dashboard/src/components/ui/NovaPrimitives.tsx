import type React from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight, BarChart3 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
	Card,
	CardContent,
	CardDescription,
	CardFooter,
	CardHeader,
	CardTitle,
} from "@/components/shadcn/card";
import {
	Empty,
	EmptyContent,
	EmptyDescription,
	EmptyHeader,
	EmptyMedia,
	EmptyTitle,
} from "@/components/ui/Empty";
import { Progress } from "@/components/ui/Progress";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/utils";

export interface NovaHeaderProps extends Omit<React.HTMLAttributes<HTMLElement>, "title"> {
	eyebrow?: React.ReactNode | undefined;
	title: React.ReactNode;
	description?: React.ReactNode | undefined;
	meta?: React.ReactNode | undefined;
	actions?: React.ReactNode | undefined;
	filters?: React.ReactNode | undefined;
	children?: React.ReactNode | undefined;
	variant?: "default" | "compact" | "board" | undefined;
}
export interface NovaCardProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
	eyebrow?: React.ReactNode | undefined;
	title?: React.ReactNode | undefined;
	description?: React.ReactNode | undefined;
	action?: React.ReactNode | undefined;
	footer?: React.ReactNode | undefined;
	variant?: "default" | "hero" | "compact" | "panel" | undefined;
	contentClassName?: string | undefined;
}
export interface NovaStatProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
	label: React.ReactNode;
	value: React.ReactNode;
	description?: React.ReactNode | undefined;
	trend?:
		| React.ReactNode
		| {
				direction?: "up" | "down" | "flat" | undefined;
				label: React.ReactNode;
		  }
		| undefined;
	icon?: React.ReactNode | undefined;
	status?: React.ReactNode | undefined;
	progress?: number | { value: number; label?: string | undefined } | undefined;
	action?: React.ReactNode | undefined;
	loading?: boolean | undefined;
	variant?: "default" | "hero" | "compact" | undefined;
}
export interface NovaDataPanelProps extends Omit<NovaCardProps, "action"> {
	toolbar?: React.ReactNode | undefined;
	empty?: React.ReactNode | { title: React.ReactNode; description?: React.ReactNode | undefined } | undefined;
	loading?: boolean | undefined;
}
export interface NovaMiniStatProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
	label: React.ReactNode;
	value: React.ReactNode;
	description?: React.ReactNode | undefined;
	trend?: React.ReactNode | undefined;
	tone?: "default" | "primary" | "success" | "warning" | "danger" | undefined;
	size?: "default" | "compact" | undefined;
}
export interface NovaListRowProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
	leading?: React.ReactNode | undefined;
	title: React.ReactNode;
	description?: React.ReactNode | undefined;
	meta?: React.ReactNode | undefined;
	action?: React.ReactNode | undefined;
	progress?: number | undefined;
	progressLabel?: string | undefined;
	tone?: "default" | "primary" | "success" | "warning" | "danger" | undefined;
}
export interface NovaInsetProps extends React.HTMLAttributes<HTMLDivElement> {
	tone?: "default" | "primary" | "success" | "warning" | "danger" | undefined;
}

export function NovaHeader({
	eyebrow,
	title,
	description,
	meta,
	actions,
	filters,
	variant = "default",
	children,
	className,
	...props
}: NovaHeaderProps) {
	const isCompact = variant === "compact" || variant === "board";
	const isBoard = variant === "board";
	return (
		<header
			className={cn("nova-header flex min-w-0 flex-col", isBoard ? "gap-2.5" : isCompact ? "gap-3" : "gap-4", className)}
			{...props}
		>
			<div
				className={cn(
					"flex min-w-0 flex-col",
					isBoard
						? "gap-2.5 md:flex-row md:items-start md:justify-between"
						: "lg:flex-row lg:items-start lg:justify-between",
					!isBoard && (isCompact ? "gap-3" : "gap-4"),
				)}
			>
				<div className="min-w-0 flex-1">
					<div className="flex min-w-0 flex-wrap items-center gap-2">
						{eyebrow ? (
							<span className="text-sm font-semibold text-primary">{eyebrow}</span>
						) : null}
						{meta ? (
							<Badge tone="outline" className="max-w-full truncate normal-case tracking-normal">
								{meta}
							</Badge>
						) : null}
					</div>
					<h1 className={cn("mt-2 font-semibold tracking-normal text-foreground", isBoard ? "text-2xl" : isCompact ? "text-3xl" : "text-3xl md:text-4xl")}>
						{title}
					</h1>
					{description ? (
						<p className={cn("mt-2 max-w-3xl leading-relaxed text-muted-foreground", isBoard ? "hidden text-sm xl:line-clamp-1 xl:block" : isCompact ? "text-sm" : "text-base")}>
							{description}
						</p>
					) : null}
				</div>
				{actions ? (
					<div className="flex shrink-0 flex-wrap items-center gap-2 lg:justify-end">
						{actions}
					</div>
				) : null}
			</div>
			{filters ? <div className="flex min-w-0 flex-wrap items-center gap-2">{filters}</div> : null}
			{children}
		</header>
	);
}

export function NovaSection({
	className,
	...props
}: React.HTMLAttributes<HTMLElement>) {
	return (
		<section
			className={cn("nova-section flex min-w-0 flex-col gap-4", className)}
			{...props}
		/>
	);
}

export function NovaToolbar({
	className,
	...props
}: React.HTMLAttributes<HTMLDivElement>) {
	return (
		<div
			className={cn("nova-toolbar flex min-w-0 flex-wrap items-center gap-2", className)}
			{...props}
		/>
	);
}

const NOVA_CARD_VARIANT_CLASS: Record<NonNullable<NovaCardProps["variant"]>, string> = {
	default: "shadow-sm",
	hero: "shadow-sm md:shadow",
	compact: "shadow-sm",
	panel: "bg-muted/45 shadow-none",
};

const NOVA_CARD_HEADER_CLASS: Record<NonNullable<NovaCardProps["variant"]>, string> = {
	default: "p-5 pb-4 md:p-6 md:pb-4",
	hero: "p-5 pb-4 md:p-7 md:pb-4",
	compact: "p-4 pb-3",
	panel: "p-4 pb-3",
};

const NOVA_CARD_CONTENT_CLASS: Record<NonNullable<NovaCardProps["variant"]>, string> = {
	default: "p-5 md:p-6",
	hero: "p-5 md:p-7",
	compact: "p-4",
	panel: "p-4",
};

const NOVA_CARD_TITLE_CLASS: Record<NonNullable<NovaCardProps["variant"]>, string> = {
	default: "text-xl",
	hero: "text-2xl md:text-3xl",
	compact: "text-base",
	panel: "text-base",
};

export function NovaCard({
	eyebrow,
	title,
	description,
	action,
	footer,
	variant = "default",
	contentClassName,
	className,
	children,
	...props
}: NovaCardProps) {
	const hasHeader = eyebrow || title || description || action;

	return (
		<Card
			className={cn(
				"nova-card min-w-0 overflow-hidden rounded-xl border-border bg-card text-card-foreground",
				NOVA_CARD_VARIANT_CLASS[variant],
				className,
			)}
			{...props}
		>
			{hasHeader ? (
				<CardHeader className={cn("nova-card-header flex flex-row items-start justify-between gap-4", NOVA_CARD_HEADER_CLASS[variant])}>
					<div className="min-w-0">
						{eyebrow ? (
							<div className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary">{eyebrow}</div>
						) : null}
						{title ? (
							<CardTitle
								role="heading"
								aria-level={3}
								className={cn(
									"text-pretty font-semibold leading-tight tracking-normal text-foreground",
									NOVA_CARD_TITLE_CLASS[variant],
								)}
							>
								{title}
							</CardTitle>
						) : null}
						{description ? (
							<CardDescription className="mt-2 line-clamp-2 text-sm leading-relaxed text-muted-foreground">
								{description}
							</CardDescription>
						) : null}
					</div>
					{action ? <div className="shrink-0">{action}</div> : null}
				</CardHeader>
			) : null}
			{children ? (
				<CardContent
					className={cn(
						"nova-card-content",
						hasHeader
							? variant === "hero"
								? "px-5 pb-5 pt-0 md:px-7 md:pb-7"
								: variant === "compact" || variant === "panel"
									? "px-4 pb-4 pt-0"
									: "px-5 pb-5 pt-0 md:px-6 md:pb-6"
							: NOVA_CARD_CONTENT_CLASS[variant],
						contentClassName,
					)}
				>
					{children}
				</CardContent>
			) : null}
			{footer ? (
				<CardFooter className={cn("nova-card-footer border-t border-border bg-muted/45", variant === "compact" || variant === "panel" ? "p-4" : "p-5 md:p-6")}>
					{footer}
				</CardFooter>
			) : null}
		</Card>
	);
}

export function NovaStat({
	label,
	value,
	description,
	trend,
	icon,
	status,
	progress,
	action,
	loading = false,
	variant = "default",
	className,
	...props
}: NovaStatProps) {
	const progressValue = typeof progress === "number" ? progress : progress?.value;
	const progressLabel = typeof progress === "number" ? undefined : progress?.label;

	return (
		<NovaCard
			variant={variant === "hero" ? "hero" : variant === "compact" ? "compact" : "default"}
			className={cn("nova-stat", className)}
			contentClassName={cn(
				"flex h-full flex-col",
				variant === "compact" ? "gap-2.5" : "gap-4",
			)}
			{...props}
		>
			<div className="flex min-w-0 items-start justify-between gap-3">
				<div className="min-w-0">
					<div className="flex min-w-0 items-center gap-2">
						<span className="truncate text-sm font-medium leading-none text-muted-foreground">{label}</span>
						{status ? <Badge tone="outline">{status}</Badge> : null}
					</div>
					{loading ? (
						<Skeleton className="mt-2 h-9 w-28" />
					) : (
						<div
							className={cn(
								"mt-2 truncate font-semibold tabular-nums tracking-normal text-foreground",
								variant === "hero" ? "text-5xl" : variant === "compact" ? "text-2xl" : "text-4xl",
							)}
						>
							{value}
						</div>
					)}
				</div>
				{icon ? (
					<div className="nova-icon-box flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
						{icon}
					</div>
				) : null}
			</div>
			{description ? (
				<p className="text-sm leading-relaxed text-muted-foreground">{description}</p>
			) : null}
			<div className="mt-auto flex min-w-0 flex-wrap items-center gap-2">
				{trend ? <NovaTrendBadge trend={trend} /> : null}
				{action ? <div className="ml-auto">{action}</div> : null}
			</div>
			{progressValue !== undefined ? (
				<div className="grid gap-2">
					<Progress
						value={progressValue}
						aria-label={progressLabel ?? `${String(label)} progress`}
					/>
					{progressLabel ? (
						<div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
							<span className="truncate">{progressLabel}</span>
							<span className="shrink-0 tabular-nums">{Math.round(progressValue)}%</span>
						</div>
					) : null}
				</div>
			) : null}
		</NovaCard>
	);
}

function NovaTrendBadge({ trend }: { trend: NonNullable<NovaStatProps["trend"]> }) {
	if (typeof trend !== "object" || !("label" in trend)) {
		return <Badge tone="secondary">{trend}</Badge>;
	}

	const direction = trend.direction ?? "flat";
	const Icon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : ArrowRight;
	const tone = direction === "down" ? "danger" : direction === "up" ? "oxblood" : "secondary";
	return (
		<Badge tone={tone} className="gap-1">
			<Icon data-icon="inline-start" aria-hidden="true" />
			{trend.label}
		</Badge>
	);
}

export function NovaDataPanel({
	toolbar,
	empty,
	loading = false,
	children,
	className,
	...props
}: NovaDataPanelProps) {
	const action = toolbar ? <div className="flex items-center gap-2">{toolbar}</div> : undefined;

	return (
		<NovaCard className={cn("nova-data-panel", className)} action={action} {...props}>
			{loading ? (
				<div role="status" aria-label="Loading panel" className="grid gap-3">
					<Skeleton className="h-5 w-2/5" />
					<Skeleton className="h-20 w-full" />
					<Skeleton className="h-5 w-3/5" />
				</div>
			) : children ? (
				children
			) : empty ? (
				typeof empty === "object" && "title" in empty ? (
					<Empty>
						<EmptyHeader>
							<EmptyTitle>{empty.title}</EmptyTitle>
							{empty.description ? (
								<EmptyDescription>{empty.description}</EmptyDescription>
							) : null}
						</EmptyHeader>
					</Empty>
				) : (
					empty
				)
			) : null}
		</NovaCard>
	);
}

const NOVA_TONE_TEXT_CLASS = {
	default: "text-foreground",
	primary: "text-primary",
	success: "text-success",
	warning: "text-warning",
	danger: "text-error",
} as const;

const NOVA_TONE_PANEL_CLASS = {
	default: "border-border bg-muted/35",
	primary: "border-primary/25 bg-primary/10",
	success: "border-success/25 bg-success/10",
	warning: "border-warning/25 bg-warning/10",
	danger: "border-error/25 bg-error/10",
} as const;

export function NovaInset({
	tone = "default",
	className,
	...props
}: NovaInsetProps) {
	return (
		<div
			className={cn(
				"nova-inset min-w-0 rounded-lg border p-4",
				NOVA_TONE_PANEL_CLASS[tone],
				className,
			)}
			{...props}
		/>
	);
}

export function NovaMiniStat({
	label,
	value,
	description,
	trend,
	tone = "default",
	size = "default",
	className,
	...props
}: NovaMiniStatProps) {
	const isCompact = size === "compact";
	return (
		<div
			className={cn(
				"nova-mini-stat min-w-0 rounded-lg border",
				isCompact ? "px-2.5 py-2" : "px-3.5 py-3",
				NOVA_TONE_PANEL_CLASS[tone],
				className,
			)}
			{...props}
		>
			<div className="flex min-w-0 items-center justify-between gap-2">
				<p
					className={cn(
						"truncate font-medium uppercase tracking-[0.12em] text-muted-foreground",
						isCompact ? "text-[10px]" : "text-xs",
					)}
				>
					{label}
				</p>
				{trend ? <Badge tone="outline">{trend}</Badge> : null}
			</div>
			<div
				className={cn(
					"truncate font-semibold tracking-normal tabular-nums",
					isCompact ? "mt-1 text-xl" : "mt-2 text-2xl",
					NOVA_TONE_TEXT_CLASS[tone],
				)}
			>
				{value}
			</div>
			{description ? (
				<p
					className={cn(
						"truncate text-muted-foreground",
						isCompact ? "mt-0.5 text-[11px]" : "mt-1 text-xs",
					)}
				>
					{description}
				</p>
			) : null}
		</div>
	);
}

export function NovaListRow({
	leading,
	title,
	description,
	meta,
	action,
	progress,
	progressLabel,
	tone = "default",
	className,
	...props
}: NovaListRowProps) {
	return (
		<div
			className={cn(
				"nova-list-row min-w-0 rounded-lg border px-3.5 py-3.5 transition-colors",
				NOVA_TONE_PANEL_CLASS[tone],
				className,
			)}
			{...props}
		>
			<div className="flex min-w-0 items-start gap-3">
				{leading ? (
					<div className="nova-icon-box flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground">
						{leading}
					</div>
				) : null}
				<div className="min-w-0 flex-1">
					<div className="flex min-w-0 items-start justify-between gap-3">
						<div className="min-w-0">
							<div className="truncate text-sm font-semibold text-foreground">
								{title}
							</div>
							{description ? (
								<div className="mt-1 truncate text-sm text-muted-foreground">
									{description}
								</div>
							) : null}
						</div>
						{meta || action ? (
							<div className="flex shrink-0 items-center gap-2">
								{meta ? <div>{meta}</div> : null}
								{action ? <div>{action}</div> : null}
							</div>
						) : null}
					</div>
					{progress !== undefined ? (
						<Progress
							className="mt-3"
							value={Math.max(0, Math.min(100, progress))}
							aria-label={progressLabel ?? `${String(title)} progress`}
						/>
					) : null}
				</div>
			</div>
		</div>
	);
}

export interface NovaEmptyProps {
	eyebrow?: React.ReactNode | undefined;
	title: React.ReactNode;
	description?: React.ReactNode | undefined;
	action?: React.ReactNode | undefined;
	icon?: React.ReactNode | undefined;
	children?: React.ReactNode | undefined;
	className?: string | undefined;
}

export function NovaEmpty({
	eyebrow,
	title,
	description,
	action,
	icon,
	children,
	className,
}: NovaEmptyProps) {
	return (
		<Empty className={cn("p-8", className)}>
			<EmptyHeader>
				<EmptyMedia>{icon ?? <BarChart3 data-icon="inline-start" aria-hidden="true" />}</EmptyMedia>
				{eyebrow ? (
					<span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
						{eyebrow}
					</span>
				) : null}
				<EmptyTitle>{title}</EmptyTitle>
				{description ? <EmptyDescription>{description}</EmptyDescription> : null}
			</EmptyHeader>
			{action ? <EmptyContent>{action}</EmptyContent> : null}
			{children}
		</Empty>
	);
}

export function NovaStatus({
	children,
	tone = "outline",
}: {
	children: React.ReactNode;
	tone?: React.ComponentProps<typeof Badge>["tone"];
}) {
	return <Badge tone={tone}>{children}</Badge>;
}

export function NovaAction({
	children,
	...props
}: React.ComponentProps<typeof Button>) {
	return <Button {...props}>{children}</Button>;
}
