import { AlertTriangle, CheckCircle2, Circle, Smartphone } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ListRow } from "@/components/ui/ListRow";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { cn } from "@/lib/utils";
import { summarizeReadinessState } from "@/lib/publishingReadiness";
import type { PublishingReadinessIssue } from "@/types/publishingReadiness";

const toneClass = {
	ready: "text-[var(--color-health-good)]",
	needs_setup: "text-[var(--color-gold)]",
	warning: "text-[var(--color-gold)]",
	blocked: "text-[var(--color-oxblood)]",
};

export function PublishingReadinessPanel({
	issues,
	title = "Publishing readiness",
	compact = false,
	onIssueAction,
}: {
	issues: PublishingReadinessIssue[];
	title?: string | undefined;
	compact?: boolean | undefined;
	onIssueAction?: ((issue: PublishingReadinessIssue) => void) | undefined;
}) {
	const state = summarizeReadinessState(issues);
	const visible = compact
		? issues.filter((issue) => issue.state !== "ready").slice(0, 4)
		: issues;
	return (
		<NovaCard
			eyebrow={
				<span className="inline-flex items-center gap-2">
					<Smartphone
						className="h-4 w-4 text-muted-foreground"
						aria-hidden="true"
					/>
					{title}
				</span>
			}
			action={
				<Badge
					tone={
						state === "ready"
							? "secondary"
							: state === "blocked"
								? "danger"
								: "outline"
					}
				>
					{state.replace("_", " ")}
				</Badge>
			}
			contentClassName="p-0"
		>
			<div className="overflow-hidden">
				{visible.length === 0 ? (
					<NovaEmpty
						className="min-h-20 px-3 py-3"
						title="Ready to publish"
						description="Everything required for publishing is ready."
					/>
				) : (
					visible.map((issue) => (
						<ListRow key={issue.id} density="compact" separator>
							<div className="flex items-start gap-2">
								<span className={cn("mt-0.5 shrink-0", toneClass[issue.state])}>
									{issue.state === "ready" ? (
										<CheckCircle2 className="h-4 w-4" aria-hidden="true" />
									) : issue.state === "blocked" ? (
										<AlertTriangle className="h-4 w-4" aria-hidden="true" />
									) : (
										<Circle className="h-4 w-4" aria-hidden="true" />
									)}
								</span>
								<div className="min-w-0 flex-1">
									<div className="text-[0.8125rem] font-medium text-foreground">
										{issue.label}
									</div>
									<div className="mt-0.5 text-[0.71875rem] leading-snug text-muted-foreground">
										{issue.detail}
									</div>
								</div>
								{issue.actionLabel && (
									<Button
										type="button"
										variant="outline"
										size="sm"
										onClick={() => {
											onIssueAction?.(issue);
											issue.action?.();
										}}
										className="h-7 shrink-0 px-2 text-[0.71875rem]"
									>
										{issue.actionLabel}
									</Button>
								)}
							</div>
						</ListRow>
					))
				)}
			</div>
		</NovaCard>
	);
}
