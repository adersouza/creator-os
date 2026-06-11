import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Check, Clock3, ExternalLink, RefreshCw, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { useOperatorSnapshot, type OperatorTask } from "@/hooks/useOperatorSnapshot";
import { scopedRoute } from "@/lib/scopedRoutes";
import type { DashboardScopeProps } from "../scope";

function priorityRank(priority: string | null | undefined) {
	if (priority === "critical") return 0;
	if (priority === "high") return 1;
	if (priority === "medium") return 2;
	return 3;
}

function formatDue(value: string | null | undefined) {
	if (!value) return "No SLA";
	const time = Date.parse(value);
	if (!Number.isFinite(time)) return "No SLA";
	const deltaMs = time - Date.now();
	const absMin = Math.max(1, Math.round(Math.abs(deltaMs) / 60_000));
	if (deltaMs < 0) return `${absMin < 60 ? `${absMin}m` : `${Math.floor(absMin / 60)}h`} overdue`;
	if (absMin < 60) return `Due in ${absMin}m`;
	if (absMin < 60 * 24) return `Due in ${Math.floor(absMin / 60)}h`;
	return `Due in ${Math.floor(absMin / (60 * 24))}d`;
}

function actionRecord(task: OperatorTask): Record<string, unknown> {
	const value = task.recommended_action;
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

function routeForTask(task: OperatorTask, scope: DashboardScopeProps) {
	const action = actionRecord(task);
	const type = typeof action.type === "string" ? action.type : task.source;
	if (type === "reconnect_account" || type === "refresh_account_token" || task.source?.startsWith("token_")) {
		return "/accounts?status=flagged";
	}
	if (type === "review_approval" || task.source === "approval") {
		const approvalId = typeof action.approval_id === "string" ? action.approval_id : task.linked_entity_id;
		return approvalId ? `/approval-queue?approvalId=${approvalId}` : "/approval-queue";
	}
	if (type === "recover_failed_post" || task.source === "failed_publish") {
		return scopedRoute("/calendar", scope, {
			status: "failed",
			postId: task.linked_entity_id ?? task.source_id ?? undefined,
		});
	}
	if (type === "recover_sync_job" || type === "inspect_stale_sync" || task.source?.startsWith("sync_")) {
		return "/accounts?status=flagged";
	}
	if (type === "replay_webhook_delivery" || type === "inspect_webhook_delivery" || task.source === "webhook_delivery") {
		return "/settings?tab=webhooks";
	}
	if (type === "run_overdue_report" || task.source === "report_overdue") {
		return "/reports";
	}
	if (type === "review_inbox_item" || task.source === "inbox_attention") {
		return scopedRoute("/inbox", scope, {
			messageId: task.linked_entity_id ?? task.source_id ?? undefined,
		});
	}
	if (type === "review_listening_signal" || task.source === "listening_signal") {
		return scopedRoute("/listening", scope, {
			resultId: task.linked_entity_id ?? task.source_id ?? undefined,
		});
	}
	if (type === "inspect_failed_cron" || type === "inspect_stale_cron" || task.source?.startsWith("cron_")) {
		return "/settings?tab=ops";
	}
	return scopedRoute("/analytics", scope, { source: ["operator", "task"].join("-") });
}

function matchesScope(task: OperatorTask, scope: DashboardScopeProps) {
	if (scope.scopedAccount) {
		return task.account_id === scope.scopedAccount.id;
	}
	if (scope.groupId) {
		if (task.group_id === scope.groupId) return true;
		return !!task.account_id && !!scope.accountIds?.includes(task.account_id);
	}
	return true;
}

function labelForTask(task: OperatorTask) {
	if (task.source === "approval") return "Approval";
	if (task.source === "failed_publish") return "Failed post";
	if (task.source === "token_reauth") return "Reconnect";
	if (task.source === "token_expiring") return "Token";
	if (task.source === "sync_failed") return "Sync";
	if (task.source === "sync_stale") return "Stale sync";
	if (task.source === "webhook_delivery") return "Webhook";
	if (task.source === "report_overdue") return "Report";
	if (task.source === "inbox_attention") return "Inbox";
	if (task.source === "listening_signal") return "Listening";
	if (task.source === "cron_failed") return "Cron";
	if (task.source === "cron_stale") return "Stale cron";
	return task.source?.replaceAll("_", " ") || "Task";
}

export function OperatorTaskQueueTile(props: DashboardScopeProps) {
	const navigate = useNavigate();
	const { scopedAccount, accountIds, groupId, scopeLabel } = props;
	const { snapshot, isLoading, hasError, refetch, updateTask } = useOperatorSnapshot();
	const rows = useMemo(
		() =>
			snapshot.tasks
				.filter((task) => matchesScope(task, { scopedAccount, accountIds, groupId }))
				.filter((task) => !["resolved", "ignored"].includes(task.status || ""))
				.sort((a, b) => priorityRank(a.priority) - priorityRank(b.priority))
				.slice(0, 5),
		[snapshot.tasks, scopedAccount, accountIds, groupId],
	);
	const highCount = rows.filter((task) => ["critical", "high"].includes(task.priority || "")).length;
	const displayedScopeLabel = scopeLabel ?? "Visible scope";

	return (
		<NovaCard className="h-full" contentClassName="flex h-full flex-col">
				<div className="flex items-start justify-between gap-3">
					<div>
						<span className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Morning queue</span>
						<div className="mt-2 flex items-baseline gap-3">
							<div className="text-4xl font-semibold tracking-[-0.04em] text-foreground tabular-nums">
								{isLoading ? "..." : rows.length}
							</div>
							<div className="text-xs text-muted-foreground">
								{highCount > 0 ? `${highCount} high priority` : "No urgent blockers"}
							</div>
						</div>
						<div className="mt-1 text-xs text-muted-foreground">
							{displayedScopeLabel} · approvals, failed publishes, inbox, listening, and health.
						</div>
					</div>
					<div className="flex items-center gap-2">
						<Button
							type="button"
							size="sm"
							variant="outline"
							onClick={() => void refetch()}
							disabled={isLoading}
						>
							<RefreshCw data-icon="inline-start" className={isLoading ? "animate-spin" : undefined} />
							Refresh
						</Button>
						<Button
							type="button"
							size="sm"
							onClick={() => navigate("/approval-queue")}
						>
							Queue
							<ExternalLink data-icon="inline-end" />
						</Button>
					</div>
				</div>

				<div className="mt-4 grid gap-2">
					{hasError ? (
						<NovaEmpty
							className="min-h-24 p-4"
							title="Queue unavailable"
							description="Operator snapshot is unavailable. Retry from the queue when the API settles."
						/>
					) : rows.length === 0 && !isLoading ? (
						<NovaEmpty
							className="min-h-24 p-4"
							icon={<Check data-icon aria-hidden="true" />}
							title="No visible operator tasks."
							description="Nothing is waiting on approval, recovery, or daily triage in this scope."
						/>
					) : (
						rows.map((task) => (
							<div
								key={task.id}
								className="flex items-center gap-3 rounded-md border border-border bg-muted/35 p-3"
							>
								<div
									className={
										["critical", "high"].includes(task.priority || "")
											? "flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-primary"
											: "flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground"
									}
								>
									<ShieldAlert aria-hidden="true" />
								</div>
								<Button
									type="button"
									variant="ghost"
									className="h-auto min-w-0 flex-1 justify-start p-0 text-left hover:bg-transparent"
									onClick={() => navigate(routeForTask(task, props))}
								>
									<div className="flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
										<span>{labelForTask(task)}</span>
										<span>·</span>
										<Badge tone={["critical", "high"].includes(task.priority || "") ? "danger" : "secondary"}>
											{task.priority || "medium"}
										</Badge>
										<span>·</span>
										<span className="inline-flex items-center gap-1">
											<Clock3 aria-hidden="true" />
											{formatDue(task.sla_at ?? task.due_at)}
										</span>
									</div>
									<div className="mt-1 truncate text-sm font-semibold text-foreground">
										{task.title || "Operator task"}
									</div>
								</Button>
								<Button
									type="button"
									size="sm"
									variant="outline"
									disabled={updateTask.isPending}
									onClick={() =>
										updateTask.mutate({
											id: task.id,
											status: "resolved",
											resolutionReason: "Resolved from dashboard morning queue",
										})
									}
								>
									<Check data-icon="inline-start" />
									Done
								</Button>
							</div>
						))
					)}
				</div>
		</NovaCard>
	);
}
