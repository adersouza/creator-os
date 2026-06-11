// biome-ignore-all lint/suspicious/noExplicitAny: Supabase string-select widens row shape
// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
	NovaCard,
	NovaEmpty,
	NovaInset,
	NovaMiniStat,
} from "@/components/ui/NovaPrimitives";
import { Progress } from "@/components/ui/Progress";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAudienceWeekdayHour } from "@/hooks/useAudienceWeekdayHour";
import { useAuthUser } from "@/hooks/useAuthUser";
import { fetchConnectedAccounts } from "@/hooks/useConnectedAccounts";
import {
	useSmartLinkClickGoal,
	useSmartLinkClickSummary,
} from "@/hooks/useSmartLinkClickGoal";
import {
	type TopPostRow,
	type TopPostsPlatform,
	useTopPosts,
} from "@/hooks/useTopPosts";
import { calendarPostPath } from "@/lib/deepLinks";
import { scopedRoute } from "@/lib/scopedRoutes";
import { queryClient } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";
import { supabase } from "@/services/supabase";
import { Avatar } from "../atoms/Avatar";
import type { DashboardScopeProps } from "../scope";
import type { Platform } from "../shared";
import { formatCompact } from "../shared";

interface Props extends DashboardScopeProps {
	platform: Platform;
}

const HOUR_MS = 60 * 60 * 1000;
const SIX_HOURS_MS = 6 * HOUR_MS;
const LIVE_POST_LIMIT = 100;
const UNASSIGNED_COLOR = "#6B6B70";
const DOW_LABELS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const VIEW_HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19];

function mapLiveRow(
	row: any,
	meta: {
		handle: string;
		groupId: string | null;
		groupName: string;
		groupColor: string;
	},
): TopPostRow {
	const isIg = row.platform === "instagram";
	return {
		id: String(row.id),
		platform: isIg ? "instagram" : "threads",
		caption: typeof row.content === "string" ? row.content : "",
		mediaUrl:
			Array.isArray(row.media_urls) && row.media_urls.length
				? String(row.media_urls[0])
				: null,
		accountId: isIg
			? (row.instagram_account_id ?? null)
			: (row.account_id ?? null),
		accountHandle: meta.handle,
		groupId: meta.groupId,
		groupName: meta.groupName,
		groupColor: meta.groupColor,
		reach: isIg ? (row.ig_reach ?? 0) : (row.views_count ?? 0),
		sends: isIg ? (row.ig_shares ?? 0) : (row.shares_count ?? 0),
		saves: isIg ? (row.ig_saved ?? 0) : 0,
		likes: row.likes_count ?? 0,
		comments: isIg ? (row.ig_comment_count ?? 0) : (row.replies_count ?? 0),
		publishedAt: String(row.published_at ?? row.created_at ?? ""),
	};
}

function useLiveRecentPosts(
	platform: TopPostsPlatform,
	scopedAccount: DashboardScopeProps["scopedAccount"],
	accountIds?: string[],
) {
	const authUser = useAuthUser();
	const userKey = authUser?.id ?? null;

	const { data, isPending, isError } = useQuery({
		queryKey: [
			"liveFirstSixHours",
			userKey,
			platform,
			scopedAccount?.id ?? "fleet",
			accountIds?.join(",") ?? null,
		],
		enabled: !!userKey,
		staleTime: 60_000,
		queryFn: async (): Promise<TopPostRow[]> => {
			if (!userKey) return [];
			const since = new Date(Date.now() - SIX_HOURS_MS).toISOString();

			const postsQuery = supabase
				.from("posts")
				.select(
					"id, platform, content, media_urls, account_id, instagram_account_id, published_at, created_at, " +
						"likes_count, shares_count, replies_count, views_count, ig_saved, ig_shares, ig_comment_count, ig_reach",
				)
				.eq("user_id", userKey)
				.eq("status", "published")
				.not("published_at", "is", null)
				.gte("published_at", since)
				.order("published_at", { ascending: false })
				.limit(LIVE_POST_LIMIT);

			let scopedPostsQuery =
				platform === "all"
					? postsQuery
					: postsQuery.eq(
							"platform",
							platform === "ig" ? "instagram" : "threads",
						);
			if (scopedAccount) {
				scopedPostsQuery =
					scopedAccount.platform === "instagram"
						? scopedPostsQuery.eq("instagram_account_id", scopedAccount.id)
						: scopedPostsQuery.eq("account_id", scopedAccount.id);
			} else if (accountIds && accountIds.length > 0) {
				scopedPostsQuery = scopedPostsQuery.or(
					`account_id.in.(${accountIds.join(",")}),instagram_account_id.in.(${accountIds.join(",")})`,
				);
			}

			const [postsRes, connectedAccounts] = await Promise.all([
				scopedPostsQuery,
				queryClient.fetchQuery({
					queryKey: queryKeys.accounts.connected(userKey),
					staleTime: 5 * 60_000,
					gcTime: 15 * 60_000,
					queryFn: () => fetchConnectedAccounts(userKey),
				}),
			]);

			if (postsRes.error) throw postsRes.error;

			const metaById = new Map<
				string,
				{
					handle: string;
					groupId: string | null;
					groupName: string;
					groupColor: string;
				}
			>();
			for (const account of connectedAccounts) {
				metaById.set(account.id, {
					handle: account.handle.replace(/^@/, ""),
					groupId: account.groupId,
					groupName: account.groupName,
					groupColor: account.groupColor,
				});
			}

			return ((postsRes.data ?? []) as any[])
				.map((row) => {
					const accountId =
						row.platform === "instagram"
							? row.instagram_account_id
							: row.account_id;
					const meta = accountId
						? (metaById.get(accountId) ?? {
								handle: "unknown",
								groupId: null,
								groupName: "Unassigned",
								groupColor: UNASSIGNED_COLOR,
							})
						: {
								handle: "unknown",
								groupId: null,
								groupName: "Unassigned",
								groupColor: UNASSIGNED_COLOR,
							};
					return mapLiveRow(row, meta);
				})
				.sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));
		},
	});

	return {
		posts: data ?? [],
		isLoading: !!userKey && isPending,
		hasError: !!userKey && isError,
	};
}

export function LivePulsePanel({
	platform,
	scopedAccount,
	accountIds,
	groupId,
}: Props) {
	const recent = useLiveRecentPosts(platform, scopedAccount, accountIds);
	const thirty = useTopPosts(
		"30d",
		platform,
		scopedAccount,
		accountIds,
		groupId,
	);
	const { goal: clickGoal } = useSmartLinkClickGoal();
	const smartLinkClicks = useSmartLinkClickSummary(clickGoal.periodDays);
	const scopedIds = scopedAccount ? [scopedAccount.id] : accountIds;
	const windows = useAudienceWeekdayHour(scopedIds);
	const [liveIndex, setLiveIndex] = useState(0);
	const safeLiveIndex =
		recent.posts.length > 0 ? Math.min(liveIndex, recent.posts.length - 1) : 0;
	const live = recent.posts[safeLiveIndex] ?? null;

	const medians = useMemo(() => {
		const valid = thirty.posts.filter((p) => p.reach > 0);
		if (valid.length === 0) return null;
		const med = (vals: number[]) => {
			const sorted = [...vals].sort((a, b) => a - b);
			return sorted[Math.floor(sorted.length / 2)] ?? 0;
		};
		return {
			reach: med(valid.map((p) => p.reach)),
			sends: med(valid.map((p) => p.sends)),
			saves: med(valid.map((p) => p.saves)),
			likes: med(valid.map((p) => p.likes)),
		};
	}, [thirty.posts]);

	const ageLabel = useMemo(() => {
		if (!live) return "NO LIVE POST";
		const t = Date.parse(live.publishedAt);
		if (!Number.isFinite(t)) return "LIVE POST";
		const ageMin = Math.max(0, Math.floor((Date.now() - t) / 60000));
		const h = Math.floor(ageMin / 60);
		const m = ageMin % 60;
		return h === 0 ? `${m}M LIVE` : `${h}H ${m}M LIVE`;
	}, [live]);
	const hasNoLiveData =
		!recent.isLoading &&
		recent.posts.length === 0 &&
		smartLinkClicks.totalClicks === 0 &&
		windows.postsSampled === 0;

	return (
		<NovaCard
			variant="compact"
			eyebrow="Live pulse"
			title="Operating pulse"
			description="Recent post health, outbound clicks, and publish-window reach."
			action={
				<div className="flex flex-wrap justify-end gap-2">
					<Badge variant="outline">Last 6h</Badge>
					<Badge variant="outline">vs 30d median</Badge>
					<Badge tone="oxblood">{ageLabel}</Badge>
				</div>
			}
			aria-label="Live pulse"
		>
			{hasNoLiveData ? (
				<NovaEmpty
					title="No live pulse yet"
					description="No posts, link clicks, or reach-window sample in the last 6h."
				>
					<Button asChild variant="outline" size="sm">
						<Link
							to={scopedRoute("/links", {
								scopedAccount,
								accountIds,
								groupId,
								platform,
							})}
						>
							Open Smart Links
						</Link>
					</Button>
				</NovaEmpty>
			) : (
				<div className="grid gap-3 md:grid-cols-[minmax(0,1.25fr)_minmax(0,0.9fr)_minmax(0,0.9fr)]">
					<NovaInset className="p-3.5">
						<LivePostModule
							live={live}
							medians={medians}
							postCount={recent.posts.length}
							postIndex={safeLiveIndex}
							onPrev={() => setLiveIndex((i) => Math.max(0, i - 1))}
							onNext={() =>
								setLiveIndex((i) => Math.min(recent.posts.length - 1, i + 1))
							}
							isLoading={recent.isLoading}
							hasError={recent.hasError}
						/>
					</NovaInset>
					<NovaInset className="p-3.5">
						<LinkModule
							totalClicks={smartLinkClicks.totalClicks}
							periodDays={smartLinkClicks.periodDays}
							goalClicks={clickGoal.enabled ? clickGoal.targetClicks : null}
							topLink={smartLinkClicks.topLink}
							linkCount={smartLinkClicks.linkCount}
							isLoading={smartLinkClicks.isLoading}
							linksPath={scopedRoute("/links", {
								scopedAccount,
								accountIds,
								groupId,
								platform,
							})}
						/>
					</NovaInset>
					<NovaInset className="p-3.5">
						<WindowModule
							matrix={windows.matrix}
							peakDow={windows.peakDow}
							peakHour={windows.peakHour}
							postsSampled={windows.postsSampled}
						/>
					</NovaInset>
				</div>
			)}
		</NovaCard>
	);
}

function LivePostModule({
	live,
	medians,
	postCount,
	postIndex,
	onPrev,
	onNext,
	isLoading,
	hasError,
}: {
	live: TopPostRow | null;
	medians: {
		reach: number;
		sends: number;
		saves: number;
		likes: number;
	} | null;
	postCount: number;
	postIndex: number;
	onPrev: () => void;
	onNext: () => void;
	isLoading: boolean;
	hasError: boolean;
}) {
	if (!live) {
		return (
			<div className="flex min-w-0 gap-3">
				<Skeleton className="h-20 w-20 shrink-0 rounded-lg" />
				<div className="min-w-0 flex-1">
					<Skeleton className="h-3 w-[70%]" />
					<Skeleton className="mt-2 h-3 w-[52%]" />
					<div className="mt-4 grid grid-cols-2 gap-2 2xl:grid-cols-4">
						{["Views", "Sends", "Saves", "Likes"].map((label) => (
							<div key={label} className="rounded-md border border-border bg-card p-2">
								<span className="font-mono text-[9px] uppercase tracking-[0.08em] text-muted-foreground">
									{label}
								</span>
								<Skeleton className="mt-2 h-2 w-3/5" />
							</div>
						))}
					</div>
					<p className="mt-4 text-xs leading-snug text-muted-foreground">
						{isLoading
							? "Looking for posts published in the last 6 hours."
							: hasError
								? "Live post data unavailable. Refresh to retry."
								: "No posts in the last 6 hours. The next live post appears here with 30d median deltas."}
					</p>
				</div>
			</div>
		);
	}

	return (
		<Link
			to={calendarPostPath(live.id, live.publishedAt)}
			className="flex min-w-0 gap-4"
			title="Open live post in calendar"
		>
			<Thumb mediaUrl={live.mediaUrl} platform={live.platform} />
			<div className="min-w-0 flex-1">
				<p className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
					{live.caption?.trim() || "— no caption —"}
				</p>
				<div className="mt-2 font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
					@{live.accountHandle} ·{" "}
					{new Date(live.publishedAt).toLocaleTimeString("en-US", {
						hour: "numeric",
						minute: "2-digit",
					})}
				</div>
				{postCount > 1 ? (
					<div className="mt-2 flex items-center gap-2">
						<Button
							type="button"
							variant="outline"
							size="icon"
							onClick={(event) => {
								event.preventDefault();
								onPrev();
							}}
							disabled={postIndex === 0}
							aria-label="Previous live post"
						>
							<ChevronLeft className="size-4" />
						</Button>
						<span className="font-mono text-xs text-muted-foreground">
							{postIndex + 1} of {postCount}
						</span>
						<Button
							type="button"
							variant="outline"
							size="icon"
							onClick={(event) => {
								event.preventDefault();
								onNext();
							}}
							disabled={postIndex >= postCount - 1}
							aria-label="Next live post"
						>
							<ChevronRight className="size-4" />
						</Button>
					</div>
					) : null}
					<div className="mt-4 grid grid-cols-2 gap-2 2xl:grid-cols-4">
						<NovaMiniStat
							label="Views"
							value={formatCompact(live.reach)}
							description={formatMetricDelta(live.reach, medians?.reach ?? null)}
							tone={metricTone(live.reach, medians?.reach ?? null)}
							size="compact"
						/>
						<NovaMiniStat
							label="Sends"
							value={formatCompact(live.sends)}
							description={formatMetricDelta(live.sends, medians?.sends ?? null)}
							tone={metricTone(live.sends, medians?.sends ?? null)}
							size="compact"
						/>
						<NovaMiniStat
							label="Saves"
							value={formatCompact(live.saves)}
							description={formatMetricDelta(live.saves, medians?.saves ?? null)}
							tone={metricTone(live.saves, medians?.saves ?? null)}
							size="compact"
						/>
						<NovaMiniStat
							label="Likes"
							value={formatCompact(live.likes)}
							description={formatMetricDelta(live.likes, medians?.likes ?? null)}
							tone={metricTone(live.likes, medians?.likes ?? null)}
							size="compact"
						/>
					</div>
				</div>
		</Link>
	);
}

function Thumb({
	mediaUrl,
	platform,
}: {
	mediaUrl: string | null;
	platform: "threads" | "instagram";
}) {
	return (
		<div className="relative h-20 w-20 shrink-0 overflow-hidden rounded-lg border border-border bg-muted">
			{mediaUrl ? (
				<img
					src={mediaUrl}
					alt=""
					loading="lazy"
					decoding="async"
					className="h-full w-full object-cover"
				/>
			) : null}
			{platform === "instagram" ? (
				<span className="absolute bottom-1.5 left-1.5 rounded-sm bg-foreground/70 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.08em] text-background">
					Reel
				</span>
			) : null}
		</div>
	);
}

function metricDelta(value: number, median: number | null) {
	const delta =
		median != null && median > 0
			? Math.round(((value - median) / median) * 100)
		: null;
	return delta;
}

function formatMetricDelta(value: number, median: number | null) {
	const delta = metricDelta(value, median);
	return delta == null ? "no med" : `${delta >= 0 ? "+" : ""}${delta}%`;
}

function metricTone(
	value: number,
	median: number | null,
): "default" | "success" | "danger" {
	const delta = metricDelta(value, median);
	if (delta == null) return "default";
	return delta >= 0 ? "success" : "danger";
}

function LinkModule({
	totalClicks,
	periodDays,
	goalClicks,
	topLink,
	linkCount,
	isLoading,
	linksPath,
}: {
	totalClicks: number;
	periodDays: number;
	goalClicks: number | null;
	topLink: {
		id: string;
		code: string;
		title: string | null;
		clicks: number;
	} | null;
	linkCount: number;
	isLoading: boolean;
	linksPath: string;
}) {
	const progressPct =
		goalClicks && goalClicks > 0
			? Math.min(100, Math.round((totalClicks / goalClicks) * 100))
			: null;
	return (
		<div className="flex min-w-0 flex-col gap-3">
			<div className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
				Smart link clicks · {periodDays}D
			</div>
			<div className="flex items-baseline gap-2">
				<strong className="text-2xl font-semibold tracking-[-0.03em] text-foreground">
					{isLoading ? "Sync" : formatCompact(totalClicks)}
				</strong>
				<span className="text-xs text-muted-foreground">
					{goalClicks
						? `of ${formatCompact(goalClicks)} goal`
						: "total tracked"}
				</span>
			</div>
			{progressPct != null ? (
				<Progress
					value={progressPct}
					title={`${formatCompact(totalClicks)} of ${formatCompact(goalClicks ?? 0)} smart-link clicks`}
				/>
			) : !isLoading ? (
				<p className="text-xs leading-snug text-muted-foreground">
					Set a Smart Links goal to turn this into a progress bar.
				</p>
			) : null}
			{topLink ? (
				<Link
					to={linksPath}
					className="flex min-w-0 items-center gap-3 rounded-lg border border-border bg-card p-3 text-foreground transition-colors hover:bg-muted"
					title="Open Smart Links"
				>
					<Avatar seed={topLink.code || topLink.id} size="sm" />
					<div className="min-w-0 flex-1">
						<div className="truncate text-sm font-medium">
							/{topLink.code || "smart-link"}
						</div>
						<div className="truncate text-xs text-muted-foreground">
							{topLink.title || "top clicked link"}
						</div>
					</div>
					<b className="font-mono text-sm text-primary">
						{formatCompact(topLink.clicks)}
					</b>
				</Link>
			) : (
				<p className="text-xs leading-snug text-muted-foreground">
					{linkCount > 0
						? "No smart-link clicks in this window."
						: "Create a Smart Link to start tracking clicks."}
				</p>
			)}
		</div>
	);
}

function WindowModule({
	matrix,
	peakDow,
	peakHour,
	postsSampled,
}: {
	matrix: number[][];
	peakDow: number;
	peakHour: number;
	postsSampled: number;
}) {
	const hasSample = postsSampled > 0;
	const peakLabel =
		peakDow >= 0 && peakHour >= 0
			? `${DOW_LABELS[peakDow]} ${formatHour(peakHour)}`
			: "No peak";
	return (
		<div className="flex min-w-0 flex-col gap-3">
			<div className="flex items-baseline justify-between gap-2">
				<div className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
					Reach windows
				</div>
				<Badge variant="outline">{hasSample ? "30D sample" : "No sample"}</Badge>
			</div>
			<div
				className="grid grid-cols-12 gap-0.5"
				role="img"
				aria-label="Reach by weekday and hour"
				style={{ opacity: hasSample ? 1 : 0.58 }}
			>
				{DOW_LABELS.flatMap((label, dow) =>
					VIEW_HOURS.map((hour) => {
						const value = hasSample ? (matrix[dow]?.[hour] ?? 0) : 0;
						const peak = dow === peakDow && hour === peakHour && hasSample;
						return (
							<span
								key={`${label}-${hour}`}
								title={`${label} ${formatHour(hour)} reach window`}
								className="h-2.5 rounded-[3px] border border-border/40"
								style={{ background: heatColor(value, peak) }}
							/>
						);
					}),
				)}
			</div>
			<div className="grid grid-cols-2 gap-2">
				<NovaMiniStat
					label="Peak"
					value={hasSample ? peakLabel : "Pending"}
					description="reach"
					tone={hasSample ? "primary" : "default"}
					size="compact"
				/>
				<NovaMiniStat
					label="Sample"
					value={formatCompact(postsSampled)}
					description="posts"
					tone={hasSample ? "success" : "default"}
					size="compact"
				/>
			</div>
		</div>
	);
}

function formatHour(h: number): string {
	if (h === 0) return "12a";
	if (h === 12) return "12p";
	if (h < 12) return `${h}a`;
	return `${h - 12}p`;
}

function heatColor(value: number, peak: boolean) {
	if (peak) return "var(--color-oxblood)";
	if (value <= 0) return "color-mix(in srgb, var(--color-foreground) 4%, transparent)";
	if (value < 0.25) return "color-mix(in srgb, var(--color-oxblood) 20%, transparent)";
	if (value < 0.5) return "color-mix(in srgb, var(--color-oxblood) 42%, transparent)";
	if (value < 0.75) return "color-mix(in srgb, var(--color-oxblood) 62%, transparent)";
	return "color-mix(in srgb, var(--color-oxblood) 82%, transparent)";
}
