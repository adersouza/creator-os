import { AlertTriangle, CheckCircle2, Circle, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ListRow } from "@/components/ui/ListRow";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Progress } from "@/components/ui/Progress";
import { cn } from "@/lib/utils";
import type { PublishingReadinessIssue } from "@/types/publishingReadiness";

export type UnifiedReadinessTone = "ready" | "warning" | "blocked";

export interface UnifiedReadinessCheck {
	id: string;
	label: string;
	detail: string;
	tone: UnifiedReadinessTone;
	action?: (() => void) | undefined;
	actionLabel?: string | undefined;
}

export interface UnifiedPostHealth {
	score: number;
	label: string;
	tone: "ready" | "warning" | "blocked";
	issues: string[];
}

const checkToneClass: Record<UnifiedReadinessTone, string> = {
	ready: "text-[color:var(--color-positive)]",
	warning: "text-[color:var(--color-gold)]",
	blocked: "text-[color:var(--color-oxblood)]",
};

const setupToneClass: Record<PublishingReadinessIssue["state"], string> = {
	ready: "text-[color:var(--color-positive)]",
	needs_setup: "text-[color:var(--color-gold)]",
	warning: "text-[color:var(--color-gold)]",
	blocked: "text-[color:var(--color-oxblood)]",
};

function scoreTone(tone: UnifiedPostHealth["tone"]) {
	return tone === "ready" ? "good" : tone === "warning" ? "warn" : "critical";
}

function statusLabel({
	blocked,
	warnings,
	setupCount,
}: {
	blocked: number;
	warnings: number;
	setupCount: number;
}) {
	if (blocked > 0) return `${blocked} blocked`;
	if (setupCount > 0) return `${setupCount} setup`;
	if (warnings > 0) return `${warnings} warning${warnings === 1 ? "" : "s"}`;
	return "Ready";
}

function CheckIcon({ tone }: { tone: UnifiedReadinessTone }) {
	const Icon =
		tone === "ready"
			? CheckCircle2
			: tone === "blocked"
				? AlertTriangle
				: Circle;
	return (
		<Icon
			className={cn("mt-0.5 size-4 shrink-0", checkToneClass[tone])}
			aria-hidden="true"
		/>
	);
}

function SetupIcon({ state }: { state: PublishingReadinessIssue["state"] }) {
	const Icon =
		state === "ready"
			? CheckCircle2
			: state === "blocked"
				? AlertTriangle
				: Circle;
	return (
		<Icon
			className={cn("mt-0.5 size-4 shrink-0", setupToneClass[state])}
			aria-hidden="true"
		/>
	);
}

export function UnifiedPublishingReadinessCard({
	checks,
	setupIssues,
	postHealth,
	onCheckAction,
	onSetupIssueAction,
}: {
	checks: UnifiedReadinessCheck[];
	setupIssues: PublishingReadinessIssue[];
	postHealth: UnifiedPostHealth;
	onCheckAction?: ((check: UnifiedReadinessCheck) => void) | undefined;
	onSetupIssueAction?: ((issue: PublishingReadinessIssue) => void) | undefined;
}) {
	const blocked = checks.filter((check) => check.tone === "blocked").length;
	const warnings = checks.filter((check) => check.tone === "warning").length;
	const visibleSetupIssues = setupIssues.filter(
		(issue) => issue.state !== "ready",
	);
	const ready =
		blocked === 0 &&
		warnings === 0 &&
		visibleSetupIssues.length === 0 &&
		postHealth.tone === "ready";

	return (
		<NovaCard
			eyebrow={
				<span className="inline-flex min-w-0 items-start gap-2">
					<ShieldCheck
						className="mt-0.5 size-4 shrink-0 text-muted-foreground"
						aria-hidden="true"
					/>
					Publishing readiness
				</span>
			}
			description="Account setup, format checks, and final publish path in one place."
			action={
				<Badge tone={blocked > 0 ? "oxblood" : ready ? "secondary" : "outline"}>
					{statusLabel({
						blocked,
						warnings,
						setupCount: visibleSetupIssues.length,
					})}
				</Badge>
			}
		>
			<div className="flex flex-col gap-4">
				<div>
					<div className="mb-2 flex items-center justify-between gap-3">
						<div className="text-[0.8125rem] font-medium text-foreground">
							Post health: {postHealth.label}
						</div>
						<div className="text-[0.8125rem] font-semibold tabular-nums text-foreground">
							{postHealth.score}/100
						</div>
					</div>
					<Progress
						value={postHealth.score}
						tone={scoreTone(postHealth.tone)}
						aria-label="Post health score"
					/>
				</div>

				{ready ? (
					<NovaEmpty
						className="min-h-20 px-3 py-3"
						title="Ready to publish"
						description="No obvious blockers. Server preflight still verifies the final publish path."
					/>
				) : (
					<div className="overflow-hidden rounded-md border border-border">
						{checks.map((check) => (
							<ListRow key={check.id} density="compact">
								<div className="flex items-start gap-2">
									<CheckIcon tone={check.tone} />
									<div className="min-w-0 flex-1">
										<div className="text-[0.8125rem] font-medium text-foreground">
											{check.label}
										</div>
										<div className="mt-0.5 text-[0.71875rem] leading-snug text-muted-foreground">
											{check.detail}
										</div>
									</div>
									{check.action && check.actionLabel ? (
										<Button
											type="button"
											variant="outline"
											size="sm"
											onClick={() => {
												onCheckAction?.(check);
												check.action?.();
											}}
											className="h-7 shrink-0 px-2 text-[0.71875rem]"
										>
											{check.actionLabel}
										</Button>
									) : null}
								</div>
							</ListRow>
						))}

						{visibleSetupIssues.map((issue) => (
							<ListRow key={issue.id} density="compact">
								<div className="flex items-start gap-2">
									<SetupIcon state={issue.state} />
									<div className="min-w-0 flex-1">
										<div className="text-[0.8125rem] font-medium text-foreground">
											{issue.label}
										</div>
										<div className="mt-0.5 text-[0.71875rem] leading-snug text-muted-foreground">
											{issue.detail}
										</div>
									</div>
									{issue.action && issue.actionLabel ? (
										<Button
											type="button"
											variant="outline"
											size="sm"
											onClick={() => {
												onSetupIssueAction?.(issue);
												issue.action?.();
											}}
											className="h-7 shrink-0 px-2 text-[0.71875rem]"
										>
											{issue.actionLabel}
										</Button>
									) : null}
								</div>
							</ListRow>
						))}
					</div>
				)}
			</div>
		</NovaCard>
	);
}
