// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, CalendarClock, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useActivity } from "@/contexts/ActivityContext";
import { cn } from "@/lib/utils";
import { invalidateDashboardQueries } from "@/lib/dashboardQueryInvalidation";
import { shortLabelFor } from "@/lib/socialPlatform";
import { calendarPostPath } from "@/lib/deepLinks";
import { useAuthUser } from "@/hooks/useAuthUser";
import { useFleetTotals } from "@/hooks/useFleetTotals";
import {
	useNextUpPosts,
	type NextUpItem as RealNextUpItem,
} from "@/hooks/useNextUpPosts";
import { useNeedsAttention } from "@/hooks/useNeedsAttention";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { useTopPosts } from "@/hooks/useTopPosts";
import { useAccountGroups } from "@/hooks/useAccountGroups";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";
import { greetingForHour } from "@/lib/format";
import { buildScopeCopy } from "@/lib/scopeLabels";
import { scopedRoute } from "@/lib/scopedRoutes";
import {
	MobileBrandTopBar,
	MobilePageShell,
	MobileSection,
	MobileSegmented,
	type MobileSegmentedOption,
} from "@/components/layout/mobile";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { NovaCard, NovaEmpty, NovaStat } from "@/components/ui/NovaPrimitives";

/**
 * Mobile Overview — single-column glass dashboard for ≤1023px.
 *
 * Layout (top → bottom):
 *   1. MobileBrandTopBar  (sigil + Juno33/Operator + health pill + bell)
 *   2. MobileSegmented    (All / Threads / Instagram)
 *   3. Greeting + meta
 *   4. MobileSegmented    (7d / 30d / 90d)
 *   5. AlertCard          (accounts needing attention)
 *   6. Account pulse      (shadcn/Nova mobile stat cards)
 *   7. NextUpStrip        (next 3-5 scheduled posts)
 *   8. TopPerformingMobile (3-row leaderboard)
 *
 * Bottom tab bar lives in Layout via <MobileTabBar/>.
 */

type Platform = "all" | "threads" | "ig";
type Timeframe = "7" | "30" | "90";

const PLATFORM_OPTIONS: MobileSegmentedOption<Platform>[] = [
	{ id: "all", label: "All" },
	{ id: "threads", label: "Threads" },
	{ id: "ig", label: "Instagram" },
];

const TIMEFRAME_OPTIONS: MobileSegmentedOption<Timeframe>[] = [
	{ id: "7", label: "7d" },
	{ id: "30", label: "30d" },
	{ id: "90", label: "90d" },
];

interface TopRow {
	postId: string;
	rank: number;
	handle: string;
	metricLabel: string;
	metricValue: string;
	grad: string;
	platform: "threads" | "ig";
	publishedAt: string;
}

function formatCompactCount(value: number): string {
	if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
	if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
	return value.toLocaleString();
}

function toTopRows(posts: ReturnType<typeof useTopPosts>["posts"]): TopRow[] {
	return posts.slice(0, 3).map((post, index) => {
		const isIg = post.platform === "instagram";
		return {
			postId: post.id,
			rank: index + 1,
			handle: post.accountHandle.startsWith("@")
				? post.accountHandle
				: `@${post.accountHandle}`,
			metricLabel: isIg ? "Sends + Saves" : "Replies + Reposts",
			metricValue: formatCompactCount(
				isIg ? post.sends + post.saves : post.comments + post.sends,
			),
			grad: `linear-gradient(135deg, ${post.groupColor}, color-mix(in srgb, ${post.groupColor} 32%, white))`,
			platform: isIg ? "ig" : "threads",
			publishedAt: post.publishedAt,
		};
	});
}

/* ---------- Alert ---------- */
function AlertCard({ title, sub, href }: { title: string; sub: string; href: string }) {
	return (
		<Link
			to={href}
			className="mb-3 block cursor-pointer active:opacity-80"
		>
			<NovaCard
				variant="compact"
				className="border-primary/20 bg-primary/5"
				contentClassName="flex items-start gap-2.5 p-3"
			>
				<span
					className="flex size-[22px] shrink-0 items-center justify-center rounded-md bg-primary text-[0.6875rem] font-bold text-primary-foreground"
				>
					<AlertCircle className="size-3" />
				</span>
				<div className="min-w-0">
					<div className="text-[0.8125rem] font-medium text-foreground">
						{title}
					</div>
					<div className="mt-0.5 text-[0.6875rem] leading-[1.4] text-muted-foreground">
						{sub}
					</div>
				</div>
			</NovaCard>
		</Link>
	);
}

function AccountPulse({
	accounts,
	scheduledToday,
	attentionTotal,
	publishSuccessPct,
	queueDepthDays,
	isLoading,
	hasError,
}: {
	accounts: number;
	scheduledToday: number;
	attentionTotal: number;
	publishSuccessPct: number | null;
	queueDepthDays: number | null;
	isLoading: boolean;
	hasError: boolean;
}) {
	const publishCopy =
		publishSuccessPct === null ? "Pending" : `${publishSuccessPct}%`;
	const queueCopy = queueDepthDays === null ? "No queue data" : `${queueDepthDays}d coverage`;

	return (
		<div className="mb-3">
			<div className="mb-2 px-1 text-[0.625rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
				Account pulse
			</div>
			<div className="grid grid-cols-2 gap-2">
				<MobileStatCard
					label="Fleet"
					value={isLoading ? "..." : hasError ? "Error" : accounts.toLocaleString()}
					description="Connected accounts"
				/>
				<MobileStatCard
					label="Today"
					value={isLoading ? "..." : scheduledToday.toLocaleString()}
					description="Scheduled posts"
				/>
				<MobileStatCard
					label="Attention"
					value={attentionTotal.toLocaleString()}
					description={attentionTotal === 1 ? "Account flagged" : "Accounts flagged"}
					tone={attentionTotal > 0 ? "danger" : "default"}
				/>
				<MobileStatCard
					label="Publishing"
					value={publishCopy}
					description={queueCopy}
					tone={publishSuccessPct !== null && publishSuccessPct < 95 ? "danger" : "default"}
				/>
			</div>
		</div>
	);
}

function MobileStatCard({
	label,
	value,
	description,
	tone = "default",
}: {
	label: string;
	value: string;
	description: string;
	tone?: "default" | "danger";
}) {
	return (
		<NovaStat
			className="min-h-[116px]"
			variant="compact"
			label={label}
			value={value}
			description={description}
			status={tone === "danger" ? "Review" : undefined}
		/>
	);
}

/* ---------- Next up strip ---------- */
function NextUpStrip({
	items,
	onOpenQueue,
}: {
	items: RealNextUpItem[];
	onOpenQueue: () => void;
}) {
	return (
		<div className="mb-3">
			<div className="flex items-center justify-between mb-1">
				<span className="text-[0.8125rem] font-medium text-foreground">
					Next up
				</span>
				<Button
					type="button"
					onClick={onOpenQueue}
					variant="ghost"
					size="sm"
					className="min-h-11 min-w-11 px-2 text-[0.75rem]"
				>
					Queue →
				</Button>
			</div>
			{items.length === 0 ? (
				<NovaCard variant="compact" contentClassName="p-0">
					<NovaEmpty
						className="p-4"
						icon={<CalendarClock data-icon="inline-start" aria-hidden="true" />}
						title="Nothing scheduled soon"
						description="The next-hour queue is clear."
					/>
				</NovaCard>
			) : (
				<div
					className="flex gap-2 overflow-x-auto -mx-4 px-4 pb-1 scrollbar-hide"
					style={{ WebkitOverflowScrolling: "touch", scrollbarWidth: "none" }}
				>
					{items.map((n) => (
						<Link
							to={calendarPostPath(n.id, n.scheduledAt)}
							key={n.id}
							className="shrink-0 min-w-[200px] rounded-xl border border-border bg-card p-2.5 shadow-sm flex gap-2 items-start cursor-pointer active:opacity-80"
						>
								<span
									className="font-mono text-[0.6875rem] font-semibold tabular-nums shrink-0 min-w-[32px]"
									style={{
										color: n.isAccent
											? "var(--color-oxblood)"
											: "var(--muted-foreground)",
									}}
								>
								{n.time}
							</span>
							<div className="flex-1 min-w-0">
								<div className="text-[0.75rem] font-medium text-foreground truncate">
									{n.text || "(empty caption)"}
								</div>
									<div className="truncate text-[0.625rem] text-muted-foreground">
										{n.handle} · {shortLabelFor(n.platform)}
									</div>
							</div>
							<span
								className="text-[0.625rem] px-1.5 py-0.5 rounded-full font-medium shrink-0"
								style={{
									color: n.groupColor,
									backgroundColor: `color-mix(in srgb, ${n.groupColor} 12%, transparent)`,
								}}
							>
								{n.groupName}
							</span>
						</Link>
					))}
				</div>
			)}
		</div>
	);
}

/* ---------- Top performing condensed ---------- */
function TopPerformingMobile({
	rows,
	isLoading,
	hasError,
	onOpenAnalytics,
}: {
	rows: TopRow[];
	isLoading: boolean;
	hasError: boolean;
	onOpenAnalytics: () => void;
}) {
	return (
		<MobileSection
			title="Top performing"
			right={
				<Button
					type="button"
					onClick={onOpenAnalytics}
					variant="ghost"
					size="sm"
					className="arrow-link min-h-11 min-w-11 px-2 text-[0.75rem]"
				>
					All{" "}
					<span className="arrow" aria-hidden="true">
						→
					</span>
				</Button>
			}
		>
			{isLoading ? (
					<NovaEmpty
						className="p-4"
						title="Loading top posts"
						description="Checking the current performance window."
					/>
				) : hasError ? (
					<NovaEmpty
						className="p-4"
						title="Top posts unavailable"
						description="Pull to refresh and try again."
					/>
				) : rows.length === 0 ? (
					<NovaEmpty
						className="p-4"
						title="No published posts yet"
						description="Published post performance appears here for this window."
					/>
			) : (
				rows.map((r, i) => (
					<Link
						to={calendarPostPath(r.postId, r.publishedAt)}
						key={`${r.handle}-${r.rank}`}
						className={cn(
							"flex items-center gap-2 py-2 text-[0.75rem] cursor-pointer active:opacity-80",
							i > 0 && "border-t border-border",
						)}
					>
							<span className="w-4 text-center font-mono text-[0.6875rem] font-semibold text-muted-foreground">
								{r.rank}
							</span>
							<span
								className="size-[22px] shrink-0 rounded-full"
								style={{ background: r.grad }}
								aria-hidden="true"
							/>
						<span className="flex-1 font-medium text-foreground truncate">
							{r.handle}
						</span>
							<span className="text-[0.6875rem] text-muted-foreground tabular-nums">
								{r.metricLabel}
							</span>
						<span
							className="text-[0.75rem] font-medium tabular-nums"
							style={{ color: "var(--color-oxblood)" }}
						>
							{r.metricValue}
						</span>
					</Link>
				))
			)}
		</MobileSection>
	);
}

/* ---------- Root ---------- */
export function MobileOverview({
	scopedAccount = null,
	accountIds,
	groupId,
}: {
	scopedAccount?: AccountScopeValue | null | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
}) {
	const [platform, setPlatform] = useState<Platform>("all");
	const [timeframe, setTimeframe] = useState<Timeframe>("7");
	const navigate = useNavigate();
	const { open: openActivity } = useActivity();
	const authUser = useAuthUser();
	const greetingName = authUser?.firstName ?? "there";
	const [currentHour, setCurrentHour] = useState(() => new Date().getHours());
	useEffect(() => {
		let timeoutId: number | undefined;
		const refresh = () => setCurrentHour(new Date().getHours());
		const scheduleNextBoundary = () => {
			const now = new Date();
			const msToNextHour =
				(60 - now.getMinutes()) * 60 * 1000 -
				now.getSeconds() * 1000 -
				now.getMilliseconds() +
				50;
			timeoutId = window.setTimeout(() => {
				refresh();
				scheduleNextBoundary();
			}, msToNextHour);
		};
		scheduleNextBoundary();
		document.addEventListener("visibilitychange", refresh);
		return () => {
			document.removeEventListener("visibilitychange", refresh);
			if (timeoutId !== undefined) window.clearTimeout(timeoutId);
		};
	}, []);
	const greeting = greetingForHour(currentHour);
	const fleet = useFleetTotals();
	const { groups } = useAccountGroups();
	const selectedGroup = useMemo(
		() =>
			!scopedAccount && groupId
				? groups.find((group) => group.id === groupId) ?? null
				: null,
		[groups, groupId, scopedAccount],
	);
	const scopeCopy = useMemo(
		() =>
			buildScopeCopy({
				scopedAccount,
				group: selectedGroup,
				accountCount: accountIds?.length ?? (fleet.hasError ? null : fleet.accounts),
				platformLabel: "All accounts",
			}),
		[accountIds?.length, fleet.accounts, fleet.hasError, scopedAccount, selectedGroup],
	);
	const effectivePlatform: Platform = scopedAccount
		? scopedAccount.platform === "instagram"
			? "ig"
			: "threads"
		: platform;
	const livePlatform =
		effectivePlatform === "threads" || effectivePlatform === "ig"
			? effectivePlatform
			: "all";
	const { items: attentionItems, totalCount: attentionTotal } =
		useNeedsAttention(
			livePlatform,
			timeframe,
			scopedAccount,
			accountIds,
			groupId,
		);
	const system = useSystemStatus();
	const { items: nextUpItems } = useNextUpPosts(
		livePlatform,
		"7",
		scopedAccount,
		accountIds,
		groupId,
	);
	const {
		posts: topPosts,
		isLoading: topPostsLoading,
		hasError: topPostsError,
	} = useTopPosts(timeframe, livePlatform, scopedAccount, accountIds, groupId);
	const topRows = useMemo(() => toTopRows(topPosts), [topPosts]);
	const hasSystemWarning =
		attentionTotal > 0 ||
		(system.queueDepthDays !== null && system.queueDepthDays < 4) ||
		(system.publishSuccessPct !== null && system.publishSuccessPct < 95) ||
		system.pendingApprovals > 0;
	const healthLabel =
		fleet.isLoading || system.isLoading
			? "Checking system status"
			: attentionTotal > 0
				? scopedAccount
					? "Account needs attention"
					: `${attentionTotal} ${attentionTotal === 1 ? "account needs" : "accounts need"} attention`
				: system.pendingApprovals > 0
					? `${system.pendingApprovals} ${system.pendingApprovals === 1 ? "approval waiting" : "approvals waiting"}`
					: system.publishSuccessPct !== null && system.publishSuccessPct < 95
						? `Publish success ${system.publishSuccessPct}%`
						: system.queueDepthDays !== null && system.queueDepthDays < 4
							? `Queue depth ${system.queueDepthDays} ${system.queueDepthDays === 1 ? "day" : "days"}`
							: "All systems green";
	const healthTone: "good" | "warn" =
		!fleet.isLoading && !system.isLoading && hasSystemWarning ? "warn" : "good";

	const queryClient = useQueryClient();
	const handleRefresh = useCallback(
		() => invalidateDashboardQueries(queryClient),
		[queryClient],
	);
	const isFirstRun =
		!scopedAccount &&
		!fleet.isLoading &&
		!fleet.hasError &&
		fleet.accounts === 0;

	if (isFirstRun) {
		return (
			<MobilePageShell
				hideAt="lg"
				onPullRefresh={handleRefresh}
				topBar={
					<MobileBrandTopBar
						onOpenActivity={openActivity}
						statusLabel="Connect first account"
						statusTone="warn"
					/>
				}
			>
				<h1 className="sr-only">Dashboard overview</h1>
				<NovaEmpty
					icon={<Plus data-icon aria-hidden="true" />}
					title="Connect your first account to see your dashboard"
					description="Juno33 needs at least one Threads or Instagram account to render the dashboard."
				>
					<div className="flex flex-col items-center gap-3">
						<Badge tone="outline">First run</Badge>
						<Button type="button" onClick={() => navigate("/accounts")}>
							Connect account
						</Button>
					</div>
				</NovaEmpty>
			</MobilePageShell>
		);
	}

	return (
		<MobilePageShell
			hideAt="lg"
			onPullRefresh={handleRefresh}
			topBar={
				<MobileBrandTopBar
					onOpenActivity={openActivity}
					statusLabel={healthLabel}
					statusTone={healthTone}
				/>
			}
		>
			<h1 className="sr-only">Dashboard overview</h1>
			{!scopedAccount && (
				<MobileSegmented<Platform>
					ariaLabel="Mobile dashboard platform filters"
					value={effectivePlatform}
					onChange={setPlatform}
					options={PLATFORM_OPTIONS}
				/>
			)}

			<div className="mt-3">
				<div className="text-[clamp(1rem,3.5vw,1.25rem)] font-medium tracking-[-0.025em] text-foreground leading-tight">
					{greeting}, {greetingName}
				</div>
				<div className="mb-1 mt-0.5 text-[0.6875rem] text-muted-foreground">
					{scopedAccount
						? `Account ${scopedAccount.handle.startsWith("@") ? scopedAccount.handle : `@${scopedAccount.handle}`} · ${healthLabel.toLowerCase()}`
						: `${scopeCopy.chip} · ${fleet.scheduledToday.toLocaleString()} scheduled · ${healthLabel.toLowerCase()}`}
				</div>
			</div>

			<div className="mb-3">
				<MobileSegmented<Timeframe>
					variant="tab"
					ariaLabel="Mobile dashboard timeframe filters"
					value={timeframe}
					onChange={setTimeframe}
					options={TIMEFRAME_OPTIONS}
				/>
			</div>

			{attentionItems.length > 0 && (
				<AlertCard
					title={
						scopedAccount
							? `${scopedAccount.handle.startsWith("@") ? scopedAccount.handle : `@${scopedAccount.handle}`} needs attention`
							: attentionTotal === 1
								? `${attentionItems[0]!.handle} needs attention`
								: `${attentionTotal} accounts need attention`
					}
					sub={attentionItems
						.slice(0, 2)
						.map((i) => `${i.handle} · ${i.issue}`)
						.join(" · ")}
					href={scopedRoute(
						"/accounts",
						{ scopedAccount, accountIds, groupId, platform: effectivePlatform },
						{ status: "flagged" },
					)}
				/>
			)}

			<AccountPulse
				accounts={fleet.accounts}
				scheduledToday={fleet.scheduledToday}
				attentionTotal={attentionTotal}
				publishSuccessPct={system.publishSuccessPct}
				queueDepthDays={system.queueDepthDays}
				isLoading={fleet.isLoading || system.isLoading}
				hasError={fleet.hasError}
			/>

			<NextUpStrip
				items={nextUpItems}
				onOpenQueue={() =>
					navigate(
						scopedRoute("/calendar", {
							scopedAccount,
							accountIds,
							groupId,
							platform: effectivePlatform,
						}),
					)
				}
			/>

			<TopPerformingMobile
				rows={topRows}
				isLoading={topPostsLoading}
				hasError={topPostsError}
				onOpenAnalytics={() =>
					navigate(
						scopedRoute("/analytics", {
							scopedAccount,
							accountIds,
							groupId,
							platform: effectivePlatform,
							timeframe: `${timeframe}d`,
						}),
					)
				}
			/>
		</MobilePageShell>
	);
}
