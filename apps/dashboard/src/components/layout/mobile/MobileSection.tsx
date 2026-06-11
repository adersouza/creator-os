import type { ReactNode } from "react";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { cn } from "@/lib/utils";

interface MobileSectionProps {
	title?: ReactNode;
	subtitle?: ReactNode;
	right?: ReactNode;
	density?: "default" | "compact";
	as?: "section" | "div";
	className?: string | undefined;
	children: ReactNode;
}

export function MobileSection({
	title,
	subtitle,
	right,
	density = "default",
	as = "section",
	className,
	children,
}: MobileSectionProps) {
	const Tag = as;
	const showHeader = title !== undefined || right !== undefined;
	if (Tag === "section") {
		return (
			<NovaCard
				className={cn("mb-3", className)}
				contentClassName={cn(density === "compact" ? "p-3" : "p-4")}
			>
				<MobileSectionContent title={title} subtitle={subtitle} right={right} showHeader={showHeader}>
					{children}
				</MobileSectionContent>
			</NovaCard>
		);
	}
	return (
		<Tag
			className={cn(
				"mb-3 rounded-lg border border-border bg-card text-card-foreground shadow-sm",
				density === "compact" ? "p-3" : "p-4",
				className,
			)}
		>
			<MobileSectionContent title={title} subtitle={subtitle} right={right} showHeader={showHeader}>
				{children}
			</MobileSectionContent>
		</Tag>
	);
}

function MobileSectionContent({
	title,
	subtitle,
	right,
	showHeader,
	children,
}: Pick<MobileSectionProps, "title" | "subtitle" | "right" | "children"> & {
	showHeader: boolean;
}) {
	return (
		<>
			{showHeader ? (
				<div className="mb-2 flex items-baseline justify-between gap-2">
					{title !== undefined ? (
						<div className="min-w-0">
							<div className="truncate text-[0.8125rem] font-medium text-foreground">
								{title}
							</div>
							{subtitle !== undefined ? (
								<div className="mt-0.5 truncate text-[0.6875rem] text-muted-foreground">
									{subtitle}
								</div>
							) : null}
						</div>
					) : (
						<span aria-hidden="true" />
					)}
					{right !== undefined ? (
						<div className="flex shrink-0 items-center gap-2">{right}</div>
					) : null}
				</div>
			) : null}
			{children}
		</>
	);
}
