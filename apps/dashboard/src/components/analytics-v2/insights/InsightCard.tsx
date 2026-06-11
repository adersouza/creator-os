import { Badge } from "@/components/ui/Badge";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { cn } from "@/lib/utils";

export interface InsightBar {
	label: string;
	value: string;
	/** 0-100 fill percentage. */
	pct: number;
	tone: "ox" | "gold" | "neg" | "dim";
}

export interface InsightCardSpec {
	timestamp: string;
	subtitle: string;
	title: string;
	body: string;
	chips?: string[] | undefined;
	bars?: InsightBar[] | undefined;
	footerLabel?: string | undefined;
	footerValue?: string | undefined;
	footerTone?: "ox" | "good" | "neg" | "gold" | undefined;
	evidenceLabel?: string | undefined;
	evidenceValue?: string | undefined;
}

/**
 * Spec §5 insight card. Three content variants — chips (cluster accounts),
 * bars (mini metric strip), or footer (single label/value pair). Variant
 * selection is by which field the spec supplies; all three can coexist.
 * Hover lift + oxblood border shift via the shared .tile-link utility.
 *
 * `onClick` is optional — when provided, the card behaves as a button
 * (cursor + keyboard activation). When omitted, the card is a plain
 * <article> with no false affordance.
 */
export function InsightCard({
	spec,
	onClick,
}: {
	spec: InsightCardSpec;
	onClick?: (() => void) | undefined;
}) {
	const interactive = !!onClick;
	const content = (
		<>
			<div className="mb-3 flex items-center justify-end">
				<Badge tone="outline">{spec.timestamp || "recent"}</Badge>
			</div>
			<span className="text-sm font-medium text-primary">{spec.subtitle}</span>
			<h3 className="mt-1 text-[0.9375rem] font-medium leading-snug text-foreground">
				{spec.title}
			</h3>
			<p className="mt-2 line-clamp-4 text-[0.78125rem] leading-snug text-muted-foreground">
				{spec.body}
			</p>
			{spec.chips?.length ? (
				<div className="mt-3 flex flex-wrap gap-1.5">
					{spec.chips.map((chip) => (
						<Badge key={chip} tone="secondary">
							{chip}
						</Badge>
					))}
				</div>
			) : null}
			{spec.bars?.length ? (
				<div className="mt-4 flex flex-col gap-2">
					{spec.bars.map((bar) => (
						<div key={bar.label}>
							<div className="flex items-center justify-between gap-2 text-[0.6875rem]">
								<span className="truncate text-muted-foreground">
									{bar.label}
								</span>
								<span className="app-data text-muted-foreground">
									{bar.value}
								</span>
							</div>
							<div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
								<div
									className={`h-full rounded-full ${bar.tone === "ox" ? "bg-[color:var(--color-selected)]" : bar.tone === "gold" ? "bg-[color:var(--color-warning)]" : bar.tone === "neg" ? "bg-[color:var(--color-critical)]" : "bg-label-tertiary"}`}
									style={{ width: `${Math.max(0, Math.min(100, bar.pct))}%` }}
								/>
							</div>
						</div>
					))}
				</div>
			) : null}
			{spec.footerLabel || spec.footerValue ? (
				<div className="mt-auto flex items-center justify-between gap-3 pt-4">
					<span className="text-xs font-medium text-muted-foreground">
						{spec.footerLabel}
					</span>
					<span
						className={`app-data text-[0.75rem] font-bold ${
							spec.footerTone === "good"
								? "text-[color:var(--color-health-good)]"
								: spec.footerTone === "neg"
									? "text-[color:var(--color-critical)]"
									: spec.footerTone === "gold"
										? "text-[color:var(--color-warning)]"
										: spec.footerTone === "ox"
											? "text-[color:var(--color-selected)]"
											: "text-muted-foreground"
						}`}
					>
						{spec.footerValue}
					</span>
				</div>
			) : null}
			{spec.evidenceLabel && spec.evidenceValue ? (
				<div className="mt-auto flex items-center justify-between gap-3 border-t border-dashed border-border pt-3 text-[0.625rem] uppercase tracking-[0.08em]">
					<span className="text-muted-foreground/75">{spec.evidenceLabel}</span>
					<span className="app-data min-w-0 truncate text-right text-muted-foreground">
						{spec.evidenceValue}
					</span>
				</div>
			) : null}
		</>
	);
	if (!interactive) {
		return (
			<NovaCard className="h-full w-full" contentClassName="flex h-full flex-col">
				{content}
			</NovaCard>
		);
	}
	return (
		<NovaCard
			className={cn(
				"h-full w-full cursor-pointer transition-colors hover:border-primary/50 hover:bg-muted/20",
			)}
			contentClassName="flex h-full flex-col"
			onClick={onClick}
			onKeyDown={(e) => {
				if (e.key === "Enter" || e.key === " ") {
					e.preventDefault();
					onClick?.();
				}
			}}
			role="button"
			aria-label={`Open insight: ${spec.title}`}
			tabIndex={0}
		>
			{content}
		</NovaCard>
	);
}
