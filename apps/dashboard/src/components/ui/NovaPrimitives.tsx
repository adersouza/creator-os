import type React from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight, BarChart3 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
	Card,
	CardAction,
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
import { Sparkline } from "@/components/ui/Sparkline";
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
	sparkline?: { points: number[]; label?: string | undefined } | undefined;
	action?: React.ReactNode | undefined;
	footer?: React.ReactNode | undefined;
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
export interface NovaUsageItem {
	label: React.ReactNode;
	value: React.ReactNode;
	description?: React.ReactNode | undefined;
	progress?: number | undefined;
	limit?: React.ReactNode | undefined;
	tone?: "default" | "primary" | "success" | "warning" | "danger" | undefined;
	action?: React.ReactNode | undefined;
}
export interface NovaUsageListProps extends React.HTMLAttributes<HTMLDivElement> {
	items: NovaUsageItem[];
	empty?: React.ReactNode | undefined;
	showMeters?: boolean | undefined;
}
export interface NovaInsetProps extends React.HTMLAttributes<HTMLDivElement> {
	tone?: "default" | "primary" | "success" | "warning" | "danger" | undefined;
}
export interface NovaBentoGridProps extends React.HTMLAttributes<HTMLDivElement> {
	gap?: "compact" | "default" | "roomy" | undefined;
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
			className={cn("nova-section flex min-w-0 flex-col gap-6", className)}
			{...props}
		/>
	);
}

export function NovaBentoGrid({
	gap = "default",
	className,
	...props
}: NovaBentoGridProps) {
	return (
		<div
			className={cn(
				"nova-bento-grid grid min-w-0 items-stretch [&>*]:min-w-0",
				gap === "compact" ? "gap-4 md:gap-5" : gap === "roomy" ? "gap-6 md:gap-7" : "gap-5 md:gap-6",
				className,
			)}
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
	default: "bg-card shadow-sm",
	hero: "bg-card shadow-sm md:shadow",
	compact: "bg-card shadow-sm",
	panel: "bg-muted shadow-none",
};

const NOVA_CARD_HEADER_CLASS: Record<NonNullable<NovaCardProps["variant"]>, string> = {
	default: "p-5 pb-3 md:p-6 md:pb-4",
	hero: "p-6 pb-4 md:p-7 md:pb-5",
	compact: "p-4 pb-2.5 md:p-5 md:pb-3",
	panel: "p-4 pb-2.5 md:p-5 md:pb-3",
};

const NOVA_CARD_CONTENT_CLASS: Record<NonNullable<NovaCardProps["variant"]>, string> = {
	default: "p-5 md:p-6",
	hero: "p-6 md:p-7",
	compact: "p-4 md:p-5",
	panel: "p-4 md:p-5",
};

const NOVA_CARD_CONTENT_WITH_HEADER_CLASS: Record<NonNullable<NovaCardProps["variant"]>, string> = {
	default: "px-5 pb-5 pt-0 md:px-6 md:pb-6",
	hero: "px-6 pb-6 pt-0 md:px-7 md:pb-7",
	compact: "px-4 pb-4 pt-0 md:px-5 md:pb-5",
	panel: "px-4 pb-4 pt-0 md:px-5 md:pb-5",
};

const NOVA_CARD_TITLE_CLASS: Record<NonNullable<NovaCardProps["variant"]>, string> = {
	default: "text-lg",
	hero: "text-xl md:text-2xl",
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
	const flushContent = typeof contentClassName === "string" && /\bp-0\b/.test(contentClassName);

	return (
		<Card
			data-nova-variant={variant}
			className={cn(
				"nova-card min-w-0 overflow-hidden rounded-xl border-border text-card-foreground",
				NOVA_CARD_VARIANT_CLASS[variant],
				className,
			)}
			{...props}
		>
			{hasHeader ? (
				<CardHeader className={cn("nova-card-header flex flex-row flex-wrap items-start justify-between gap-3", NOVA_CARD_HEADER_CLASS[variant])}>
					<div className="min-w-0 basis-64 flex-1">
						{eyebrow ? (
							<div className="mb-1.5 text-xs font-semibold uppercase tracking-[0.16em] text-primary">{eyebrow}</div>
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
							<CardDescription className="mt-1.5 line-clamp-2 text-sm leading-snug text-muted-foreground">
								{description}
							</CardDescription>
						) : null}
					</div>
					{action ? <CardAction className="flex min-w-0 shrink-0 flex-wrap items-center justify-end gap-2">{action}</CardAction> : null}
				</CardHeader>
			) : null}
			{children ? (
				<CardContent
					className={cn(
							"nova-card-content",
							flushContent
								? "p-0 md:p-0"
								: hasHeader
								? NOVA_CARD_CONTENT_WITH_HEADER_CLASS[variant]
								: NOVA_CARD_CONTENT_CLASS[variant],
							contentClassName,
						)}
				>
					{children}
				</CardContent>
			) : null}
			{footer ? (
				<CardFooter
					className={cn(
						"nova-card-footer border-t border-border bg-muted/55",
						variant === "compact" || variant === "panel" ? "p-4 md:p-5" : "p-5 md:p-6",
					)}
				>
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
	sparkline,
	action,
	footer,
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
				variant === "hero"
					? "min-h-[220px] gap-4"
					: variant === "compact"
						? "min-h-[112px] gap-2.5"
						: "min-h-[176px] gap-4",
			)}
			footer={footer}
			{...props}
		>
			<div className="flex min-w-0 items-start justify-between gap-3">
				<div className="min-w-0">
					<div className="flex min-w-0 items-center gap-2">
							<span
								className={cn(
									"nova-stat-label text-xs font-semibold uppercase leading-tight tracking-[0.12em] text-muted-foreground",
									"line-clamp-2",
								)}
							>
							{label}
						</span>
						{status ? <Badge tone="outline">{status}</Badge> : null}
					</div>
					{loading ? (
						<Skeleton className="mt-2 h-8 w-24" />
					) : (
						<div
							className={cn(
								"nova-stat-value truncate font-semibold tabular-nums tracking-normal text-foreground",
								variant === "hero"
									? "mt-2 text-4xl"
									: variant === "compact"
										? "mt-1.5 text-2xl"
										: "mt-2 text-3xl",
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
				<p className={cn("nova-stat-description text-muted-foreground", variant === "compact" ? "line-clamp-2 text-sm leading-snug" : "line-clamp-2 text-sm leading-relaxed")}>{description}</p>
			) : null}
			<div className="mt-auto flex min-w-0 flex-wrap items-center gap-2">
				{trend ? <NovaTrendBadge trend={trend} /> : null}
				{action ? <div className="ml-auto">{action}</div> : null}
			</div>
			{sparkline?.points && sparkline.points.length > 1 ? (
				<div className={cn("nova-stat-sparkline overflow-hidden rounded-lg border border-border bg-muted/40 px-2 py-1.5", variant === "compact" ? "h-9" : "h-12")}>
					<Sparkline
						points={sparkline.points}
						color="var(--color-primary)"
						fillOpacity={0.18}
						height={variant === "compact" ? 24 : 36}
						strokeWidth={1.6}
						ariaLabel={sparkline.label ?? `${String(label)} trend`}
					/>
				</div>
			) : null}
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
	const action = toolbar ? <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">{toolbar}</div> : undefined;

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
	default: "border-border bg-muted/45",
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
				"nova-inset min-w-0 rounded-lg border p-3.5",
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
				isCompact ? "min-h-[92px] px-3 py-2.5" : "min-h-[112px] px-4 py-3.5",
				NOVA_TONE_PANEL_CLASS[tone],
				className,
			)}
			{...props}
		>
			<div className="flex min-w-0 items-center justify-between gap-2">
				<p
					className={cn(
						"truncate font-medium uppercase tracking-[0.12em] text-muted-foreground",
						isCompact ? "text-xs" : "text-xs",
					)}
				>
					{label}
				</p>
				{trend ? <Badge tone="outline">{trend}</Badge> : null}
			</div>
			<div
				className={cn(
					"truncate font-semibold tracking-normal tabular-nums",
					isCompact ? "mt-1.5 text-lg" : "mt-2 text-2xl",
					NOVA_TONE_TEXT_CLASS[tone],
				)}
			>
				{value}
			</div>
			{description ? (
				<p
					className={cn(
						"line-clamp-2 text-muted-foreground",
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
				"nova-list-row min-w-0 rounded-lg border px-4 py-3.5 transition-colors",
				NOVA_TONE_PANEL_CLASS[tone],
				className,
			)}
			{...props}
		>
			<div className="flex min-w-0 items-start gap-3">
				{leading ? (
					<div className="nova-icon-box flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-card text-muted-foreground">
						{leading}
					</div>
				) : null}
				<div className="min-w-0 flex-1">
					<div className="flex min-w-0 items-start justify-between gap-3">
						<div className="min-w-0">
							<div className="line-clamp-2 text-sm font-semibold leading-snug text-foreground">
								{title}
							</div>
							{description ? (
								<div className="mt-1 line-clamp-2 text-sm leading-snug text-muted-foreground">
									{description}
								</div>
							) : null}
						</div>
						{meta || action ? (
							<div className="flex min-w-0 shrink-0 flex-wrap items-center justify-end gap-2">
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

export function NovaUsageList({
	items,
	empty,
	showMeters = true,
	className,
	...props
}: NovaUsageListProps) {
	if (items.length === 0) {
		return empty ?? null;
	}

	return (
		<div
			className={cn("nova-usage-list grid min-w-0 gap-2", className)}
			{...props}
		>
			{items.map((item, index) => (
				<NovaUsageRow
					key={index}
					item={item}
					showMeter={showMeters}
				/>
			))}
		</div>
	);
}

function NovaUsageRow({
	item,
	showMeter,
}: {
	item: NovaUsageItem;
	showMeter: boolean;
}) {
	const progress = item.progress === undefined ? undefined : Math.max(0, Math.min(100, item.progress));
	const tone = item.tone ?? "default";
	const progressLabel = progress === undefined ? undefined : `${String(item.label)} usage`;
	return (
		<div className={cn("nova-usage-row min-w-0 rounded-lg border px-3 py-3", NOVA_TONE_PANEL_CLASS[tone])}>
			<div className="flex min-w-0 items-center gap-3">
				{showMeter ? (
					<NovaUsageMeter
						value={progress}
						tone={tone}
						label={progressLabel}
					/>
				) : null}
				<div className="min-w-0 flex-1">
					<div className="flex min-w-0 items-start justify-between gap-3">
						<div className="min-w-0">
							<div className="truncate text-sm font-semibold text-foreground">
								{item.label}
							</div>
							{item.description ? (
								<div className="mt-0.5 line-clamp-2 text-xs leading-snug text-muted-foreground">
									{item.description}
								</div>
							) : null}
						</div>
						<div className="flex min-w-0 shrink-0 items-center justify-end gap-2 text-right">
							<div className="min-w-0">
								<div className={cn("truncate text-sm font-semibold tabular-nums", NOVA_TONE_TEXT_CLASS[tone])}>
									{item.value}
								</div>
								{item.limit ? (
									<div className="truncate text-[11px] text-muted-foreground">
										{item.limit}
									</div>
								) : null}
							</div>
							{item.action ? <div className="shrink-0">{item.action}</div> : null}
						</div>
					</div>
					{progress !== undefined ? (
						<Progress
							className="mt-2.5"
							value={progress}
							aria-label={progressLabel}
						/>
					) : null}
				</div>
			</div>
		</div>
	);
}

function NovaUsageMeter({
	value,
	tone,
}: {
	value?: number | undefined;
	tone: NonNullable<NovaUsageItem["tone"]>;
	label?: string | undefined;
}) {
	const fill = value === undefined ? 0 : Math.max(0, Math.min(100, value));
	const color =
		tone === "danger"
			? "var(--color-error)"
			: tone === "warning"
				? "var(--color-warning)"
				: tone === "success"
					? "var(--color-success)"
					: "var(--color-primary)";
	return (
		<div
			className="relative flex size-10 shrink-0 items-center justify-center rounded-full border border-border bg-muted"
			aria-hidden="true"
			style={{
				background:
					value === undefined
						? "var(--color-muted)"
						: `conic-gradient(${color} ${fill * 3.6}deg, var(--color-muted) 0deg)`,
			}}
		>
			<div className="flex size-7 items-center justify-center rounded-full border border-border bg-card text-[10px] font-semibold tabular-nums text-muted-foreground">
				{value === undefined ? "..." : Math.round(fill)}
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
