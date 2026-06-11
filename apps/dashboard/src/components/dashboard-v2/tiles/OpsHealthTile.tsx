import { AlertTriangle, CheckCircle2, ExternalLink, RefreshCw, ServerCog } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import { NovaCard, NovaInset, NovaListRow, NovaStat } from "@/components/ui/NovaPrimitives";
import { useOperatorSnapshot } from "@/hooks/useOperatorSnapshot";
import type { DashboardScopeProps } from "../scope";

function toneLabel(tone: string) {
	if (tone === "critical") return "Needs attention";
	if (tone === "warning") return "Watch";
	return "Healthy";
}

function toneColor(tone: string) {
	if (tone === "critical") return "var(--color-oxblood)";
	if (tone === "warning") return "var(--color-warning)";
	return "var(--color-health-good)";
}

function matchesScope(
	item: {
		account_id?: string | null | undefined;
		group_id?: string | null | undefined;
		workspace_id?: string | null | undefined;
	},
	scope: DashboardScopeProps,
) {
	if (scope.scopedAccount) return item.account_id === scope.scopedAccount.id;
	if (scope.groupId) {
		if (item.group_id === scope.groupId) return true;
		return !!item.account_id && !!scope.accountIds?.includes(item.account_id);
	}
	return true;
}

function formatValue(value: string | number | null | undefined) {
	if (value === null || value === undefined || value === "") return "0";
	return String(value);
}

export function OpsHealthTile(props: DashboardScopeProps) {
	const navigate = useNavigate();
	const { snapshot, isLoading, hasError, refetch } = useOperatorSnapshot();
	const { scopedAccount, groupId, accountIds, scopeLabel } = props;
	const [accountPage, setAccountPage] = useState(0);
	const health = snapshot.opsHealth;
	const scopedIssues = useMemo(
		() =>
			health.issues
				.filter((issue) => matchesScope(issue, { scopedAccount, groupId, accountIds }))
				.slice(0, 4),
		[health.issues, scopedAccount, groupId, accountIds],
	);
	const scopedAccounts = useMemo(
		() =>
			health.unhealthyAccounts.filter((account) =>
				matchesScope(
					{ account_id: account.accountId, group_id: account.group_id },
					{ scopedAccount, groupId, accountIds },
				),
			),
		[health.unhealthyAccounts, scopedAccount, groupId, accountIds],
	);
	const accountPageSize = 6;
	const accountPageCount = Math.max(1, Math.ceil(scopedAccounts.length / accountPageSize));
	const safeAccountPage = Math.min(accountPage, accountPageCount - 1);
	const visibleAccounts = scopedAccounts.slice(safeAccountPage * accountPageSize, (safeAccountPage + 1) * accountPageSize);
	const scopedCritical = scopedIssues.filter((issue) => issue.severity === "critical").length;
	const scopedAccountCritical = scopedAccounts.some((account) => account.severity === "critical");
	const scopedTone = scopedCritical > 0 || scopedAccountCritical ? "critical" : scopedIssues.length > 0 || scopedAccounts.length > 0 ? "warning" : health.tone;
	const displayScopeLabel = scopeLabel ?? "Visible scope";
	const topMetrics = health.metrics.slice(0, 4);

	return (
		<NovaCard
			className="h-full"
			contentClassName="p-5"
		>
				<div className="flex items-start justify-between gap-3">
					<div>
						<Badge tone="outline">Account issues</Badge>
						<div className="mt-2 flex items-baseline gap-3">
							<div className="text-4xl font-semibold tracking-[-0.04em] text-foreground">
								{isLoading ? "..." : health.score}
							</div>
							<div className="text-xs font-semibold" style={{ color: toneColor(scopedTone) }}>
								{toneLabel(scopedTone)}
							</div>
						</div>
						<div className="mt-1 text-xs text-muted-foreground">
							{displayScopeLabel} · account connections, scheduled posts, and recovery work.
						</div>
					</div>
					<div className="flex items-center gap-2">
						<Button type="button" variant="outline" size="sm" onClick={() => void refetch()} disabled={isLoading}>
							<RefreshCw className={isLoading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
							Refresh
						</Button>
						<Button type="button" size="sm" onClick={() => navigate("/reliability")}>
							Reliability
							<ExternalLink data-icon="inline-end" />
						</Button>
					</div>
				</div>

				<div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
					{topMetrics.map((metric) => (
						<NovaStat
							key={metric.key}
							label={metric.label}
							value={formatValue(metric.value)}
							variant="compact"
							status={metric.status}
							action={
								<Button
									type="button"
									variant="ghost"
									size="sm"
									onClick={() => navigate(metric.route)}
								>
									Open
								</Button>
							}
							className="bg-muted/35"
						/>
					))}
				</div>

				<NovaInset className="mt-4">
					<div className="flex items-center justify-between gap-3">
						<div>
							<div className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">Unhealthy accounts</div>
							<div className="mt-1 text-sm font-semibold text-foreground">
								{scopedAccounts.length} visible account{scopedAccounts.length === 1 ? "" : "s"} need work
							</div>
						</div>
						<div className="flex items-center gap-2">
							<Button
								type="button"
								variant="outline"
								size="sm"
								disabled={safeAccountPage === 0}
								onClick={() => setAccountPage((page) => Math.max(0, page - 1))}
							>
								Prev
							</Button>
							<div className="text-[11px] text-muted-foreground">
								{safeAccountPage + 1}/{accountPageCount}
							</div>
							<Button
								type="button"
								variant="outline"
								size="sm"
								disabled={safeAccountPage >= accountPageCount - 1}
								onClick={() => setAccountPage((page) => Math.min(accountPageCount - 1, page + 1))}
							>
								Next
							</Button>
						</div>
					</div>
					{visibleAccounts.length === 0 ? (
						<div className="mt-3 text-xs text-muted-foreground">No unhealthy accounts in this scope.</div>
					) : (
						<div className="mt-3 grid gap-2">
							{visibleAccounts.map((account) => (
								<NovaListRow
									key={`${account.platform}:${account.accountId}`}
									role="button"
									tabIndex={0}
									className="cursor-pointer"
									onClick={() => navigate(account.route)}
									onKeyDown={(event) => {
										if (event.key === "Enter" || event.key === " ") {
											event.preventDefault();
											navigate(account.route);
										}
									}}
									leading={
											<BrandLogo
												name={account.platform === "instagram" ? "instagram" : "threads"}
												size="xs"
											/>
									}
									title={`@${account.handle}`}
									description={account.reasons.join(" · ")}
									meta={
										<div className="flex items-center gap-2">
											<Badge tone="outline" className="px-1.5 py-0.5 text-[10px] uppercase">
												{account.platform}
											</Badge>
											<span className="text-[11px] font-semibold" style={{ color: toneColor(account.severity) }}>
												{account.severity}
											</span>
											<ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
										</div>
									}
								/>
							))}
						</div>
					)}
				</NovaInset>

				<div className="mt-4 grid gap-2">
					{hasError ? (
						<NovaInset className="border-dashed text-sm text-muted-foreground">
							Account issue status is unavailable. Retry once the status check settles.
						</NovaInset>
					) : scopedIssues.length === 0 && !isLoading ? (
						<NovaInset className="p-3 text-sm">
							<div className="flex items-center gap-2 font-medium text-foreground">
								<CheckCircle2 className="h-4 w-4" />
								No visible account blockers.
							</div>
							<div className="mt-1 text-muted-foreground">Posting, account connection, and recovery signals look clear for this scope.</div>
						</NovaInset>
					) : (
						scopedIssues.map((issue) => (
							<Button
								key={issue.key}
								type="button"
								variant="outline"
								className="flex h-auto min-h-14 items-center justify-start gap-3 bg-muted/35 p-3 text-left"
								onClick={() => navigate(issue.route)}
							>
								<div
									className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
									style={{
										color: toneColor(issue.severity),
										background: "color-mix(in srgb, var(--color-foreground) 5%, transparent)",
									}}
								>
									{issue.severity === "critical" ? <AlertTriangle className="h-4 w-4" /> : <ServerCog className="h-4 w-4" />}
								</div>
								<div className="min-w-0 flex-1">
									<div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
										{issue.source.replaceAll("_", " ")} · {issue.severity}
									</div>
									<div className="mt-1 truncate text-sm font-semibold text-foreground">
										{issue.title}
									</div>
								</div>
								<ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
							</Button>
						))
					)}
				</div>
		</NovaCard>
	);
}
