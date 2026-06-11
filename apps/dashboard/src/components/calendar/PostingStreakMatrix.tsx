import {
	AlertTriangle,
	CalendarDays,
	ChevronLeft,
	ChevronRight,
	Plus,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import {
	addMonthsToKey,
	formatMonthLabel,
	toLocalDateKey,
	type AccountPostingStreakRow,
	type PostingStreakCell,
	useAccountPostingStreakMatrix,
} from "@/hooks/useAccountPostingStreakMatrix";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";
import { badgeLabelFor } from "@/lib/socialPlatform";
import { scopedRoute } from "@/lib/scopedRoutes";
import type { Platform } from "./shared";

interface Props {
	monthKey: string;
	onMonthChange: (next: string) => void;
	platformFilter: Platform | "all";
	groupFilter: string;
	scopedAccount: AccountScopeValue | null;
	accountIds?: string[] | null | undefined;
	accountId?: string | null | undefined;
	accountHandle?: string | null | undefined;
	onComposeForAccountDate: (accountId: string, dateKey: string) => void;
}

export function PostingStreakMatrix({
	monthKey,
	onMonthChange,
	platformFilter,
	groupFilter,
	scopedAccount,
	accountIds,
	accountId,
	accountHandle,
	onComposeForAccountDate,
}: Props) {
	const matrix = useAccountPostingStreakMatrix({
		monthKey,
		platform: platformFilter,
		groupId: groupFilter,
		scopedAccount,
		accountIds,
		accountId,
		accountHandle,
	});
	const platformForRoute =
		platformFilter === "instagram"
			? "instagram"
			: platformFilter === "threads"
				? "threads"
				: null;

	if (matrix.hasError) {
		return (
			<NovaCard contentClassName="p-6" className="text-sm text-muted-foreground">
				Posting streaks could not be loaded. Refresh Calendar to retry.
			</NovaCard>
		);
	}

	return (
		<div className="flex flex-col gap-4">
			<NovaCard contentClassName="p-5">
				<div className="flex flex-wrap items-start justify-between gap-4">
					<div>
						<div className="text-[0.65625rem] font-bold uppercase tracking-[0.14em] text-[var(--color-oxblood)]">
							Posting streaks
						</div>
						<h2 className="mt-1 text-[1.25rem] font-semibold tracking-[-0.03em] text-foreground">
							Account-by-day cadence matrix
						</h2>
						<p className="mt-1 max-w-2xl text-[0.8125rem] leading-relaxed text-muted-foreground">
							Solid cells are published posts. Outlined cells are planned posts
							that do not count toward the streak until they publish.
						</p>
					</div>

					<div className="flex flex-wrap items-center gap-2">
						<Button
							type="button"
							variant="outline"
							size="icon"
							onClick={() => onMonthChange(addMonthsToKey(monthKey, -1))}
							aria-label="Previous month"
						>
							<ChevronLeft />
						</Button>
						<div className="min-w-[144px] rounded-md border border-border bg-card px-3 py-2 text-center text-[0.8125rem] font-semibold text-foreground">
							{formatMonthLabel(monthKey)}
						</div>
						<Button
							type="button"
							variant="outline"
							size="icon"
							onClick={() => onMonthChange(addMonthsToKey(monthKey, 1))}
							aria-label="Next month"
						>
							<ChevronRight />
						</Button>
					</div>
				</div>

				<div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
					<SummaryStat
						label="Needs post"
						value={matrix.needsPostRows.length}
						tone={matrix.needsPostRows.length > 0 ? "red" : "green"}
					/>
					<SummaryStat label="Published" value={matrix.totalPublished} />
					<SummaryStat label="Planned" value={matrix.totalScheduled} />
					<SummaryStat
						label="No posts this month"
						value={matrix.zeroPostRows.length}
						tone={matrix.zeroPostRows.length > 0 ? "gold" : "default"}
					/>
				</div>
			</NovaCard>

			<div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
				<NovaCard contentClassName="p-0">
					<div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
						<div>
							<div className="text-[0.6875rem] font-bold uppercase tracking-[0.14em] text-muted-foreground">
								{matrix.rows.length.toLocaleString()} accounts ·{" "}
								{matrix.days.length} days
							</div>
							<div className="mt-1 text-sm font-semibold text-foreground">
								Scan who posted and who needs content
							</div>
						</div>
						<div className="hidden items-center gap-2 text-[0.6875rem] text-muted-foreground md:flex">
							<span className="inline-flex items-center gap-1">
								<i className="size-2.5 rounded-[3px] bg-[var(--color-health-good)]" />{" "}
								Published
							</span>
							<span className="inline-flex items-center gap-1">
								<i className="size-2.5 rounded-[3px] border border-[var(--color-warning)]" />{" "}
								Planned
							</span>
						</div>
					</div>
					{matrix.isLoading ? (
						<div className="p-6 text-sm text-muted-foreground">
							Loading posting streaks...
						</div>
					) : matrix.rows.length === 0 ? (
						<div className="p-6">
							<div className="flex max-w-xl items-start gap-3 rounded-xl border border-border bg-muted/40 p-4">
								<CalendarDays className="mt-0.5 size-4 text-muted-foreground" />
								<div>
									<div className="text-sm font-semibold text-foreground">
										No accounts match this scope
									</div>
									<div className="mt-1 text-sm text-muted-foreground">
										Clear the account, group, or platform filter to see posting
										streaks.
									</div>
								</div>
							</div>
						</div>
					) : (
						<MatrixTable
							rows={matrix.rows}
							days={matrix.days}
							monthKey={monthKey}
							platformForRoute={platformForRoute}
							onComposeForAccountDate={onComposeForAccountDate}
						/>
					)}
				</NovaCard>

				<div className="flex flex-col gap-4">
					<NeedsPostRail
						rows={matrix.needsPostRows.slice(0, 6)}
						onComposeForAccountDate={onComposeForAccountDate}
					/>
					<LeaderRail
						title="Longest streaks"
						empty="No active streaks yet"
						rows={matrix.longestStreakRows}
					/>
					<LeaderRail
						title="No posts this month"
						empty="Every visible account has posted"
						rows={matrix.zeroPostRows.slice(0, 5)}
					/>
				</div>
			</div>
		</div>
	);
}

function SummaryStat({
	label,
	value,
	tone = "default",
}: {
	label: string;
	value: number;
	tone?: "default" | "red" | "gold" | "green";
}) {
	const color =
		tone === "red"
			? "var(--color-critical)"
			: tone === "gold"
				? "var(--color-warning)"
				: tone === "green"
					? "var(--color-health-good)"
					: "var(--color-foreground)";
	return (
		<div className="rounded-xl border border-border bg-background/45 p-3">
			<div className="text-[0.65625rem] font-bold uppercase tracking-[0.13em] text-muted-foreground">
				{label}
			</div>
			<div
				className="mt-1 text-[1.45rem] font-semibold tabular-nums tracking-[-0.04em]"
				style={{ color }}
			>
				{value.toLocaleString()}
			</div>
		</div>
	);
}

function MatrixTable({
	rows,
	days,
	monthKey,
	platformForRoute,
	onComposeForAccountDate,
}: {
	rows: AccountPostingStreakRow[];
	days: PostingStreakCell[];
	monthKey: string;
	platformForRoute: "threads" | "instagram" | null;
	onComposeForAccountDate: (accountId: string, dateKey: string) => void;
}) {
	return (
		<div className="max-h-[72vh] overflow-auto">
			<table className="w-full min-w-[1180px] border-collapse text-left">
				<thead>
					<tr className="border-b border-border bg-background/95">
						<th className="sticky left-0 top-0 z-30 w-[270px] bg-background/95 px-4 py-3 text-[0.6875rem] font-bold uppercase tracking-[0.13em] text-muted-foreground backdrop-blur">
							Account
						</th>
						{days.map((day) => (
							<th
								key={day.dateKey}
								className={`sticky top-0 z-20 px-1.5 py-3 text-center text-[0.6875rem] font-bold tabular-nums ${
									day.isToday
										? "text-[var(--color-oxblood)]"
										: "text-muted-foreground"
								}`}
							>
								{day.day}
							</th>
						))}
						<th className="sticky top-0 z-20 w-[96px] bg-background/95 px-3 py-3 text-right text-[0.6875rem] font-bold uppercase tracking-[0.13em] text-muted-foreground backdrop-blur">
							Streak
						</th>
						<th className="sticky top-0 z-20 w-[112px] bg-background/95 px-4 py-3 text-right text-[0.6875rem] font-bold uppercase tracking-[0.13em] text-muted-foreground backdrop-blur">
							Last post
						</th>
					</tr>
				</thead>
				<tbody>
					{rows.map((row) => {
						const accountRoute = scopedRoute(
							"/calendar",
							{
								scopedAccount: {
									id: row.accountId,
									handle: row.handle,
									platform: row.platform,
								},
								platform: platformForRoute ?? row.platform,
							},
							{ view: "streaks", month: monthKey },
						);
						return (
							<tr
								key={`${row.platform}:${row.accountId}`}
								className={`border-b border-border/80 last:border-b-0 ${
									row.needsPost
										? "bg-[color-mix(in_srgb,var(--color-oxblood)_4%,transparent)]"
										: ""
								}`}
							>
								<td className="sticky left-0 z-10 bg-background/95 px-4 py-3 backdrop-blur">
									<Link
										to={accountRoute}
										className="group flex min-w-0 items-center gap-3"
									>
										<span
											className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[0.75rem] font-bold text-white"
											style={{ backgroundColor: row.groupColor }}
										>
											{row.handle.replace(/^@/, "").slice(0, 1).toUpperCase() ||
												"A"}
										</span>
										<span className="min-w-0">
											<span className="flex items-center gap-2">
												<span className="truncate text-sm font-semibold text-foreground group-hover:text-[var(--color-oxblood)]">
													{row.handle}
												</span>
												<Badge tone="outline">{badgeLabelFor(row.platform)}</Badge>
											</span>
											<span className="mt-0.5 block truncate text-[0.6875rem] text-muted-foreground">
												{row.groupName} · {row.postsThisMonth} published ·{" "}
												{row.scheduledThisMonth} planned
											</span>
										</span>
									</Link>
								</td>
								{row.cells.map((cell) => (
									<td key={cell.dateKey} className="px-1.5 py-2">
										<StreakCellButton
											cell={cell}
											accountHandle={row.handle}
											needsPost={row.needsPost}
											onClick={() => {
												if (
													cell.publishedCount === 0 &&
													cell.scheduledCount === 0
												) {
													onComposeForAccountDate(row.accountId, cell.dateKey);
												}
											}}
										/>
									</td>
								))}
								<td className="px-3 py-3 text-right text-sm font-semibold tabular-nums text-foreground">
									{row.currentStreak}d
								</td>
								<td className="px-4 py-3 text-right text-xs text-muted-foreground">
									{row.lastPublishedLabel}
								</td>
							</tr>
						);
					})}
				</tbody>
			</table>
		</div>
	);
}

function StreakCellButton({
	cell,
	accountHandle,
	needsPost,
	onClick,
}: {
	cell: PostingStreakCell;
	accountHandle: string;
	needsPost: boolean;
	onClick: () => void;
}) {
	const hasPublished = cell.publishedCount > 0;
	const hasScheduled = cell.scheduledCount > 0;
	const canSchedule =
		!hasPublished && !hasScheduled && (cell.isToday || cell.isFuture);
	const title = `${accountHandle} · ${cell.dateKey} · ${
		hasPublished
			? `${cell.publishedCount} published`
			: hasScheduled
				? `${cell.scheduledCount} planned`
				: "no post"
	}`;
	return (
		<Button
			type="button"
			variant="ghost"
			size="icon"
			onClick={onClick}
			title={title}
			aria-label={title}
			disabled={!canSchedule}
			className={`mx-auto size-8 rounded-[8px] text-[0.6875rem] font-bold tabular-nums transition-transform ${
				canSchedule ? "hover:-translate-y-0.5" : "cursor-default"
			}`}
			style={{
				color: hasPublished
					? "white"
					: hasScheduled
						? "var(--color-warning)"
						: "var(--color-muted-foreground)",
				background: hasPublished
					? "linear-gradient(135deg, var(--color-health-good), color-mix(in srgb, var(--color-health-good) 58%, var(--color-foreground)))"
					: hasScheduled
						? "color-mix(in srgb, var(--color-warning) 8%, transparent)"
						: cell.isToday && needsPost
							? "color-mix(in srgb, var(--color-critical) 7%, transparent)"
							: "color-mix(in srgb, var(--color-foreground) 4%, transparent)",
				border: hasPublished
					? "1px solid color-mix(in srgb, var(--color-health-good) 55%, transparent)"
					: hasScheduled
						? "1px solid color-mix(in srgb, var(--color-warning) 42%, transparent)"
						: cell.isToday && needsPost
							? "1px solid color-mix(in srgb, var(--color-critical) 44%, transparent)"
							: "1px solid color-mix(in srgb, var(--color-foreground) 8%, transparent)",
				boxShadow:
					cell.isToday && needsPost
						? "0 0 0 2px color-mix(in srgb, var(--color-critical) 12%, transparent)"
						: undefined,
			}}
		>
			{hasPublished
				? cell.publishedCount
				: hasScheduled
					? cell.scheduledCount
					: ""}
		</Button>
	);
}

function NeedsPostRail({
	rows,
	onComposeForAccountDate,
}: {
	rows: AccountPostingStreakRow[];
	onComposeForAccountDate: (accountId: string, dateKey: string) => void;
}) {
	const todayLocalKey = toLocalDateKey(new Date());
	return (
		<NovaCard contentClassName="p-5">
			<div className="flex items-center justify-between gap-3">
				<div>
					<div className="text-[0.65625rem] font-bold uppercase tracking-[0.14em] text-[var(--color-critical)]">
						Needs posts today
					</div>
					<div className="mt-1 text-sm font-semibold text-foreground">
						Idle 48h+ accounts
					</div>
				</div>
				<AlertTriangle className="size-4 text-[var(--color-critical)]" />
			</div>
			<div className="mt-4 flex flex-col gap-3">
				{rows.length === 0 ? (
					<div className="rounded-xl border border-border bg-muted/40 p-3 text-sm text-muted-foreground">
						No visible accounts need posts.
					</div>
				) : (
					rows.map((row) => (
						<div
							key={row.accountId}
							className="flex items-center justify-between gap-3"
						>
							<div className="min-w-0">
								<div className="truncate text-sm font-semibold text-foreground">
									{row.handle}
								</div>
								<div className="text-xs text-muted-foreground">
									{row.lastPublishedLabel}
								</div>
							</div>
							<Button
								type="button"
								size="sm"
								onClick={() =>
									onComposeForAccountDate(row.accountId, todayLocalKey)
								}
								className="shrink-0"
							>
								<Plus data-icon="inline-start" />
								Post
							</Button>
						</div>
					))
				)}
			</div>
		</NovaCard>
	);
}

function LeaderRail({
	title,
	empty,
	rows,
}: {
	title: string;
	empty: string;
	rows: AccountPostingStreakRow[];
}) {
	return (
		<NovaCard contentClassName="p-5">
			<div className="text-[0.65625rem] font-bold uppercase tracking-[0.14em] text-muted-foreground">
				{title}
			</div>
			<div className="mt-3 flex flex-col gap-2">
				{rows.length === 0 ? (
					<div className="text-sm text-muted-foreground">{empty}</div>
				) : (
					rows.map((row) => (
						<div
							key={row.accountId}
							className="flex items-center justify-between gap-3 text-sm"
						>
							<span className="min-w-0 truncate font-medium text-foreground">
								{row.handle}
							</span>
							<span className="shrink-0 text-muted-foreground tabular-nums">
								{row.currentStreak > 0
									? `${row.currentStreak}d`
									: row.lastPublishedLabel}
							</span>
						</div>
					))
				)}
			</div>
		</NovaCard>
	);
}
