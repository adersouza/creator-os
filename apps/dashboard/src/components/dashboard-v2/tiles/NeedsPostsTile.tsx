import { Link } from "react-router-dom";
import { AlertTriangle, CalendarDays } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import {
	currentMonthKey,
	useAccountPostingStreakMatrix,
	type PostingStreakPlatform,
} from "@/hooks/useAccountPostingStreakMatrix";
import { scopedRoute } from "@/lib/scopedRoutes";
import type { DashboardScopeProps } from "../scope";

interface Props extends DashboardScopeProps {
	platform?: PostingStreakPlatform | undefined;
}

export function NeedsPostsTile({
	platform = "all",
	scopedAccount,
	accountIds,
	groupId,
	scopeLabel,
}: Props) {
	const matrix = useAccountPostingStreakMatrix({
		monthKey: currentMonthKey(),
		platform,
		groupId,
		scopedAccount,
		accountIds,
	});
	const urgentRows = matrix.needsPostRows.slice(0, 4);
	const count = matrix.needsPostRows.length;
	const status = matrix.isLoading ? "Syncing" : count > 0 ? `${count} idle` : "Clear";
	const calendarHref = scopedRoute(
		"/calendar",
		{
			scopedAccount,
			accountIds,
			groupId,
			platform,
		},
		{ view: "streaks" },
	);

	return (
		<NovaCard
			className="h-full"
			contentClassName="flex h-full flex-col gap-3"
			eyebrow="Needs posts"
			title={
				<span
					className={
						count > 0
							? "block text-[34px] font-semibold leading-none tracking-[-0.04em] text-primary"
							: "block text-[34px] font-semibold leading-none tracking-[-0.04em] text-foreground"
					}
				>
					{matrix.isLoading ? "..." : count}
				</span>
			}
			description={`${scopeLabel ?? "Visible scope"} · idle 48h+ by published posts.`}
			action={
				<Badge tone={count > 0 ? "oxblood" : "secondary"}>{status}</Badge>
			}
			footer={
				<Button asChild size="sm" variant={count > 0 ? "default" : "outline"}>
					<Link to={calendarHref}>Open streaks</Link>
				</Button>
			}
		>
			<div className="mb-3 flex justify-end">
				<div
					className={
						count > 0
							? "inline-flex size-9 items-center justify-center rounded-md border border-border bg-muted text-primary"
							: "inline-flex size-9 items-center justify-center rounded-md border border-border bg-muted text-[color:var(--color-health-good)]"
					}
				>
					{count > 0 ? <AlertTriangle aria-hidden="true" /> : <CalendarDays aria-hidden="true" />}
				</div>
			</div>
			<div className="grid gap-2">
				{matrix.isLoading ? (
					<div className="grid gap-2 rounded-lg border border-border bg-muted/35 p-3">
						<Skeleton className="h-4 w-3/4" />
						<Skeleton className="h-4 w-1/2" />
					</div>
				) : urgentRows.length === 0 ? (
					<NovaEmpty
						className="min-h-24 p-4"
						title="No accounts need posts"
						description="No visible accounts need posts right now."
					/>
				) : (
					urgentRows.map((row) => (
						<div
							key={`${row.platform}:${row.accountId}`}
							className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/35 px-2.5 py-2"
						>
							<span className="min-w-0 truncate text-xs font-semibold text-foreground">
								{row.handle}
							</span>
							<span className="shrink-0 tabular-nums text-[11px] text-muted-foreground">
								{row.lastPublishedLabel}
							</span>
						</div>
					))
				)}
			</div>
		</NovaCard>
	);
}
