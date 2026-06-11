// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useContentMixHealth } from "@/hooks/useContentMixHealth";
import { useFleetMetrics } from "@/hooks/useFleetMetrics";
import { useReelWatchTimeLeaders } from "@/hooks/useReelWatchTimeLeaders";
import { useSaveRateLeaders } from "@/hooks/useSaveRateLeaders";
import { useSendsPerReachLeaders } from "@/hooks/useSendsPerReachLeaders";
import { useVanityAccounts } from "@/hooks/useVanityAccounts";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { calendarPostPath } from "@/lib/deepLinks";
import { scopedRoute } from "@/lib/scopedRoutes";
import { Avatar } from "../atoms/Avatar";
import { BulletChart } from "../atoms/BulletChart";
import type { DashboardScopeProps } from "../scope";
import { formatCompact } from "../shared";

type TimedDashboardScopeProps = DashboardScopeProps & { periodDays?: number };

function formatReach(n: number): string {
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
	return String(n);
}

function percentile(values: number[], p: number): number | null {
	const sorted = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
	if (sorted.length === 0) return null;
	const idx = Math.min(
		sorted.length - 1,
		Math.max(0, Math.round((p / 100) * (sorted.length - 1))),
	);
	return sorted[idx]!;
}

function formatPctValue(value: number | null, digits = 1): string {
	return value == null ? "0.0%" : `${(value * 100).toFixed(digits)}%`;
}

function ternaryPoint(reelsPct: number, feedPct: number, storyPct: number) {
	const total = Math.max(1, reelsPct + feedPct + storyPct);
	const r = reelsPct / total;
	const f = feedPct / total;
	const s = storyPct / total;
	return {
		x: r * 100 + f * 10 + s * 190,
		y: r * 8 + f * 168 + s * 168,
	};
}

function scopedInstagramAccountId(
	scopedAccount?: DashboardScopeProps["scopedAccount"],
): string | null {
	return scopedAccount?.platform === "instagram" ? scopedAccount.id : null;
}

function normalizedLeaderboardDays(days: number): 7 | 30 | 90 {
	if (days <= 7) return 7;
	if (days >= 90) return 90;
	return 30;
}

// =========================================================================
// Sends-per-reach bullet (dark hero right) — col-9-12 row-1-3
// Spec §6 Widget #4 (P0, Mosseri #1 signal)
// =========================================================================
export function SendsPerReachBulletDarkTile({
	periodDays = 30,
	scopedAccount,
	accountIds,
	groupId,
}: TimedDashboardScopeProps) {
	const metrics = useFleetMetrics(periodDays, "instagram", scopedAccount, {
		accountIds,
		groupId,
	});
	const samples = useSendsPerReachLeaders(
		periodDays,
		scopedInstagramAccountId(scopedAccount),
		100,
		scopedAccount ? undefined : accountIds,
	);
	const totalSends = metrics.accounts.reduce((s, a) => s + a.sends, 0);
	const sampleSends = samples.leaders.reduce((s, a) => s + a.shares, 0);
	const sampleReach = samples.leaders.reduce((s, a) => s + a.reach, 0);
	const hasFleetData = metrics.postCount > 0 && metrics.totalReach > 0;
	const hasSampleData = sampleReach > 0 && sampleSends > 0;
	const pct = hasFleetData
		? (totalSends / metrics.totalReach) * 100
		: hasSampleData
			? (sampleSends / sampleReach) * 100
			: 0;
	const hasData = hasFleetData || hasSampleData;
	const barPct = Math.min(100, pct);
	const fleetP50 = percentile(
		samples.leaders.map((post) => post.sendsPerReach * 100),
		50,
	);
	const pctLabel = pct > 0 && pct < 1 ? pct.toFixed(2) : pct.toFixed(1);
	const topContributors = samples.leaders.slice(0, 3);
	const scopeLabel = hasFleetData
		? scopedAccount
			? `selected account · ${periodDays}d`
			: accountIds && accountIds.length > 0
				? `selected scope · ${periodDays}d`
				: `workspace · ${periodDays}d`
		: hasSampleData
			? `${samples.leaders.length} synced posts`
			: "no reach-backed posts";
	return (
		<NovaCard
			eyebrow={`Share rate · ${periodDays}d`}
			title="DM share signal"
			description="Sends per reach across Instagram posts in the current scope."
			action={<Badge tone="oxblood">Mosseri #1</Badge>}
			contentClassName="flex min-h-[280px] flex-col"
		>
			<div className="mt-auto flex items-end gap-3">
				<div className="font-mono text-5xl font-semibold tracking-[-0.05em] text-foreground">
					{hasData ? pctLabel : "0"}
					{hasData ? (
						<span className="text-2xl text-muted-foreground">%</span>
					) : null}
				</div>
				<div className="mb-2 text-xs text-muted-foreground">{scopeLabel}</div>
			</div>

			{hasData ? (
				<>
					<div className="mt-3">
						<BulletChart
							value={barPct}
							target={fleetP50 ?? undefined}
							fullWidth
							highlightTop={pct > 10}
						/>
					</div>
					<div className="mt-1 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
						DM shares per reach · Instagram priority signal
					</div>
					{topContributors.length > 0 ? (
						<div className="mt-3 flex flex-col gap-2">
							<div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
								Top contributors · {periodDays}d
							</div>
							{topContributors.map((post) => {
								const title = post.content?.trim() || "Untitled IG post";
								return (
									<div
										key={post.id}
										className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-lg border border-border bg-muted/35 px-2 py-1.5"
									>
										<span className="min-w-0 truncate text-sm font-semibold text-foreground">
											{title}
										</span>
										<div className="text-right">
											<div className="font-mono text-xs font-bold text-primary">
												{(post.sendsPerReach * 100).toFixed(
													post.sendsPerReach > 0 && post.sendsPerReach < 0.01
														? 2
														: 1,
												)}
												%
											</div>
											<div className="text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
												{formatCompact(post.reach)} reach ·{" "}
												{formatCompact(post.shares)} send
											</div>
										</div>
									</div>
								);
							})}
						</div>
					) : null}
				</>
			) : (
				<NovaEmpty
					className="mt-3"
					title="DM shares need synced reach"
					description="Shows once IG posts have synced reach and share counts."
				>
					<Skeleton className="h-3 w-full" />
				</NovaEmpty>
			)}
		</NovaCard>
	);
}

// =========================================================================
// Reel watch-time leaders (compact) — col-9-10 row-3
// Spec §6 Widget #14 (P0) — ranked by ig_reels_avg_watch_time.
// Shows top 2 Reels in a tight 2×1 slot — ranking signal in glance form.
// =========================================================================
export function WatchPerViewTile({
	periodDays = 30,
	scopedAccount,
	accountIds,
	groupId,
}: TimedDashboardScopeProps) {
	const { leaders, isLoading, hasError } = useReelWatchTimeLeaders(
		periodDays,
		scopedAccount,
		accountIds,
		groupId,
	);
	const top = useMemo(() => leaders.slice(0, 4), [leaders]);
	const fleetAvg = useMemo(() => {
		if (leaders.length === 0) return null;
		const sum = leaders.reduce((s, l) => s + l.avgWatchSec, 0);
		return sum / leaders.length;
	}, [leaders]);
	const avgLabel = scopedAccount
		? "account avg"
		: accountIds && accountIds.length > 0
			? "scope avg"
			: "network avg";
	const maxWatch = Math.max(...leaders.map((x) => x.avgWatchSec), 1);

	return (
		<NovaCard
			eyebrow={`Watch per view · ${periodDays}d`}
			title="Reel watch time"
			description="Average watch time from synced Reel insights."
			action={<Badge tone="outline">Reels · IG</Badge>}
			contentClassName="flex min-h-[250px] flex-col"
		>
			{top.length > 0 ? (
				<>
					<div className="flex items-baseline gap-2">
						<div className="font-mono text-4xl font-semibold tracking-[-0.04em] text-foreground">
							{fleetAvg != null ? `${fleetAvg.toFixed(1)}s` : "0.0s"}
						</div>
						<span className="text-xs text-muted-foreground">{avgLabel}</span>
					</div>
					<div className="mt-1 text-xs text-muted-foreground">
						Average watch time from synced Reel insights.
					</div>

					<div className="mt-auto flex flex-col gap-2 pt-4">
						{top.map((r, i) => (
							<Link
								key={r.id}
								to={calendarPostPath(r.id, r.publishedAt)}
								className="flex min-w-0 items-center gap-2 rounded-lg border border-border bg-muted/35 p-2 text-foreground no-underline transition-colors hover:bg-muted"
								title="Open Reel in calendar"
							>
								<span className="w-4 shrink-0 font-mono text-xs font-bold text-muted-foreground data-[leader=true]:text-primary" data-leader={i === 0}>
									{i + 1}
								</span>
								<span className="min-w-0 flex-1 truncate text-sm font-medium">
									@{r.username ?? "unknown"}
								</span>
								<div className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-muted">
									<div
										className="h-full rounded-full bg-primary"
										style={{
											width: `${Math.min(100, (r.avgWatchSec / maxWatch) * 100)}%`,
											opacity: i === 0 ? 1 : 0.6,
										}}
									/>
								</div>
								<span className="w-10 shrink-0 text-right font-mono text-xs font-semibold text-foreground data-[leader=true]:text-primary" data-leader={i === 0}>
									{r.avgWatchSec.toFixed(1)}s
								</span>
							</Link>
						))}
					</div>
				</>
			) : isLoading ? (
				<div className="mt-2 grid gap-3">
					<Skeleton className="h-8 w-24" />
					<Skeleton className="h-2 w-3/4" />
					<Skeleton className="h-2 w-1/2" />
					<Skeleton className="mt-3 h-1.5 w-full" />
				</div>
			) : (
				<NovaEmpty
					className="mt-2"
					title={hasError ? "Reel watch-time unavailable" : "No reels in window"}
					description={
						hasError
							? "Try syncing again in a moment."
							: "Top reels by average watch time appear here after Reel insights sync."
					}
				/>
			)}
		</NovaCard>
	);
}

// =========================================================================
// Share-rate leaders — col-1-7 row-4-7
// Spec §6 Widget #4 (P0) — "lead the IG view with it"
// =========================================================================
export function SendsPerReachLeadersTile({
	periodDays = 30,
	scopedAccount,
	accountIds,
}: TimedDashboardScopeProps) {
	const { leaders, isLoading } = useSendsPerReachLeaders(
		periodDays,
		scopedInstagramAccountId(scopedAccount),
		100,
		scopedAccount ? undefined : accountIds,
	);
	const top = useMemo(() => leaders.slice(0, 4), [leaders]);
	const bottom = useMemo(() => {
		if (leaders.length < 2) return null;
		const sorted = [...leaders].sort(
			(a, b) => a.sendsPerReach - b.sendsPerReach,
		);
		return sorted[0] ?? null;
	}, [leaders]);
	const thinSample = !isLoading && top.length > 0 && top.length < 3;
	const title = leaders.length > 1
		? scopedAccount
			? "Top + bottom posts"
			: accountIds && accountIds.length > 0
				? "Top 4 + bottom in scope"
				: "Top 4 + bottom of workspace"
		: "Top synced sample";

	return (
		<NovaCard
			eyebrow={`Share-rate leaders · ${periodDays}d`}
			title={title}
			description="Posts ranked by Instagram sends per reach."
			action={<Badge tone={thinSample ? "outline" : "oxblood"}>{thinSample ? "Thin sample" : "Mosseri #1"}</Badge>}
			contentClassName="flex min-h-[320px] flex-col"
		>
			<div className="flex min-h-0 flex-1 flex-col gap-2">
				{top.length === 0 ? (
					isLoading ? (
						Array.from({ length: 4 }).map((_, i) => (
							<div
								key={i}
								className="flex items-center gap-3 rounded-lg border border-border bg-muted/35 p-2"
							>
								<span className="w-4 font-mono text-xs font-semibold text-primary">
									{i + 1}
								</span>
								<Skeleton className="size-6 rounded-full" />
								<div className="min-w-0 flex-1">
									<Skeleton className="h-2.5" style={{ width: `${58 - i * 7}%` }} />
									<Skeleton className="mt-2 h-2 opacity-70" style={{ width: `${36 - i * 4}%` }} />
								</div>
								<Skeleton className="h-3 w-11" />
							</div>
						))
					) : (
						<NovaEmpty
							title="No reach-backed send samples"
							description="Synced Reels with share counts will rank here once the next analytics pass has enough reach."
						/>
					)
				) : (
					top.map((r, i) => (
						<Link
							key={r.id}
							to={calendarPostPath(r.id, r.publishedAt)}
							className="flex min-w-0 items-center gap-3 rounded-lg border border-border bg-muted/35 p-2 text-foreground no-underline transition-colors hover:bg-muted"
							title="Open post in calendar"
						>
							<span className="w-4 shrink-0 font-mono text-xs font-semibold text-primary">
								{i + 1}
							</span>
							<Avatar seed={r.instagramAccountId ?? r.id} size="sm" />
							<div className="min-w-0 flex-1">
								<div className="truncate text-sm font-medium">
									{r.content?.slice(0, 50) ?? "No caption recorded"}
								</div>
								<div className="mt-1 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
									{formatCompact(r.reach)} reach · {formatCompact(r.shares)} shares
								</div>
							</div>
							<span className="shrink-0 font-mono text-sm font-semibold text-primary">
								{(r.sendsPerReach * 100).toFixed(1)}%
							</span>
						</Link>
					))
				)}

				{bottom ? (
					<>
						<div className="mt-2 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
							Lowest sample
						</div>
						<Link
							to={calendarPostPath(bottom.id, bottom.publishedAt)}
							className="flex min-w-0 items-center gap-3 rounded-lg border border-border bg-muted/35 p-2 text-foreground no-underline transition-colors hover:bg-muted"
							title="Open lowest sample in calendar"
						>
							<span className="w-4 shrink-0 font-mono text-xs font-semibold text-destructive">
								W
							</span>
							<Avatar seed={bottom.instagramAccountId ?? bottom.id} size="sm" />
							<div className="min-w-0 flex-1">
								<div className="truncate text-sm font-medium">
									{bottom.content?.slice(0, 50) ?? "No caption recorded"}
								</div>
								<div className="mt-1 text-[11px] font-medium uppercase tracking-[0.12em] text-destructive">
									{formatCompact(bottom.reach)} reach · lowest send rate
								</div>
							</div>
							<span className="shrink-0 font-mono text-sm font-semibold text-destructive">
								{(bottom.sendsPerReach * 100).toFixed(1)}%
							</span>
						</Link>
					</>
				) : null}
			</div>
			{thinSample ? (
				<div className="mt-3 text-xs leading-relaxed text-muted-foreground">
					Needs 3+ reach-backed IG posts for a full leaderboard. Current row is still live-backed, but intentionally compact.
				</div>
			) : null}
		</NovaCard>
	);
}

// =========================================================================
// Quality signal bullets — research-validated replacement for standalone
// save-rate percentage. Uses real post samples from the existing save-rate
// and sends-per-reach endpoints; bands are portfolio p25/p50/p75, not a
// fabricated cohort.
// =========================================================================
export function QualitySignalBulletsTile({
	periodDays = 30,
	scopedAccount,
	accountIds,
}: TimedDashboardScopeProps) {
	const saves = useSaveRateLeaders(
		periodDays,
		scopedInstagramAccountId(scopedAccount),
		100,
		scopedAccount ? undefined : accountIds,
	);
	const sends = useSendsPerReachLeaders(
		periodDays,
		scopedInstagramAccountId(scopedAccount),
		100,
		scopedAccount ? undefined : accountIds,
	);

	const saveRates = saves.leaders.map((r) => r.saveRate);
	const sendRates = sends.leaders.map((r) => r.sendsPerReach);
	const saveP25 = percentile(saveRates, 25);
	const saveP50 = percentile(saveRates, 50);
	const saveP75 = percentile(saveRates, 75);
	const sendP25 = percentile(sendRates, 25);
	const sendP50 = percentile(sendRates, 50);
	const sendP75 = percentile(sendRates, 75);
	const saveCurrent = percentile(saveRates, 75);
	const sendCurrent = percentile(sendRates, 75);
	const hasData = saveRates.length > 0 || sendRates.length > 0;
	const isLoading = saves.isLoading || sends.isLoading;
	const sampleCount = saveRates.length + sendRates.length;

	return (
		<NovaCard
			title="Quality signals"
			description="Portfolio bands from saved and shared Instagram posts."
			action={<Badge tone="outline">{periodDays}d</Badge>}
			contentClassName="flex h-full flex-col gap-4"
		>
			{hasData ? (
				<>
					<div className="grid grid-cols-2 gap-2">
						<SignalSummaryCard label="Saves · P75" value={saveCurrent} tone="save" />
						<SignalSummaryCard label="Sends · P75" value={sendCurrent} tone="send" />
					</div>
					<div className="flex flex-col gap-3">
						<QualityBulletRow
							label="Saves"
							value={saveCurrent}
							p25={saveP25}
							p50={saveP50}
							p75={saveP75}
							tone="save"
						/>
						<QualityBulletRow
							label="Sends"
							value={sendCurrent}
							p25={sendP25}
							p50={sendP50}
							p75={sendP75}
							tone="send"
						/>
					</div>
					<p className="mt-auto text-xs leading-relaxed text-muted-foreground">
						Live portfolio P75 from {sampleCount} synced IG samples. Saves and sends bullets show P75 vs P25/P50/P75 markers.
					</p>
				</>
			) : isLoading ? (
				<div className="flex flex-col gap-4" role="status" aria-label="Loading quality signals">
					<QualityBulletSkeleton />
					<QualityBulletSkeleton />
					<p className="mt-auto text-xs leading-relaxed text-muted-foreground">
						Building portfolio bands from saved and shared IG posts.
					</p>
				</div>
			) : (
				<NovaEmpty
					className="min-h-40"
					title="Quality-signal benchmarks need saved/shared IG posts."
					description="Once synced, this replaces one-off percentages with live portfolio bands."
				/>
			)}
		</NovaCard>
	);
}

function SignalSummaryCard({
	label,
	value,
	tone,
}: {
	label: string;
	value: number | null;
	tone: "save" | "send";
}) {
	const color = tone === "save" ? "var(--color-oxblood)" : "var(--color-chart-2)";
	return (
		<div className="min-w-0 rounded-lg border border-border bg-muted/35 px-3 py-2">
			<div className="truncate text-[0.68rem] font-medium uppercase tracking-[0.14em] text-muted-foreground">
				{label}
			</div>
			<div className="mt-1 font-mono text-xl font-semibold tabular-nums" style={{ color }}>
				{formatPctValue(value)}
			</div>
		</div>
	);
}

function QualityBulletRow({
	label,
	value,
	p25,
	p50,
	p75,
	tone,
}: {
	label: string;
	value: number | null;
	p25: number | null;
	p50: number | null;
	p75: number | null;
	tone: "save" | "send";
}) {
	const max = Math.max(value ?? 0, p75 ?? 0, p50 ?? 0, p25 ?? 0, 0.01);
	const valuePct = value == null ? 0 : Math.min(100, (value / max) * 100);
	const p25Pct = p25 == null ? 25 : Math.min(100, (p25 / max) * 100);
	const p50Pct = p50 == null ? 50 : Math.min(100, (p50 / max) * 100);
	const p75Pct = p75 == null ? 75 : Math.min(100, (p75 / max) * 100);
	const color = tone === "save" ? "var(--color-oxblood)" : "var(--color-chart-2)";
	return (
		<div className="flex flex-col gap-1.5">
			<div className="grid grid-cols-[3rem_minmax(0,1fr)_3.25rem] items-center gap-2.5">
				<span className="truncate text-[0.68rem] font-medium uppercase tracking-[0.12em] text-muted-foreground">
					{label}
				</span>
				<div>
					<BulletChart
						value={valuePct}
						target={p50Pct}
						fullWidth
						highlightTop
						bands={{ p25: p25Pct, p50: p50Pct, p75: p75Pct, max: 100 }}
						measureColor={color}
					/>
				</div>
				<span className="text-right font-mono text-xs font-semibold tabular-nums" style={{ color }}>
					{formatPctValue(value)}
				</span>
			</div>
			<div className="flex justify-between text-[0.64rem] font-medium uppercase tracking-[0.12em] text-muted-foreground">
				<span>p25 {formatPctValue(p25)}</span>
				<span>p50 {formatPctValue(p50)}</span>
				<span>p75 {formatPctValue(p75)}</span>
			</div>
		</div>
	);
}

function QualityBulletSkeleton() {
	return (
		<div className="flex flex-col gap-2">
			<Skeleton className="h-3 w-20 rounded-md" />
			<Skeleton className="h-5 w-full rounded-md" />
		</div>
	);
}

// =========================================================================
// Quality action gap — likes-heavy, quality-light IG accounts.
// =========================================================================
export function VanityFlagTile({
	periodDays = 30,
	scopedAccount,
	accountIds,
}: TimedDashboardScopeProps) {
	const { accounts, fleetAvgRatio, hasRealData, loading } = useVanityAccounts(
		normalizedLeaderboardDays(periodDays),
		scopedInstagramAccountId(scopedAccount),
		scopedAccount ? undefined : accountIds,
	);
	const top = accounts[0] ?? null;
	const quality = top ? top.sends + top.saves : 0;
	const ratio = top?.ratio ?? null;
	const hasFlag = hasRealData && top != null;
	const baselineLabel = scopedAccount
		? "account baseline"
		: accountIds && accountIds.length > 0
			? "scope baseline"
			: "network baseline";
	const flagTone =
		hasFlag && ratio != null && ratio > Math.max(20, fleetAvgRatio * 2)
			? "danger"
			: "outline";

	return (
		<NovaCard
			title="Quality action gap"
			description={`Likes-heavy accounts compared with ${baselineLabel}.`}
			action={
				hasFlag ? (
					<Badge tone={flagTone}>Likes-heavy</Badge>
				) : (
					<Badge tone="outline">IG</Badge>
				)
			}
			contentClassName="flex h-full flex-col gap-4"
		>
			{hasFlag && ratio != null ? (
				<>
					<div className="flex items-baseline gap-2">
						<span
							className="font-mono text-5xl font-semibold tabular-nums tracking-[-0.04em]"
							style={{
								color:
									ratio > Math.max(20, fleetAvgRatio * 2)
										? "var(--color-danger)"
										: "var(--color-foreground)",
							}}
						>
							{ratio.toFixed(1)}x
						</span>
						<span className="text-xs text-muted-foreground">likes / quality</span>
					</div>
					<p className="text-xs text-muted-foreground">
						{top.handle} · {baselineLabel} {fleetAvgRatio}:1
					</p>
					<div className="flex flex-col gap-2">
						<VanityBar label="Likes" value={top.likes} max={top.likes} tone="likes" />
						<VanityBar label="Sends" value={top.sends} max={top.likes} tone="sends" />
						<VanityBar label="Saves" value={top.saves} max={top.likes} tone="saves" />
					</div>
					<div className="flex justify-end text-[0.64rem] font-medium uppercase tracking-[0.12em] text-muted-foreground">
						= Likes · 100%
					</div>
					<p className="mt-auto text-xs leading-relaxed text-muted-foreground">
						Sends and saves shown as a fraction of likes. Axis: 100% = likes.{" "}
						{quality.toLocaleString()} sends+saves against{" "}
						{top.likes.toLocaleString()} likes.
					</p>
				</>
			) : loading ? (
				<div className="flex flex-col gap-3" role="status" aria-label="Loading quality action gap">
					<Skeleton className="h-10 w-28 rounded-lg" />
					<Skeleton className="h-3 w-40 rounded-md" />
					<Skeleton className="h-24 w-full rounded-lg" />
					<p className="mt-auto text-xs leading-relaxed text-muted-foreground">
						{scopedAccount
							? "Scanning this account for likes-heavy, sends/saves-light patterns."
							: "Scanning IG accounts for likes-heavy, sends/saves-light patterns."}
					</p>
				</div>
			) : (
				<NovaEmpty
					className="min-h-40"
					title="No quality gap flagged"
					description={
						scopedAccount
							? "This account has not crossed the likes-heavy, sends/saves-light threshold."
							: "No likes-heavy, sends/saves-light account crossed the live threshold."
					}
				/>
			)}
		</NovaCard>
	);
}

function VanityBar({
	label,
	value,
	max,
	tone,
}: {
	label: string;
	value: number;
	max: number;
	tone: "likes" | "sends" | "saves";
}) {
	const width =
		value > 0
			? Math.max(6, Math.min(100, (value / Math.max(1, max)) * 100))
			: 4;
	const color =
		tone === "likes"
			? "var(--color-danger)"
			: tone === "sends"
				? "var(--color-chart-2)"
				: "var(--color-oxblood)";
	return (
		<div className="grid grid-cols-[3rem_minmax(0,1fr)_3rem] items-center gap-2 text-xs">
			<span className="truncate font-medium uppercase tracking-[0.12em] text-muted-foreground">
				{label}
			</span>
			<div className="h-1.5 overflow-hidden rounded-full bg-muted">
				<div
					style={{
						height: "100%",
						width: `${width}%`,
						borderRadius: 999,
						background: color,
					}}
				/>
			</div>
			<span className="text-right font-mono text-xs font-semibold tabular-nums text-foreground">
				{formatCompact(value)}
			</span>
		</div>
	);
}

// =========================================================================
// Save-rate top/bottom — col-1-4 row-7-9
// Spec §6 Widget #6 (P0)
// =========================================================================
export function SaveRateTopBottomTile({
	periodDays = 30,
	scopedAccount,
	accountIds,
}: TimedDashboardScopeProps) {
	const { leaders, isLoading } = useSaveRateLeaders(
		periodDays,
		scopedInstagramAccountId(scopedAccount),
		100,
		scopedAccount ? undefined : accountIds,
	);
	const top = useMemo(() => leaders.slice(0, 3), [leaders]);
	const bottom = useMemo(() => {
		const sorted = [...leaders].sort((a, b) => a.saveRate - b.saveRate);
		return sorted.slice(0, 3);
	}, [leaders]);

	const Row = ({
		r,
		tone,
	}: {
		r: (typeof leaders)[number];
		tone: "up" | "down";
	}) => {
		const published = new Date(r.publishedAt);
		const dateLabel = Number.isFinite(published.getTime())
			? published.toLocaleDateString("en-US", {
					month: "short",
					day: "numeric",
				})
			: "synced post";
		const postKey = r.id ? `#${r.id.slice(-4)}` : null;

		return (
			<Link
				to={calendarPostPath(r.id, r.publishedAt)}
				className="group flex min-w-0 items-center gap-2 rounded-lg border border-border bg-muted/35 px-2.5 py-2 text-foreground no-underline transition-colors hover:bg-muted/60"
				title="Open post in calendar"
			>
				<span
					aria-hidden="true"
					className="w-2.5 shrink-0 text-sm leading-none"
					style={{ color: tone === "up" ? "var(--color-success)" : "var(--color-danger)" }}
				>
					{tone === "up" ? "↑" : "↓"}
				</span>
				{r.mediaUrl ? (
					<img
						src={r.mediaUrl}
						alt=""
						aria-hidden="true"
						style={{
							width: 26,
							height: 26,
							borderRadius: 4,
							flexShrink: 0,
							objectFit: "cover",
							opacity: tone === "up" ? 1 : 0.6,
							filter: tone === "down" ? "saturate(0.7)" : undefined,
						}}
						loading="lazy"
					/>
				) : (
					<div
						className="size-[26px] shrink-0 rounded-md"
						style={{
							background:
								tone === "up"
									? "linear-gradient(135deg, var(--color-oxblood), var(--color-chart-1))"
									: "linear-gradient(135deg, var(--color-muted), var(--color-danger))",
							opacity: tone === "up" ? 1 : 0.55,
						}}
					/>
				)}
				<div className="min-w-0 flex-1">
					<div className="truncate text-xs font-medium">
						{r.content?.slice(0, 38) ?? "No caption recorded"}
					</div>
					<div className="mt-0.5 text-[0.68rem] font-medium uppercase tracking-[0.12em] text-muted-foreground">
						{dateLabel}
						{postKey ? ` · ${postKey}` : ""}
					</div>
				</div>
				<span
					className="shrink-0 font-mono text-xs font-semibold tabular-nums"
					style={{ color: tone === "up" ? "var(--color-oxblood)" : "var(--color-danger)" }}
				>
					{(r.saveRate * 100).toFixed(1)}%
				</span>
			</Link>
		);
	};

	return (
		<NovaCard
			title="Save rate"
			description="Highest-quality engagement signal by post."
			action={<Badge tone="outline">{periodDays}d</Badge>}
			contentClassName="flex h-full flex-col gap-4"
		>
			{top.length === 0 ? (
				isLoading ? (
					<div className="flex flex-col gap-3" role="status" aria-label="Loading save-rate leaderboard">
						<SaveRateSkeletonSection label="Top 3" />
						<SaveRateSkeletonSection label="Bottom 3" />
						<p className="mt-auto text-xs leading-relaxed text-muted-foreground">
							Ranking highest- and lowest-save-rate posts.
						</p>
					</div>
				) : (
					<NovaEmpty
						className="min-h-44"
						title="No save data in window."
						description="Highest- and lowest-saving posts appear here. Saves are the strongest IG quality signal."
					/>
				)
			) : (
				<div className="flex flex-col gap-4">
					<div className="flex flex-col gap-2">
						<div className="text-[0.68rem] font-medium uppercase tracking-[0.14em] text-primary">
							Top 3
						</div>
						{top.map((r) => (
							<Row key={r.id} r={r} tone="up" />
						))}
					</div>
					<div className="flex flex-col gap-2">
						<div className="text-[0.68rem] font-medium uppercase tracking-[0.14em] text-danger">
							Bottom 3
						</div>
						{bottom.map((r) => (
							<Row key={r.id} r={r} tone="down" />
						))}
					</div>
				</div>
			)}
		</NovaCard>
	);
}

function SaveRateSkeletonSection({ label }: { label: string }) {
	return (
		<div className="flex flex-col gap-2">
			<div className="text-[0.68rem] font-medium uppercase tracking-[0.14em] text-muted-foreground">
				{label}
			</div>
			{[1, 2, 3].map((i) => (
				<div key={`${label}-${i}`} className="flex items-center gap-2 rounded-lg border border-border bg-muted/35 px-2.5 py-2">
					<Skeleton className="h-2 w-2.5 rounded-sm" />
					<Skeleton className="size-[26px] shrink-0 rounded-md" />
					<div className="flex min-w-0 flex-1 flex-col gap-1.5">
						<Skeleton className="h-3 w-3/4 rounded-md" />
						<Skeleton className="h-2 w-1/2 rounded-md" />
					</div>
					<Skeleton className="h-3 w-9 rounded-md" />
				</div>
			))}
		</div>
	);
}

// =========================================================================
// Content-mix health — col-5-8 row-7-9
// Spec §6 Widget #17 (P1) — "catch reel drought early"
// =========================================================================
export function ContentMixHealthTile({
	periodDays = 30,
	scopedAccount,
	accountIds,
	groupId,
}: TimedDashboardScopeProps) {
	const { current, previous, trail, isLoading, hasError } = useContentMixHealth(
		scopedInstagramAccountId(scopedAccount),
		scopedAccount ? undefined : accountIds,
		periodDays,
	);

	const reelsReach = current.reels?.reach ?? 0;
	const feedReach = current.feed?.reach ?? 0;
	const storyReach = current.story?.reach ?? 0;
	const total = reelsReach + feedReach + storyReach;
	const hasData = total > 0;

	const segments = useMemo(() => {
		if (!hasData) return [];
		return [
			{
				label: "Reels",
				pct: Math.round((reelsReach / total) * 100),
				color: "var(--color-oxblood)",
			},
			{
				label: "Feed",
				pct: Math.round((feedReach / total) * 100),
				color: "var(--color-chart-1)",
			},
			{
				label: "Stories",
				pct: Math.round((storyReach / total) * 100),
				color: "var(--color-chart-2)",
			},
		];
	}, [hasData, reelsReach, feedReach, storyReach, total]);

	const reelsPct = segments.find((s) => s.label === "Reels")?.pct ?? 0;
	const reelDrought = reelsPct < 25;
	const reelHeavy = reelsPct >= 55;
	const mixNeedsAction = reelDrought || reelHeavy;
	const healthLabel = reelDrought
		? "Reel drought"
		: reelHeavy
			? "Reel-heavy"
			: "Balanced";
	const actionLabel = reelDrought
		? "Shift feed/story → Reels"
		: reelHeavy
			? "Rebalance toward feed/story"
			: "Mix within target band";
	const healthColor = reelDrought
		? "var(--color-error)"
		: reelHeavy
			? "var(--color-warning)"
			: "var(--color-success)";
	const composerPath = scopedRoute(
		"/composer?platform=instagram&format=reel",
		{ scopedAccount, accountIds, groupId, platform: "instagram" },
	);
	const formatMix = (["reels", "feed", "story"] as const).map((fmt) => {
		const label =
			fmt === "reels" ? "Reels" : fmt === "feed" ? "Carousel" : "Story";
		const reach = current[fmt]?.reach ?? 0;
		const maxReach = Math.max(reelsReach, feedReach, storyReach, 1);
		const widthPct = (reach / maxReach) * 92;
		const color =
			fmt === "reels"
				? "var(--color-oxblood)"
				: fmt === "feed"
					? "var(--color-chart-1)"
					: "var(--color-chart-2)";
		return { fmt, label, reach, widthPct, color };
	});
	const weeklyShift = (["reels", "feed", "story"] as const).map((fmt) => {
		const label =
			fmt === "reels" ? "Reels" : fmt === "feed" ? "Carousel" : "Story";
		const curTotal =
			(current.reels?.reach ?? 0) +
			(current.feed?.reach ?? 0) +
			(current.story?.reach ?? 0);
		const prevTotal =
			(previous.reels?.reach ?? 0) +
			(previous.feed?.reach ?? 0) +
			(previous.story?.reach ?? 0);
		const curShare =
			curTotal > 0 ? ((current[fmt]?.reach ?? 0) / curTotal) * 100 : 0;
		const prevShare =
			prevTotal > 0 ? ((previous[fmt]?.reach ?? 0) / prevTotal) * 100 : 0;
		const ppDelta = curTotal > 0 && prevTotal > 0 ? curShare - prevShare : null;
		const sign =
			ppDelta == null ? "" : ppDelta > 0 ? "+" : ppDelta < 0 ? "-" : "";
		const color =
			ppDelta == null
				? "var(--color-muted-foreground)"
				: fmt === "reels" && ppDelta > 0
					? "var(--color-success)"
					: fmt === "feed" && ppDelta > 2
						? "var(--color-error)"
						: fmt === "story" && ppDelta < -2
							? "var(--color-warning)"
							: "var(--color-muted-foreground)";
		const value =
			ppDelta == null ? "0.0pp" : `${sign}${Math.abs(ppDelta).toFixed(1)}pp`;
		return { fmt, label, value, color };
	});

	return (
		<NovaCard
			title="Content mix"
			description={`Reach-weighted format mix over ${periodDays} days.`}
			action={
				hasData && mixNeedsAction ? (
					<Button asChild size="sm">
						<Link to={composerPath}>{reelDrought ? "Plan Reel" : "Rebalance"}</Link>
					</Button>
				) : hasData ? (
					<Badge tone={mixNeedsAction ? "danger" : "outline"}>{healthLabel}</Badge>
				) : (
					<Badge tone="outline">{periodDays}d</Badge>
				)
			}
			contentClassName="flex h-full flex-col gap-4"
		>
			{hasData ? (
				<>
					<TernaryContentMixPlot
						reelsPct={reelsPct}
						feedPct={segments.find((s) => s.label === "Feed")?.pct ?? 0}
						storyPct={segments.find((s) => s.label === "Stories")?.pct ?? 0}
						trail={trail}
					/>
					<p className="text-xs leading-relaxed text-muted-foreground">
						Position is reach-weighted, not post-count-weighted. Reels mix &lt;25% drought · 25-55% healthy · ≥55% heavy.
					</p>

					<div className="grid grid-cols-2 gap-3 border-t border-border pt-3">
						<ContentMixSummary label="Health" value={healthLabel} color={healthColor} />
						<ContentMixSummary label="Action" value={actionLabel} align="right" />
					</div>

					<div className="border-t border-border pt-3">
						<div className="mb-2 text-[0.68rem] font-medium uppercase tracking-[0.14em] text-muted-foreground">
							Weekly shift · vs prior {periodDays}d
						</div>
						<div className="grid grid-cols-3 gap-2">
							{weeklyShift.map((item) => (
								<ContentMixSummary
									key={item.fmt}
									label={item.label}
									value={item.value}
									color={item.color}
								/>
							))}
						</div>
					</div>

					<div className="border-t border-border pt-3">
						<div className="mb-2 text-[0.68rem] font-medium uppercase tracking-[0.14em] text-muted-foreground">
							Per-format reach · {periodDays}d
						</div>
						<div className="flex flex-col gap-2">
							{formatMix.map((item) => (
								<ContentMixReachRow key={item.fmt} {...item} />
							))}
						</div>
					</div>
				</>
			) : isLoading ? (
				<div className="flex flex-col gap-3" role="status" aria-label="Loading content mix">
					<Skeleton className="h-7 w-full rounded-lg" />
					{["Reels", "Carousel", "Stories"].map((label) => (
						<div key={label} className="flex items-center gap-3">
							<Skeleton className="size-2 rounded-sm" />
							<Skeleton className="h-3 flex-1 rounded-md" />
							<Skeleton className="h-3 w-9 rounded-md" />
						</div>
					))}
					<p className="mt-auto text-xs leading-relaxed text-muted-foreground">
						Reading Reels, carousel, and Story reach mix.
					</p>
				</div>
			) : (
				<NovaEmpty
					className="min-h-48"
					title={hasError ? "Content mix unavailable." : "No IG reach in window."}
					description={
						hasError
							? "Try syncing again in a moment."
							: "Reels, carousel, and stories distribution appears here to catch reel droughts early."
					}
				/>
			)}
		</NovaCard>
	);
}

function ContentMixSummary({
	label,
	value,
	color,
	align = "left",
}: {
	label: string;
	value: string;
	color?: string | undefined;
	align?: "left" | "right" | undefined;
}) {
	return (
		<div className={align === "right" ? "text-right" : undefined}>
			<div className="text-[0.68rem] font-medium uppercase tracking-[0.14em] text-muted-foreground">
				{label}
			</div>
			<div className="mt-1 text-sm font-medium" style={color ? { color } : undefined}>
				{value}
			</div>
		</div>
	);
}

function ContentMixReachRow({
	label,
	reach,
	widthPct,
	color,
}: {
	label: string;
	reach: number;
	widthPct: number;
	color: string;
}) {
	return (
		<div className="grid grid-cols-[4rem_minmax(0,1fr)_4rem] items-center gap-2 text-xs">
			<span className="truncate text-muted-foreground">{label}</span>
			<div className="h-1.5 overflow-hidden rounded-full bg-muted">
				<div
					className="h-full rounded-full"
					style={{ width: `${widthPct}%`, background: color }}
				/>
			</div>
			<span className="text-right font-mono text-xs font-semibold tabular-nums text-foreground">
				{formatReach(reach)}
			</span>
		</div>
	);
}

function TernaryContentMixPlot({
	reelsPct,
	feedPct,
	storyPct,
	trail,
}: {
	reelsPct: number;
	feedPct: number;
	storyPct: number;
	trail: Array<{
		weekStart: string;
		reelsPct: number;
		feedPct: number;
		storyPct: number;
		totalReach: number;
	}>;
}) {
	const currentPoint = ternaryPoint(reelsPct, feedPct, storyPct);
	const trailPoints = trail
		.filter((point) => point.totalReach > 0)
		.map((point) =>
			ternaryPoint(point.reelsPct, point.feedPct, point.storyPct),
		);
	const path =
		trailPoints.length > 1
			? trailPoints
					.map(
						(point, index) =>
							`${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`,
					)
					.join(" ")
			: "";

	return (
		<div className="rounded-xl border border-border bg-muted/30 p-3">
			<svg
				className="h-40 w-full overflow-visible"
				viewBox="0 0 200 184"
				role="img"
				aria-label={`Content mix ternary plot. Reels ${reelsPct} percent, feed ${feedPct} percent, stories ${storyPct} percent.`}
			>
				<path
					d="M 100 8 L 10 168 L 190 168 Z"
					fill="none"
					stroke="var(--color-border)"
					strokeWidth="1.2"
				/>
				{[
					"M 32.5 128 L 167.5 128",
					"M 55 88 L 145 88",
					"M 77.5 48 L 122.5 48",
					"M 100 8 L 55 88",
					"M 100 8 L 145 88",
					"M 32.5 128 L 77.5 48",
					"M 167.5 128 L 122.5 48",
					"M 55 88 L 167.5 128",
					"M 145 88 L 32.5 128",
				].map((d) => (
					<path
						key={d}
						d={d}
						fill="none"
						stroke="var(--color-border)"
						strokeDasharray="2 5"
						strokeOpacity="0.55"
						strokeWidth="0.8"
					/>
				))}
				{path ? (
					<path
						d={path}
						fill="none"
						stroke="var(--color-muted-foreground)"
						strokeOpacity="0.55"
						strokeWidth="1"
					/>
				) : null}
				{trail
					.filter((point) => point.totalReach > 0)
					.slice(-11)
					.map((mix, index) => {
						const point = ternaryPoint(mix.reelsPct, mix.feedPct, mix.storyPct);
						return (
							<circle
								key={mix.weekStart}
								cx={point.x}
								cy={point.y}
								r={2.5 + index * 0.08}
								fill="var(--color-muted-foreground)"
								opacity={0.28 + index * 0.04}
							/>
						);
					})}
				<circle
					cx={currentPoint.x}
					cy={currentPoint.y}
					r="4.4"
					fill="var(--color-oxblood)"
					stroke="var(--color-background)"
					strokeWidth="1.5"
				/>
				<text
					x="100"
					y="4"
					textAnchor="middle"
					fill="var(--color-muted-foreground)"
					fontSize="10"
					fontWeight="600"
				>
					Reels
				</text>
				<text
					x="6"
					y="181"
					textAnchor="start"
					fill="var(--color-muted-foreground)"
					fontSize="10"
					fontWeight="600"
				>
					Feed
				</text>
				<text
					x="194"
					y="181"
					textAnchor="end"
					fill="var(--color-muted-foreground)"
					fontSize="10"
					fontWeight="600"
				>
					Stories
				</text>
			</svg>
			<div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs text-muted-foreground">
				<span>
					<b className="font-mono text-foreground">{reelsPct}%</b> Reels
				</span>
				<span>
					<b className="font-mono text-foreground">{feedPct}%</b> Feed
				</span>
				<span>
					<b className="font-mono text-foreground">{storyPct}%</b> Stories
				</span>
			</div>
		</div>
	);
}
