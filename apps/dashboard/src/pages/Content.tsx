import type React from "react";
import { useMemo, useState } from "react";
import {
	ArrowUpRight,
	BarChart3,
	CalendarClock,
	Image as ImageIcon,
	MessageCircle,
	Send,
	Sparkles,
	TrendingUp,
	TriangleAlert,
} from "lucide-react";
import { Link } from "react-router-dom";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { Badge } from "@/components/ui/Badge";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { Button } from "@/components/ui/Button";
import {
	NovaCard,
	NovaEmpty,
	NovaHeader,
	NovaListRow,
	NovaMiniStat,
	NovaSection,
	NovaStat,
	NovaToolbar,
} from "@/components/ui/NovaPrimitives";
import { Separator } from "@/components/ui/Separator";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { useSelectedGroupAccountIds } from "@/hooks/useSelectedGroupAccountIds";
import { useTopPosts, type TopPostRow, type TopPostsPlatform, type TopPostsTimeframe } from "@/hooks/useTopPosts";
import {
	buildContentOperations,
	discoveryScore,
	engagementTotal,
	formatCompact,
} from "@/lib/contentOperations";
import { calendarPostPath } from "@/lib/deepLinks";
import { cn } from "@/lib/utils";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";

type PlatformFilter = TopPostsPlatform;
type WindowFilter = "7d" | "30d" | "90d";

const WINDOWS: Array<{ value: WindowFilter; label: string; timeframe: TopPostsTimeframe }> = [
	{ value: "7d", label: "7d", timeframe: "7d" },
	{ value: "30d", label: "30d", timeframe: "30d" },
	{ value: "90d", label: "90d", timeframe: "90d" },
];
const DEFAULT_WINDOW: (typeof WINDOWS)[number] = { value: "30d", label: "30d", timeframe: "30d" };

const PLATFORMS: Array<{ value: PlatformFilter; label: string }> = [
	{ value: "all", label: "All" },
	{ value: "threads", label: "Threads" },
	{ value: "ig", label: "Instagram" },
];

function formatDate(value: string) {
	if (!value) return "Published";
	return new Intl.DateTimeFormat(undefined, {
		month: "short",
		day: "numeric",
		hour: "numeric",
		minute: "2-digit",
	}).format(new Date(value));
}

function platformLabel(post: TopPostRow) {
	return post.platform === "instagram" ? "Instagram" : "Threads";
}

function platformLogoName(post: TopPostRow) {
	return post.platform === "instagram" ? "instagram" : "threads";
}

export function Content() {
	const scopedAccount = useAccountScopeStore((state) => state.scopedAccount);
	const { accountIds, groupId } = useSelectedGroupAccountIds(scopedAccount);
	const [windowFilter, setWindowFilter] = useState<WindowFilter>("30d");
	const [platform, setPlatform] = useState<PlatformFilter>("all");
	const selectedWindow = WINDOWS.find((window) => window.value === windowFilter) ?? DEFAULT_WINDOW;
	const { posts, isLoading, hasError } = useTopPosts(
		selectedWindow.timeframe,
		platform,
		scopedAccount,
		accountIds,
		groupId,
	);

	const operations = useMemo(() => buildContentOperations(posts), [posts]);
	const {
		recentPosts,
		topPost,
		winningPosts,
		reviewPosts,
		platformBreakdown,
		totalReach,
		totalDiscovery,
		totalEngagement,
		reviewThreshold,
		lowReachCount,
	} = operations;
	const scopeLabel = scopedAccount ? `@${scopedAccount.handle}` : groupId ? "Selected group" : "Fleet";

	return (
		<NovaScreen width="wide">
			<NovaHeader
				eyebrow="Content"
				title="Posted content"
				description="See what went live, which posts are carrying discovery, and which posts need a closer read."
				meta={`${scopeLabel} · ${selectedWindow.label}`}
				actions={
					<NovaToolbar>
						<Button asChild variant="outline">
							<Link to="/content-library">
								<ImageIcon data-icon="inline-start" aria-hidden="true" />
								Media library
							</Link>
						</Button>
						<Button asChild>
							<Link to="/composer">
								<Sparkles data-icon="inline-start" aria-hidden="true" />
								Create post
							</Link>
						</Button>
					</NovaToolbar>
				}
				filters={
					<NovaToolbar>
						<Tabs value={platform} onValueChange={(value) => setPlatform(value as PlatformFilter)}>
							<TabsList aria-label="Filter content by platform">
								{PLATFORMS.map((option) => (
									<TabsTrigger key={option.value} value={option.value}>
										{option.label}
									</TabsTrigger>
								))}
							</TabsList>
						</Tabs>
						<Tabs value={windowFilter} onValueChange={(value) => setWindowFilter(value as WindowFilter)}>
							<TabsList aria-label="Filter content by time window">
								{WINDOWS.map((option) => (
									<TabsTrigger key={option.value} value={option.value}>
										{option.label}
									</TabsTrigger>
								))}
							</TabsList>
						</Tabs>
					</NovaToolbar>
				}
			/>

			<div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
				<NovaStat
					label="Published posts"
					value={isLoading ? "..." : posts.length.toLocaleString()}
					description="Synced posts in this window"
					icon={<CalendarClock className="size-4" />}
					loading={isLoading}
				/>
				<NovaStat
					label="Views / reach"
					value={formatCompact(totalReach)}
					description="Uses synced views when IG reach is unavailable"
					icon={<BarChart3 className="size-4" />}
					loading={isLoading}
				/>
				<NovaStat
					label="Discovery actions"
					value={formatCompact(totalDiscovery)}
					description="Sends + saves, or replies + reposts"
					icon={<Send className="size-4" />}
					loading={isLoading}
				/>
				<NovaStat
					label="Needs review"
					value={lowReachCount.toLocaleString()}
					description="Posts below this window's distribution baseline"
					status={lowReachCount > 0 ? "watch" : "clear"}
					loading={isLoading}
				/>
			</div>

			<div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
				<NovaCard
					title="Recent posts"
					description="Chronological view of what actually went out and how it is performing."
					action={<Badge tone="outline">{posts.length} loaded</Badge>}
					contentClassName="p-0"
				>
					{isLoading ? (
						<PostListSkeleton />
					) : hasError ? (
						<ContentEmpty
							title="Could not load posted content"
							description="The published post feed failed to load. Try refreshing after the API settles."
						/>
					) : recentPosts.length === 0 ? (
						<ContentEmpty
							title="No published posts in this window"
							description="Switch the time window or create a post to start tracking performance here."
							action={
								<Button asChild>
									<Link to="/composer">Create post</Link>
								</Button>
							}
						/>
					) : (
						<div className="divide-y divide-border">
							{recentPosts.map((post) => (
								<PostRow key={post.id} post={post} reviewThreshold={reviewThreshold} />
							))}
						</div>
					)}
				</NovaCard>

				<NovaSection>
					<NovaCard
						title="Best current signal"
						description="The post with the strongest discovery-weighted response."
					>
						{isLoading ? (
							<div className="grid gap-3">
								<Skeleton className="h-6 w-2/3" />
								<Skeleton className="h-24 w-full" />
								<Skeleton className="h-4 w-1/2" />
							</div>
						) : topPost ? (
							<div className="flex flex-col gap-4">
								<div className="rounded-md border border-border bg-muted/35 p-3">
									<div className="mb-2 flex items-center justify-between gap-2">
										<Badge tone={topPost.platform === "instagram" ? "oxblood" : "secondary"}>
											{platformLabel(topPost)}
										</Badge>
										<span className="text-sm text-muted-foreground">{formatDate(topPost.publishedAt)}</span>
									</div>
									<p className="line-clamp-5 text-sm leading-relaxed text-foreground">
										{topPost.caption || "Untitled post"}
									</p>
								</div>
								<div className="grid grid-cols-2 gap-2">
									<NovaMiniStat label="Views / reach" value={formatCompact(topPost.reach)} />
									<NovaMiniStat
										label="Discovery"
										value={formatCompact(discoveryScore(topPost))}
										tone="primary"
									/>
									<NovaMiniStat label="Likes" value={formatCompact(topPost.likes)} />
									<NovaMiniStat label="Comments" value={formatCompact(topPost.comments)} />
								</div>
								<Button asChild variant="outline">
									<Link to={calendarPostPath(topPost.id, topPost.publishedAt)}>
										Open post detail
										<ArrowUpRight data-icon="inline-end" aria-hidden="true" />
									</Link>
								</Button>
							</div>
						) : (
							<ContentEmpty
								title="No signal yet"
								description="Published content will appear here once synced metrics are available."
							/>
						)}
					</NovaCard>

					<NovaCard
						title="Operator queue"
						description="The next posts to inspect, repeat, or turn into a follow-up."
						action={
							<Badge tone={lowReachCount > 0 ? "danger" : "outline"}>
								{lowReachCount > 0 ? `${lowReachCount} review` : "Clear"}
							</Badge>
						}
					>
						{isLoading ? (
							<div className="grid gap-3">
								<Skeleton className="h-16 w-full" />
								<Skeleton className="h-16 w-full" />
							</div>
						) : reviewPosts.length > 0 || winningPosts.length > 0 ? (
							<div className="flex flex-col gap-3">
								{reviewPosts.map((post) => (
									<ActionPost
										key={`review-${post.id}`}
										post={post}
										label="Review"
										tone="danger"
										icon={<TriangleAlert aria-hidden="true" />}
										description={`${formatCompact(post.reach)} views/reach is below this window's baseline.`}
										to={calendarPostPath(post.id, post.publishedAt)}
										action="Open"
									/>
								))}
								{reviewPosts.length > 0 && winningPosts.length > 0 ? <Separator /> : null}
								{winningPosts.slice(0, reviewPosts.length > 0 ? 1 : 3).map((post) => (
									<ActionPost
										key={`win-${post.id}`}
										post={post}
										label="Follow up"
										tone="outline"
										icon={<TrendingUp aria-hidden="true" />}
										description={`${formatCompact(discoveryScore(post))} discovery actions. Build the next variant from this signal.`}
										to="/composer"
										action="Create"
									/>
								))}
							</div>
						) : (
							<ContentEmpty
								title="No operator actions"
								description="Published content will create review and follow-up actions here."
							/>
						)}
					</NovaCard>

					<NovaCard title="Content mix" description="A compact read on loaded posts in this scope.">
						<div className="grid gap-2">
							{platformBreakdown.map((item) => (
								<NovaMiniStat
									key={item.label}
									label={item.label}
									value={item.count.toLocaleString()}
									description="Published posts"
								/>
							))}
							<Separator />
							<NovaMiniStat
								label="Total engagement"
								value={formatCompact(totalEngagement)}
								description="Likes + comments + shares/saves"
								tone="success"
							/>
							<NovaMiniStat
								label="Review baseline"
								value={formatCompact(Math.round(reviewThreshold))}
								description="Views/reach threshold"
								tone={lowReachCount > 0 ? "warning" : "default"}
							/>
						</div>
					</NovaCard>
				</NovaSection>
			</div>
		</NovaScreen>
	);
}

function PostRow({ post, reviewThreshold }: { post: TopPostRow; reviewThreshold: number }) {
	const score = discoveryScore(post);
	const needsReview = post.reach < reviewThreshold;
	return (
		<Link
			to={calendarPostPath(post.id, post.publishedAt)}
			className="grid gap-3 p-4 transition-colors hover:bg-muted/45 md:grid-cols-[88px_minmax(0,1fr)_auto]"
		>
			<div
				className={cn(
					"flex aspect-square size-[88px] items-center justify-center overflow-hidden rounded-md border border-border bg-muted",
					!post.mediaUrl && "p-3 text-muted-foreground",
				)}
			>
				{post.mediaUrl ? (
					<img src={post.mediaUrl} alt="" className="size-full object-cover" loading="lazy" decoding="async" />
				) : (
					<MessageCircle className="size-5" aria-hidden="true" />
				)}
			</div>
			<div className="min-w-0">
				<div className="mb-2 flex flex-wrap items-center gap-2">
					<Badge tone={post.platform === "instagram" ? "oxblood" : "secondary"}>
						<BrandLogo
							name={platformLogoName(post)}
							size="xs"
							monochrome
						/>
						{platformLabel(post)}
					</Badge>
					{needsReview ? <Badge tone="danger">Review</Badge> : null}
					<span className="text-sm text-muted-foreground">@{post.accountHandle}</span>
					<span className="text-sm text-muted-foreground">{formatDate(post.publishedAt)}</span>
				</div>
				<p className="line-clamp-2 text-sm leading-relaxed text-foreground">
					{post.caption || "Untitled post"}
				</p>
				<div className="mt-3 flex flex-wrap gap-2 text-sm text-muted-foreground">
					<span>{formatCompact(post.reach)} views/reach</span>
					<span>{formatCompact(post.likes)} likes</span>
					<span>{formatCompact(post.comments)} comments</span>
				</div>
			</div>
			<div className="flex min-w-[132px] flex-row gap-2 md:flex-col md:items-end md:justify-center">
				<NovaMiniStat
					className="min-w-[96px]"
					label="Discovery"
					value={formatCompact(score)}
					tone={score > 0 ? "primary" : "default"}
				/>
				<NovaMiniStat
					className="min-w-[96px]"
					label="Total"
					value={formatCompact(engagementTotal(post))}
				/>
			</div>
		</Link>
	);
}

function ActionPost({
	post,
	label,
	tone,
	icon,
	description,
	to,
	action,
}: {
	post: TopPostRow;
	label: string;
	tone: React.ComponentProps<typeof Badge>["tone"];
	icon: React.ReactNode;
	description: string;
	to: string;
	action: string;
}) {
	return (
		<NovaListRow
			leading={icon}
			title={post.caption || "Untitled post"}
			description={`${platformLabel(post)} · ${description}`}
			meta={<Badge tone={tone}>{label}</Badge>}
			action={
				<Button asChild variant="ghost" size="sm">
					<Link to={to}>
						{action}
						<ArrowUpRight data-icon="inline-end" aria-hidden="true" />
					</Link>
				</Button>
			}
			tone={label === "Review" ? "danger" : "default"}
		/>
	);
}

function ContentEmpty({
	title,
	description,
	action,
}: {
	title: string;
	description: string;
	action?: React.ReactNode;
}) {
	return (
		<NovaEmpty
			title={title}
			description={description}
			action={action}
			icon={<BarChart3 data-icon="inline-start" aria-hidden="true" />}
		/>
	);
}

function PostListSkeleton() {
	return (
		<div className="divide-y divide-border">
			{Array.from({ length: 5 }).map((_, index) => (
				<div key={index} className="grid gap-3 p-4 md:grid-cols-[88px_minmax(0,1fr)_132px]">
					<Skeleton className="size-[88px] rounded-md" />
					<div className="grid content-center gap-2">
						<Skeleton className="h-4 w-48" />
						<Skeleton className="h-4 w-full" />
						<Skeleton className="h-4 w-2/3" />
					</div>
					<div className="grid content-center gap-2">
						<Skeleton className="h-12 w-full" />
						<Skeleton className="h-12 w-full" />
					</div>
				</div>
			))}
		</div>
	);
}
