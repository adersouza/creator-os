// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { usePendingRepliesQueue } from "@/hooks/usePendingRepliesQueue";
import { useQuoteReplyRatio } from "@/hooks/useQuoteReplyRatio";
import { useReachAnomalies } from "@/hooks/useReachAnomalies";
import { useReplyDepthLeaders } from "@/hooks/useReplyDepthLeaders";
import {
	EMPTY_THREAD_TOTALS,
	useThreadsPostTotals,
} from "@/hooks/useThreadsPostTotals";
import { useViewsBySource } from "@/hooks/useViewsBySource";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { accountDetailPath } from "@/lib/deepLinks";
import { scopedRoute } from "@/lib/scopedRoutes";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import { Avatar } from "../atoms/Avatar";
import { TrafficDot } from "../atoms/TrafficDot";
import type { DashboardScopeProps } from "../scope";

// Tiny 4-stat display used by ConversationWinnerTile mockup #19.
function WinnerStat({ label, value }: { label: string; value: string }) {
	return (
		<div className="min-w-0 rounded-lg border border-border bg-muted/35 p-2">
			<div className="truncate text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
				{label}
			</div>
			<div className="mt-1 truncate font-mono text-sm font-semibold tracking-[-0.01em] text-foreground">
				{value}
			</div>
		</div>
	);
}

// =========================================================================
// Views-by-source strip (Threads Band 2 right, col-9-12 rows 4-6)
// =========================================================================
function formatThreadTotal(value: number): string {
	if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
	if (value >= 10_000) return `${Math.round(value / 1000)}K`;
	if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
	return value.toLocaleString();
}

export function ViewsBySourceStripTile({
	scopedAccount,
	accountIds,
}: DashboardScopeProps) {
	const threadScopedIds = useMemo(
		() =>
			scopedAccount
				? scopedAccount.platform === "threads"
					? [scopedAccount.id]
					: []
				: accountIds,
		[accountIds, scopedAccount],
	);
	const { data, isLoading } = useViewsBySource({
		days: 30,
		accountId: scopedAccount?.platform === "threads" ? scopedAccount.id : null,
		accountIds: threadScopedIds,
	});
	const postTotals = useThreadsPostTotals(30, threadScopedIds);
	const fallback = postTotals.data ?? EMPTY_THREAD_TOTALS;
	const sourceTotal = data?.totals
		? Object.values(data.totals).reduce(
				(sum, value) => sum + (Number(value) || 0),
				0,
			)
		: 0;
	const hasSourceData = !isLoading && sourceTotal > 0;
	const showPostTotals = !hasSourceData && fallback.posts > 0;

	// Each source uses its own y-axis so quieter sources are still legible.
	const paths = useMemo(() => {
		if (!data?.series || data.series.length === 0) return null;
		const keys: Array<keyof (typeof data.series)[number]> = [
			"home",
			"profile",
			"search",
			"activity",
			"ig",
		];
		const width = 280;
		const height = 18;
		const step = data.series.length > 1 ? width / (data.series.length - 1) : 0;

		const colorFor = (k: string): string =>
			(
				({
					home: "var(--color-oxblood)",
					profile: "var(--color-gold)",
					search: "var(--color-negative)",
					activity: "var(--color-vale)",
					ig: "var(--color-meridian)",
				}) as Record<string, string>
			)[k] ?? "var(--color-muted-foreground)";

		return keys.map((k) => {
			const seriesMax = Math.max(
				1,
				...data.series.map((p) => (p[k] as number) || 0),
			);
			const d = data.series
				.map((p, i) => {
					const v = ((p[k] as number) || 0) / seriesMax;
					const x = i * step;
					const y = height - v * (height - 4) - 2;
					return i === 0 ? `M${x},${y}` : `L${x},${y}`;
				})
				.join(" ");
			return { key: k as string, d, color: colorFor(k as string) };
		});
	}, [data]);

	return (
		<NovaCard
			eyebrow={showPostTotals ? "Thread post totals · 30d" : "Views by source · 30d"}
			title={showPostTotals ? "Thread reach mix" : "Source distribution"}
			description={
				showPostTotals
					? "Exact post totals while source buckets finish syncing."
					: "Home, profile, search, activity, and Instagram referral paths."
			}
			action={
				<Badge tone={showPostTotals ? "outline" : "oxblood"}>
					{showPostTotals ? (isLoading ? "Checking" : "Totals") : "Threads"}
				</Badge>
			}
			contentClassName="flex min-h-[220px] flex-col"
		>
				{showPostTotals ? (
					<>
						<div className="grid items-end gap-3 sm:grid-cols-[1.2fr_repeat(3,minmax(0,1fr))]">
							<div>
								<div className="font-mono text-4xl font-semibold tracking-[-0.04em] text-foreground">
									{formatThreadTotal(fallback.views)}
								</div>
								<div className="mt-1 text-sm text-muted-foreground">
									views from {fallback.posts.toLocaleString()} published Threads
								</div>
							</div>
							<WinnerStat
								label="Replies"
								value={formatThreadTotal(fallback.replies)}
							/>
							<WinnerStat
								label="Likes"
								value={formatThreadTotal(fallback.likes)}
							/>
							<WinnerStat
								label="Quotes"
								value={formatThreadTotal(fallback.quotes + fallback.reposts)}
							/>
						</div>
						<div className="mt-auto grid gap-2 pt-5">
							{[
								["Views", fallback.views, "var(--color-oxblood)"],
								["Replies", fallback.replies, "var(--color-meridian)"],
								["Likes", fallback.likes, "var(--color-gold)"],
							].map(([label, rawValue, color]) => {
								const value = Number(rawValue);
								const max = Math.max(
									fallback.views,
									fallback.replies,
									fallback.likes,
									1,
								);
								return (
									<div
										key={label as string}
										className="flex items-center gap-3"
									>
										<span className="w-14 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
											{label}
										</span>
										<div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
											<div
												aria-hidden="true"
												style={{
													height: "100%",
													width: `${Math.max(2, (value / max) * 100)}%`,
													background: color as string,
												}}
												className="rounded-full"
											/>
										</div>
										<span className="w-12 text-right font-mono text-xs font-semibold text-foreground">
											{formatThreadTotal(value)}
										</span>
									</div>
								);
							})}
						</div>
						<div className="mt-3 text-xs leading-relaxed text-muted-foreground">
							Source buckets are not available yet; these are exact totals from
							published Threads posts.
						</div>
					</>
				) : (
					<>
						<div className="flex min-h-0 flex-1 flex-col justify-center">
							{isLoading || !paths ? (
								<NovaEmpty
									title={isLoading || postTotals.isPending ? "Checking source buckets" : "No source data yet"}
									description={
										isLoading || postTotals.isPending
											? "Reading Threads source buckets."
											: "Source distribution appears once the API sync returns bucketed views."
									}
								>
									<div className="grid w-full max-w-sm gap-2">
										{["home", "profile", "search"].map((key, i) => (
											<div key={key} className="flex items-center gap-2">
												<span
													className="size-2 rounded-full"
													style={{
														background: [
															"var(--color-oxblood)",
															"var(--color-gold)",
															"var(--color-vale)",
														][i],
														opacity: 0.48,
													}}
												/>
												<Skeleton className="h-2 flex-1" />
												<Skeleton className="h-2 w-8" />
											</div>
										))}
									</div>
								</NovaEmpty>
							) : (
								<div style={{ display: "grid", gap: 3 }}>
									{paths.map((p) => (
										<svg
											key={p.key}
											viewBox="0 0 280 18"
											preserveAspectRatio="none"
											style={{ width: "100%", height: 18 }}
											aria-hidden="true"
											role="presentation"
										>
											<path
												d={p.d}
												fill="none"
												stroke={p.color}
												strokeWidth={1.4}
											/>
										</svg>
									))}
								</div>
							)}
						</div>
						<div className="mt-3 flex flex-wrap items-center gap-3">
							{[
								["home", "Home"],
								["profile", "Profile"],
								["search", "Search"],
								["activity", "Activity"],
								["ig", "IG"],
							].map(([k, l]) => {
								const c = (
									{
										home: "var(--color-oxblood)",
										profile: "var(--color-gold)",
										search: "var(--color-negative)",
										activity: "var(--color-vale)",
										ig: "var(--color-meridian)",
									} as Record<string, string>
								)[k!];
								const pct = data?.totals
									? Math.round(
											(((data.totals[k as "home"] ?? 0) as number) /
												Math.max(
													1,
													Object.values(data.totals).reduce(
														(s, v) => s + (v as number),
														0,
													),
												)) *
												100,
										)
									: 0;
								return (
									<div key={k} className="flex items-center gap-1.5">
										<span
											style={{
												width: 8,
												height: 2,
												background: c,
												borderRadius: 1,
											}}
										/>
										<span className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
											{l} · {pct}%
										</span>
									</div>
								);
							})}
						</div>
					</>
				)}
		</NovaCard>
	);
}

// =========================================================================
// Conversation winner (Threads Band 3, col-1-5 rows 7-9)
// =========================================================================
export function ConversationWinnerTile({
	scopedAccount,
	accountIds,
	groupId,
}: DashboardScopeProps) {
	const threadScopedIds = useMemo(
		() =>
			scopedAccount
				? scopedAccount.platform === "threads"
					? [scopedAccount.id]
					: []
				: accountIds,
		[accountIds, scopedAccount],
	);
	const { leaders, isLoading } = useReplyDepthLeaders(
		30,
		scopedAccount,
		accountIds,
		groupId,
	);
	const qr = useQuoteReplyRatio(
		30,
		scopedAccount?.platform === "threads" ? scopedAccount.id : null,
		threadScopedIds,
	);
	const top = leaders[0] ?? null;
	const runners = leaders.slice(1, 4);

	// Velocity histogram now arrives server-side from the
	// /api/analytics?action=reply-depth-leaders endpoint, computed from
	// posts.reply_chain (cron-populated). 10 buckets, each spanning
	// top.velocityWindowHours hours. Falls back to an empty-state
	// skeleton when the cron hasn't synced this post's chain yet.
	const histogram = top?.velocityHistogram ?? null;
	const windowHours = top?.velocityWindowHours ?? null;
	const peakIdx = useMemo(() => {
		if (!histogram || histogram.length === 0) return -1;
		let max = 0;
		let idx = -1;
		for (let i = 0; i < histogram.length; i++) {
			if (histogram[i]! > max) {
				max = histogram[i]!;
				idx = i;
			}
		}
		return max > 0 ? idx : -1;
	}, [histogram]);

	return (
		<NovaCard
			eyebrow="30-day deepest thread"
			title="Conversation winner"
			description="The thread creating the deepest reply chain in the current scope."
			action={
				qr.fleetRatio != null ? (
					<Badge tone="oxblood">Quote/reply {qr.fleetRatio.toFixed(1)}x</Badge>
				) : null
			}
			contentClassName="flex min-h-[280px] flex-col"
		>
			{top ? (
				<>
					<div className="mb-3 line-clamp-3 text-base font-semibold leading-snug tracking-[-0.015em] text-foreground">
						{top.content?.trim() || "— no caption recorded"}
					</div>
					<div className="mb-4 grid grid-cols-2 gap-2 border-t border-border pt-3 sm:grid-cols-4">
						<WinnerStat label="Replies" value={top.replies.toLocaleString()} />
						<WinnerStat label="Depth" value={`D${top.replyDepth}`} />
						<WinnerStat label="Reposts" value={top.reposts.toLocaleString()} />
						<WinnerStat label="Quotes" value={top.quotes.toLocaleString()} />
					</div>
					<div className="mb-3">
						<div className="mb-2 text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
							{histogram
								? `Reply velocity · ${windowHours && windowHours >= 10 ? Math.round(windowHours) : (windowHours ?? 1).toFixed(1)}h windows`
								: "Reply velocity"}
						</div>
						<div className="relative flex h-8 items-end gap-1 opacity-90">
							{(histogram ?? Array.from({ length: 10 }, (_, i) => i + 1)).map(
								(count, i) => {
									const max = histogram ? Math.max(...histogram, 1) : 10;
									const heightPct = histogram
										? count > 0
											? Math.max(8, (count / max) * 100)
											: 8
										: 18 + (i % 4) * 12;
									const isPeak = histogram ? i === peakIdx : false;
									return (
										<div
											key={i}
											style={{
												flex: 1,
												height: `${heightPct}%`,
												background: isPeak
													? "var(--color-oxblood)"
													: "var(--color-muted-foreground)",
												opacity: histogram ? (count > 0 ? 1 : 0.25) : 0.3,
											}}
											className="rounded-sm"
										/>
									);
								},
							)}
						</div>
						<div className="relative mt-1 font-mono text-[10px] font-medium text-muted-foreground">
							<span>oldest</span>
							{histogram ? (
								<span
									style={{
										left:
											peakIdx >= 0 && histogram.length > 1
												? `${(peakIdx / (histogram.length - 1)) * 100}%`
												: "50%",
										transform: "translateX(-50%)",
									}}
									className="absolute font-semibold text-foreground"
								>
									peak
								</span>
							) : null}
							<span className="float-right">now</span>
						</div>
					</div>
				</>
			) : (
				<div className="mb-4">
					<Skeleton className="mb-2 h-4 w-[90%]" />
					<Skeleton className="mb-2 h-4 w-[70%]" />
					<Skeleton className="mt-3 h-3 w-1/2 opacity-70" />
					<div className="mt-4 text-sm leading-relaxed text-muted-foreground">
						{isLoading ? (
							"Reading reply depth, quotes, and reposts for the deepest thread."
						) : (
							<>
								<strong className="font-semibold text-foreground">
									No qualifying threads in window.
								</strong>{" "}
								Today's deepest reply chain appears here once a thread crosses
								depth 2+.
							</>
						)}
					</div>
				</div>
			)}

			<div className="flex min-h-0 flex-1 flex-col gap-2">
				{runners.map((r, i) => (
					<div
						key={r.id}
						className="flex items-baseline gap-3 border-t border-border pt-2"
					>
						<span className="w-4 font-mono text-xs font-semibold text-muted-foreground">
							{i + 2}
						</span>
						<div className="min-w-0 flex-1">
							<div className="truncate text-sm text-foreground">
								{r.content?.trim() || "— no caption"}
							</div>
							<div className="mt-1 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
								{r.replies} replies · depth {r.replyDepth}
							</div>
						</div>
					</div>
				))}
			</div>

			{top?.permalink ? (
				<Button asChild variant="outline" size="sm" className="mt-3 w-full">
					<a href={top.permalink} target="_blank" rel="noopener noreferrer">
						Open winning thread
					</a>
				</Button>
			) : null}
		</NovaCard>
	);
}

// =========================================================================
// Held replies queue (Threads Band 3, col-5-8 rows 7-9)
// =========================================================================
export function HeldRepliesQueueTile({
	scopedAccount,
	accountIds,
	groupId,
}: DashboardScopeProps) {
	const storeScopedAccount = useAccountScopeStore((s) => s.scopedAccount);
	const selectedGroupId = useWorkspaceStore((s) => s.selectedGroupId);
	const effectiveScopedAccount = scopedAccount ?? storeScopedAccount;
	const effectiveGroupId = groupId ?? selectedGroupId;
	const threadAccountId =
		effectiveScopedAccount?.platform === "threads"
			? effectiveScopedAccount.id
			: null;
	const queue = usePendingRepliesQueue(threadAccountId);
	const accountIdSet = useMemo(() => new Set(accountIds ?? []), [accountIds]);
	const visibleAccounts = useMemo(() => {
		if (threadAccountId) return queue.accounts;
		if (accountIdSet.size === 0) return queue.accounts;
		return queue.accounts.filter((account) => accountIdSet.has(account.accountId));
	}, [accountIdSet, queue.accounts, threadAccountId]);
	const scopedTotal = visibleAccounts.reduce(
		(sum, account) => sum + account.total,
		0,
	);
	const top = visibleAccounts.slice(0, 4);

	return (
		<NovaCard
			eyebrow="Held replies · fleet"
			title="Reply queue"
			description="Moderated replies waiting for review across Threads accounts."
			action={
				<Badge tone={queue.hasError ? "danger" : scopedTotal > 0 ? "oxblood" : "secondary"}>
					{queue.isLoading ? "Sync" : queue.hasError ? "Retry" : scopedTotal}
				</Badge>
			}
			contentClassName="flex min-h-[240px] flex-col"
		>
			{scopedTotal > 0 && !queue.hasError ? (
				<Button asChild size="sm" className="mb-3 self-end">
					<Link
						to={scopedRoute("/inbox", {
							scopedAccount: effectiveScopedAccount,
							accountIds,
							groupId: effectiveGroupId,
							platform: "threads",
						})}
					>
						Review replies
					</Link>
				</Button>
			) : null}

			<div className="flex min-h-0 flex-1 flex-col gap-2">
				{queue.isLoading && top.length === 0 ? (
					Array.from({ length: 3 }).map((_, i) => (
						<div
							key={i}
							className="flex items-center gap-2 rounded-lg border border-border bg-muted/35 p-2"
						>
							<Skeleton className="size-6 rounded-full" />
							<div className="flex-1">
								<Skeleton className="h-2" style={{ width: `${58 - i * 9}%` }} />
								<Skeleton className="mt-2 h-2 opacity-70" style={{ width: `${42 - i * 5}%` }} />
							</div>
						</div>
					))
				) : queue.hasError && top.length === 0 ? (
					<NovaEmpty
						title="Held replies unavailable"
						description="Try syncing again in a moment."
					/>
				) : top.length === 0 ? (
					<NovaEmpty
						title="Auto-poster running clean"
						description="Replies caught by moderation rules will queue here for inline approve or deny."
					/>
				) : (
					top.map((acct) => {
						const handle = acct.username ? `@${acct.username}` : "Unnamed account";
						return (
							<Link
								key={acct.accountId}
								to={accountDetailPath(acct.accountId)}
								className="flex min-w-0 items-start gap-2 rounded-lg border border-border bg-muted/35 p-2 text-foreground no-underline transition-colors hover:bg-muted"
								title="Open account details"
							>
								<Avatar seed={handle} size="sm" />
								<div className="min-w-0 flex-1">
									<div className="flex min-w-0 items-baseline gap-2">
										<span className="min-w-0 flex-1 truncate text-sm font-medium">
											{handle}
										</span>
										<span className="shrink-0 font-mono text-xs font-semibold text-primary">
											{acct.total}
										</span>
									</div>
									<div className="mt-1 truncate text-xs text-muted-foreground">
										{acct.pending} pending · {acct.needsReview} need review
										{acct.topReason ? ` · ${acct.topReason}` : ""}
									</div>
								</div>
							</Link>
						);
					})
				)}
			</div>
		</NovaCard>
	);
}

// =========================================================================
// Reach anomalies — dark card, Threads Band 3 right (span-4).
//
// Per-account reach anomaly monitor: backend compares posts from the last
// 3 days against the 4-14 day baseline, using first-24h snapshots when
// post_metric_history has enough coverage.
//
// IG variant intentionally returns null: reach-drop semantics differ on IG
// (Reels vs feed vs story) and a fleet-aggregate single number masks more
// than it reveals. Build a separate IG-specific tile when that's wanted.
// =========================================================================
export function SuppressionDarkTile({
	variant,
	scopedAccount,
	accountIds,
}: DashboardScopeProps & {
	variant: "threads" | "ig";
}) {
	if (variant === "ig") {
		return null;
	}
	return (
		<ThreadsSuppressionDarkTile
			scopedAccount={scopedAccount}
			accountIds={accountIds}
		/>
	);
}

function ThreadsSuppressionDarkTile({
	scopedAccount,
	accountIds,
}: DashboardScopeProps) {
	const anomalies = useReachAnomalies();
	const scopedIds = useMemo(() => new Set(accountIds ?? []), [accountIds]);

	const drops = useMemo(() => {
		return anomalies.accounts.filter((account) => {
			if (scopedAccount) {
				if (scopedAccount.platform !== "threads") return false;
				if (account.accountId !== scopedAccount.id) return false;
			} else if (scopedIds.size > 0 && !scopedIds.has(account.accountId)) {
				return false;
			}
			return account.status === "anomaly" || account.status === "concerning";
		});
	}, [anomalies.accounts, scopedAccount, scopedIds]);

	const rows = drops.slice(0, 4);
	const totalDrops = drops.length;

	return (
		<NovaCard
			eyebrow={`Reach anomalies · ${anomalies.isLoading ? "syncing" : totalDrops}`}
			title="Suppression watch"
			description="Recent post reach compared with each account's 4-14 day baseline."
			action={<Badge tone={totalDrops > 0 ? "danger" : "secondary"}>Recent vs base</Badge>}
			contentClassName="flex min-h-[240px] flex-col"
		>
			<div className="flex min-h-0 flex-1 flex-col gap-3">
				{anomalies.isLoading && rows.length === 0 ? (
					Array.from({ length: 3 }).map((_, i) => (
						<div key={i} className="flex items-center gap-3">
							<Skeleton className="size-3 rounded-full" />
							<Skeleton className="size-6 rounded-full" />
							<div className="flex-1">
								<Skeleton className="h-2" style={{ width: `${62 - i * 8}%` }} />
								<Skeleton className="mt-2 h-2 opacity-70" style={{ width: `${40 - i * 5}%` }} />
							</div>
							<Skeleton className="h-3 w-9" />
						</div>
					))
				) : rows.length === 0 ? (
					<NovaEmpty
						title="Fleet stable"
						description="No accounts with concerning reach drops vs their 4-14 day baseline."
					/>
				) : (
					rows.map((acct) => {
						const handle = acct.username ? `@${acct.username}` : "Unnamed account";
						const dropPct = acct.reachChangePercent ?? 0;
						const signedDrop = `${dropPct > 0 ? "+" : "-"}${Math.abs(Math.round(dropPct))}%`;
						const state: "crit" | "warn" =
							acct.status === "anomaly" ? "crit" : "warn";
						return (
							<Link
								key={acct.accountId}
								to={accountDetailPath(acct.accountId)}
								className="flex items-center gap-3 rounded-lg border border-border bg-muted/35 p-2 text-foreground no-underline transition-colors hover:bg-muted"
								title="Open account details"
							>
								<TrafficDot state={state} />
								<Avatar seed={handle} size="sm" />
								<div className="min-w-0 flex-1">
									<div className="truncate text-sm font-medium">{handle}</div>
									<div className="mt-1 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
										reach {signedDrop} · {acct.recentPostCount} recent /{" "}
										{acct.baselinePostCount} base
									</div>
								</div>
							</Link>
						);
					})
				)}
			</div>
		</NovaCard>
	);
}
