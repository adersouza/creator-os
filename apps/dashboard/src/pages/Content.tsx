import type React from "react";
import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import {
	ArrowUpRight,
	BarChart3,
	CalendarClock,
	Image as ImageIcon,
	MessageCircle,
	Search,
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
import { DataTable } from "@/components/ui/DataTable";
import { Input } from "@/components/ui/Input";
import { MotionReveal } from "@/components/ui/Motion";
import {
	NovaCard,
	NovaBentoGrid,
	NovaDataPanel,
	NovaEmpty,
	NovaHeader,
	NovaInset,
	NovaListRow,
	NovaMiniStat,
	NovaStat,
	NovaToolbar,
} from "@/components/ui/NovaPrimitives";
import { Separator } from "@/components/ui/Separator";
import { Sheet } from "@/components/ui/Sheet";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { VirtualizedList } from "@/components/ui/VirtualizedList";
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
type ContentStatusFilter = "all" | "signal" | "review" | "tracking";
type ContentSort = "newest" | "views" | "engagement" | "discovery";

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

const STATUS_FILTERS: Array<{ value: ContentStatusFilter; label: string }> = [
	{ value: "all", label: "All" },
	{ value: "signal", label: "Signal" },
	{ value: "review", label: "Review" },
	{ value: "tracking", label: "Tracking" },
];

const SORT_OPTIONS: Array<{ value: ContentSort; label: string }> = [
	{ value: "newest", label: "Newest" },
	{ value: "views", label: "Views" },
	{ value: "engagement", label: "Engagement" },
	{ value: "discovery", label: "Discovery" },
];

const CONTENT_STAT_CLASS =
	"h-full max-sm:[&_.nova-card-content]:min-h-[88px] max-sm:[&_.nova-card-content]:gap-1.5 max-sm:[&_.nova-stat-description]:hidden max-sm:[&_.nova-icon-box]:size-8 max-sm:[&_.nova-stat-label]:text-[10px] max-sm:[&_.nova-stat-value]:text-xl";
const CONTENT_TABLE_FRAME_CLASS = "max-h-[min(62vh,720px)] overflow-auto";
const CONTENT_MOBILE_LIST_CLASS = "h-[min(58vh,30rem)] min-h-[18rem] pr-1";

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

function engagementRate(post: TopPostRow) {
	if (post.reach <= 0) return null;
	return (engagementTotal(post) / post.reach) * 100;
}

function formatRate(value: number | null) {
	if (value === null) return "Pending";
	return `${value.toFixed(value >= 10 ? 0 : 1)}%`;
}

function contentStatus(post: TopPostRow, reviewThreshold: number): ContentStatusFilter {
	if (post.reach < reviewThreshold) return "review";
	if (discoveryScore(post) > 0) return "signal";
	return "tracking";
}

function contentStatusLabel(status: ContentStatusFilter) {
	if (status === "review") return "Review";
	if (status === "signal") return "Signal";
	if (status === "tracking") return "Tracking";
	return "All";
}

function contentStatusTone(status: ContentStatusFilter): React.ComponentProps<typeof Badge>["tone"] {
	if (status === "review") return "danger";
	if (status === "signal") return "outline";
	if (status === "tracking") return "secondary";
	return "secondary";
}

function reviewReason(post: TopPostRow, reviewThreshold: number) {
	if (post.reach < reviewThreshold) {
		return `${formatCompact(post.reach)} views/reach is below this window's ${formatCompact(Math.round(reviewThreshold))} review baseline.`;
	}
	if (discoveryScore(post) > 0) {
		return `${formatCompact(discoveryScore(post))} discovery actions make this a good follow-up candidate.`;
	}
	return "Tracking while more engagement data comes in.";
}

function filterPosts(
	posts: TopPostRow[],
	query: string,
	status: ContentStatusFilter,
	reviewThreshold: number,
) {
	const normalized = query.trim().toLowerCase();
	return posts.filter((post) => {
		const postStatus = contentStatus(post, reviewThreshold);
		if (status !== "all" && postStatus !== status) return false;
		if (!normalized) return true;
		return [
			post.caption,
			post.accountHandle,
			post.groupName,
			platformLabel(post),
		]
			.join(" ")
			.toLowerCase()
			.includes(normalized);
	});
}

function sortPosts(posts: TopPostRow[], sort: ContentSort) {
	const next = [...posts];
	if (sort === "views") return next.sort((a, b) => b.reach - a.reach);
	if (sort === "engagement") return next.sort((a, b) => engagementTotal(b) - engagementTotal(a));
	if (sort === "discovery") return next.sort((a, b) => discoveryScore(b) - discoveryScore(a));
	return next.sort((a, b) => new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime());
}

export function Content() {
	const scopedAccount = useAccountScopeStore((state) => state.scopedAccount);
	const { accountIds, groupId } = useSelectedGroupAccountIds(scopedAccount);
	const [windowFilter, setWindowFilter] = useState<WindowFilter>("30d");
	const [platform, setPlatform] = useState<PlatformFilter>("all");
	const [search, setSearch] = useState("");
	const [statusFilter, setStatusFilter] = useState<ContentStatusFilter>("all");
	const [sortBy, setSortBy] = useState<ContentSort>("newest");
	const [selectedPost, setSelectedPost] = useState<TopPostRow | null>(null);
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
	const filteredPosts = useMemo(
		() =>
			sortPosts(
				filterPosts(recentPosts, search, statusFilter, reviewThreshold),
				sortBy,
			),
		[recentPosts, reviewThreshold, search, sortBy, statusFilter],
	);
	const visibleReviewPosts = reviewPosts.slice(0, 3);
	const visibleWinningPosts = winningPosts.slice(0, visibleReviewPosts.length > 0 ? 1 : 3);
	const postColumns = useMemo<ColumnDef<TopPostRow>[]>(
		() => [
			{
				accessorKey: "caption",
				header: "Preview",
				cell: ({ row }) => {
					const post = row.original;
					return (
						<div className="flex min-w-[220px] items-center gap-3 sm:min-w-[280px]">
							<div
								className={cn(
									"flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-muted text-muted-foreground",
									!post.mediaUrl && "p-2",
								)}
							>
								{post.mediaUrl ? (
									<img
										src={post.mediaUrl}
										alt=""
										className="size-full object-cover"
										loading="lazy"
										decoding="async"
									/>
								) : (
									<MessageCircle className="size-4" aria-hidden="true" />
								)}
							</div>
							<div className="min-w-0">
								<div className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
									{post.caption || "Untitled post"}
								</div>
								<div className="mt-1 text-xs text-muted-foreground">
									{post.groupName}
								</div>
							</div>
						</div>
					);
				},
				meta: {
					headerClassName: "min-w-[260px] w-[300px]",
					cellClassName: "min-w-[260px] w-[300px]",
				},
			},
			{
				accessorKey: "publishedAt",
				header: "Published",
				cell: ({ row }) => formatDate(row.original.publishedAt),
				meta: {
					headerClassName: "w-[112px]",
					cellClassName: "w-[112px]",
				},
			},
			{
				accessorKey: "accountHandle",
				header: "Account",
				cell: ({ row }) => (
					<span className="inline-flex min-w-0 items-center gap-2 font-medium text-foreground">
						<BrandLogo name={platformLogoName(row.original)} size="xs" monochrome />
						<span className="truncate">@{row.original.accountHandle}</span>
					</span>
				),
				meta: {
					headerClassName: "w-[128px]",
					cellClassName: "w-[128px]",
				},
			},
			{
				accessorKey: "platform",
				header: "Platform",
				cell: ({ row }) => (
					<Badge tone={row.original.platform === "instagram" ? "oxblood" : "secondary"}>
						<BrandLogo name={platformLogoName(row.original)} size="xs" monochrome />
						{platformLabel(row.original)}
					</Badge>
				),
				meta: {
					headerClassName: "w-[108px]",
					cellClassName: "w-[108px]",
				},
			},
			{
				accessorKey: "reach",
				header: "Views / reach",
				cell: ({ row }) => formatCompact(row.original.reach),
				meta: {
					headerClassName: "w-[100px] text-right",
					cellClassName: "w-[100px] text-right tabular-nums",
				},
			},
			{
				id: "engagement",
				accessorFn: (post) => engagementTotal(post),
				header: "Engagements",
				cell: ({ row }) => formatCompact(engagementTotal(row.original)),
				meta: {
					headerClassName: "w-[104px] text-right",
					cellClassName: "w-[104px] text-right tabular-nums",
				},
			},
			{
				id: "status",
				accessorFn: (post) => contentStatus(post, reviewThreshold),
				header: "Status",
				cell: ({ row }) => {
					const status = contentStatus(row.original, reviewThreshold);
					return (
						<Badge tone={contentStatusTone(status)}>
							{contentStatusLabel(status)}
						</Badge>
					);
				},
				meta: {
					headerClassName: "w-[92px]",
					cellClassName: "w-[92px]",
				},
			},
			{
				id: "actions",
				header: "",
				cell: ({ row }) => (
					<div onClick={(event) => event.stopPropagation()}>
						<Button asChild variant="ghost" size="sm">
							<Link to={calendarPostPath(row.original.id, row.original.publishedAt)}>
								Open
								<ArrowUpRight data-icon="inline-end" aria-hidden="true" />
							</Link>
						</Button>
					</div>
				),
				meta: {
					headerClassName: "w-[76px]",
					cellClassName: "w-[76px]",
				},
			},
		],
		[reviewThreshold],
	);

	return (
		<NovaScreen width="wide" density="compact">
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

			<div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
				<NovaStat
					label="Published posts"
					value={isLoading ? "..." : posts.length.toLocaleString()}
					description="Synced posts in this window"
					icon={<CalendarClock aria-hidden />}
					loading={isLoading}
					variant="compact"
					className={CONTENT_STAT_CLASS}
				/>
				<NovaStat
					label="Views / reach"
					value={formatCompact(totalReach)}
					description="Uses synced views when IG reach is unavailable"
					icon={<BarChart3 aria-hidden />}
					loading={isLoading}
					variant="compact"
					className={CONTENT_STAT_CLASS}
				/>
				<NovaStat
					label="Discovery actions"
					value={formatCompact(totalDiscovery)}
					description="Sends + saves, or replies + reposts"
					icon={<Send aria-hidden />}
					loading={isLoading}
					variant="compact"
					className={CONTENT_STAT_CLASS}
				/>
				<NovaStat
					label="Needs review"
					value={lowReachCount.toLocaleString()}
					description="Posts below this window's distribution baseline"
					status={lowReachCount > 0 ? "watch" : "clear"}
					loading={isLoading}
					variant="compact"
					className={CONTENT_STAT_CLASS}
				/>
			</div>

			<MotionReveal delay={0.04}>
				<NovaCard
					title="Recent posts"
					description="Chronological view of what actually went out and how it is performing."
					action={<Badge tone="outline">{filteredPosts.length} shown</Badge>}
					contentClassName="p-0"
					className="w-full"
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
					) : filteredPosts.length === 0 ? (
						<div className="grid gap-3 p-3 sm:p-4">
							<ContentTableToolbar
								search={search}
								onSearchChange={setSearch}
								statusFilter={statusFilter}
								onStatusFilterChange={setStatusFilter}
								sortBy={sortBy}
								onSortChange={setSortBy}
							/>
							<ContentEmpty
								title="No posts match these filters"
								description="Clear the search or switch status filters to inspect more posted content."
							/>
						</div>
					) : (
						<>
							<div className="grid gap-3 p-3 md:hidden">
								<ContentTableToolbar
									search={search}
									onSearchChange={setSearch}
									statusFilter={statusFilter}
									onStatusFilterChange={setStatusFilter}
									sortBy={sortBy}
									onSortChange={setSortBy}
								/>
								<div className={CONTENT_MOBILE_LIST_CLASS}>
									<MobilePostList
										posts={filteredPosts}
										reviewThreshold={reviewThreshold}
										onSelectPost={setSelectedPost}
									/>
								</div>
								<ContentTableFooter shown={filteredPosts.length} total={recentPosts.length} />
							</div>
							<div className="hidden md:block">
								<DataTable
									data={filteredPosts}
									columns={postColumns}
									ariaLabel="Posted content performance table"
									toolbar={
										<ContentTableToolbar
											search={search}
											onSearchChange={setSearch}
											statusFilter={statusFilter}
											onStatusFilterChange={setStatusFilter}
											sortBy={sortBy}
											onSortChange={setSortBy}
										/>
									}
									footer={<ContentTableFooter shown={filteredPosts.length} total={recentPosts.length} />}
									onRowClick={setSelectedPost}
									className="min-w-0 p-3 sm:p-4"
									frameClassName={CONTENT_TABLE_FRAME_CLASS}
									tableClassName="min-w-[820px] xl:min-w-full"
								/>
							</div>
						</>
					)}
				</NovaCard>
			</MotionReveal>

			<NovaBentoGrid gap="compact" className="content-followup-grid grid-cols-1 lg:grid-cols-3">
				<NovaCard
					title="Best current signal"
					description="The post with the strongest discovery-weighted response."
					className="h-full"
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
							<div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
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
					title="Next actions"
					description="Posts to inspect, repeat, or turn into a follow-up."
					action={
						<Badge tone={lowReachCount > 0 ? "danger" : "outline"}>
							{lowReachCount > 0 ? `${lowReachCount} review` : "Clear"}
						</Badge>
					}
					className="h-full"
				>
					{isLoading ? (
						<div className="grid gap-3">
							<Skeleton className="h-16 w-full" />
							<Skeleton className="h-16 w-full" />
						</div>
					) : reviewPosts.length > 0 || winningPosts.length > 0 ? (
						<div className="flex flex-col gap-3">
							{visibleReviewPosts.map((post) => (
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
							{visibleReviewPosts.length > 0 && visibleWinningPosts.length > 0 ? <Separator /> : null}
							{visibleWinningPosts.map((post) => (
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
							{reviewPosts.length > visibleReviewPosts.length ? (
								<div className="rounded-lg border border-border bg-muted/35 px-3 py-2 text-sm text-muted-foreground">
									{reviewPosts.length - visibleReviewPosts.length} more posts are listed in Recent posts.
								</div>
							) : null}
						</div>
					) : (
						<ContentEmpty
							title="No operator actions"
							description="Published content will create review and follow-up actions here."
						/>
					)}
				</NovaCard>

				<NovaCard
					title="Content mix"
					description="A compact read on loaded posts in this scope."
					className="h-full"
				>
					<div className="grid gap-2">
						{platformBreakdown.map((item) => (
							<NovaMiniStat
								key={item.label}
								label={item.label}
								value={item.count.toLocaleString()}
								description="Published posts"
								size="compact"
							/>
						))}
						<Separator />
						<NovaMiniStat
							label="Total engagement"
							value={formatCompact(totalEngagement)}
							description="Likes + comments + shares/saves"
							tone="success"
							size="compact"
						/>
						<NovaMiniStat
							label="Review baseline"
							value={formatCompact(Math.round(reviewThreshold))}
							description="Views/reach threshold"
							tone={lowReachCount > 0 ? "warning" : "default"}
							size="compact"
						/>
					</div>
				</NovaCard>
			</NovaBentoGrid>
			<PostDetailSheet
				post={selectedPost}
				reviewThreshold={reviewThreshold}
				onClose={() => setSelectedPost(null)}
			/>
		</NovaScreen>
	);
}

function ContentTableToolbar({
	search,
	onSearchChange,
	statusFilter,
	onStatusFilterChange,
	sortBy,
	onSortChange,
}: {
	search: string;
	onSearchChange: (value: string) => void;
	statusFilter: ContentStatusFilter;
	onStatusFilterChange: (value: ContentStatusFilter) => void;
	sortBy: ContentSort;
	onSortChange: (value: ContentSort) => void;
}) {
	return (
		<div className="flex min-w-0 max-w-full flex-col gap-3 rounded-lg border border-border bg-muted/35 p-3 md:flex-row md:items-center md:justify-between">
			<div className="flex min-w-0 flex-1 flex-col gap-2 lg:flex-row lg:items-center">
				<Input
					value={search}
					onChange={(event) => onSearchChange(event.target.value)}
					placeholder="Search caption, account, group, or platform"
					leadingIcon={<Search className="size-4" aria-hidden="true" />}
					aria-label="Search posted content"
					className="lg:max-w-[420px]"
				/>
				<Tabs value={statusFilter} onValueChange={(value) => onStatusFilterChange(value as ContentStatusFilter)}>
					<TabsList
						aria-label="Filter posts by status"
						className="w-full max-w-full overflow-x-auto rounded-lg md:w-max md:rounded-full"
					>
						{STATUS_FILTERS.map((option) => (
							<TabsTrigger key={option.value} value={option.value} className="shrink-0">
								{option.label}
							</TabsTrigger>
						))}
					</TabsList>
				</Tabs>
			</div>
			<Tabs value={sortBy} onValueChange={(value) => onSortChange(value as ContentSort)}>
				<TabsList
					aria-label="Sort posts"
					className="!grid w-full max-w-none grid-cols-2 gap-1 rounded-lg md:!inline-flex md:w-max md:gap-0 md:rounded-full"
				>
					{SORT_OPTIONS.map((option) => (
						<TabsTrigger key={option.value} value={option.value} className="w-full px-3 md:w-auto md:px-4">
							{option.label}
						</TabsTrigger>
					))}
				</TabsList>
			</Tabs>
		</div>
	);
}

function ContentTableFooter({ shown, total }: { shown: number; total: number }) {
	return (
		<div className="flex min-w-0 flex-col gap-2 rounded-lg border border-border bg-muted/35 px-3 py-2.5 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:gap-3">
			<span>
				Showing {shown.toLocaleString()} of {total.toLocaleString()} posts
			</span>
			<Button asChild variant="outline" size="sm">
				<Link to="/analytics?tab=posts">
					Investigate in Analytics
					<ArrowUpRight data-icon="inline-end" aria-hidden="true" />
				</Link>
			</Button>
		</div>
	);
}

function MobilePostList({
	posts,
	reviewThreshold,
	onSelectPost,
}: {
	posts: TopPostRow[];
	reviewThreshold: number;
	onSelectPost: (post: TopPostRow) => void;
}) {
	return (
		<VirtualizedList
			items={posts}
			estimateSize={96}
			height="100%"
			getItemKey={(post) => post.id}
			ariaLabel="Recent posts"
			className="rounded-none border-0 bg-transparent"
			contentClassName="pb-2"
			renderItem={(post) => {
				const status = contentStatus(post, reviewThreshold);
				const activate = () => onSelectPost(post);
				return (
					<div className="pb-3">
						<NovaListRow
							role="button"
							tabIndex={0}
							onClick={activate}
							onKeyDown={(event) => {
								if (event.key === "Enter" || event.key === " ") {
									event.preventDefault();
									activate();
								}
							}}
							leading={
								post.mediaUrl ? (
									<img
										src={post.mediaUrl}
										alt=""
										className="size-full object-cover"
										loading="lazy"
										decoding="async"
									/>
								) : (
									<MessageCircle aria-hidden="true" />
								)
							}
							title={post.caption || "Untitled post"}
							description={`${platformLabel(post)} · @${post.accountHandle} · ${formatDate(post.publishedAt)}`}
							meta={<Badge tone={contentStatusTone(status)}>{contentStatusLabel(status)}</Badge>}
							className="cursor-pointer bg-card hover:bg-muted/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)]"
						/>
					</div>
				);
			}}
		/>
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

function PostDetailSheet({
	post,
	reviewThreshold,
	onClose,
}: {
	post: TopPostRow | null;
	reviewThreshold: number;
	onClose: () => void;
}) {
	const status = post ? contentStatus(post, reviewThreshold) : "all";
	const calendarPath = post ? calendarPostPath(post.id, post.publishedAt) : "/calendar";
	return (
		<Sheet
			open={Boolean(post)}
			onClose={onClose}
			title={post ? "Post inspection" : "Post inspection"}
			description={post ? `${platformLabel(post)} · @${post.accountHandle}` : undefined}
			widthClass="w-full sm:w-[640px]"
			ariaLabel="Post inspection"
			panelClassName="bg-card"
		>
			{post ? (
				<MotionReveal className="flex flex-col gap-4 p-4 sm:p-5">
					<div className="overflow-hidden rounded-xl border border-border bg-muted/35">
						<div className="flex aspect-video items-center justify-center bg-muted text-muted-foreground">
							{post.mediaUrl ? (
								<img
									src={post.mediaUrl}
									alt=""
									className="size-full object-cover"
									loading="lazy"
									decoding="async"
								/>
							) : (
								<div className="flex flex-col items-center gap-2 text-sm">
									<MessageCircle className="size-5" aria-hidden="true" />
									Text post
								</div>
							)}
						</div>
						<div className="flex flex-col gap-3 p-4">
							<div className="flex flex-wrap items-center gap-2">
								<Badge tone={post.platform === "instagram" ? "oxblood" : "secondary"}>
									<BrandLogo name={platformLogoName(post)} size="xs" monochrome />
									{platformLabel(post)}
								</Badge>
								<Badge tone={status === "review" ? "danger" : status === "signal" ? "outline" : "secondary"}>
									{contentStatusLabel(status)}
								</Badge>
								<span className="text-sm text-muted-foreground">{formatDate(post.publishedAt)}</span>
							</div>
							<p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
								{post.caption || "Untitled post"}
							</p>
						</div>
					</div>

					<NovaDataPanel
						title="Performance"
						description="Synced metrics for this post in the selected content window."
						toolbar={<Badge tone={status === "review" ? "danger" : status === "signal" ? "outline" : "secondary"}>{contentStatusLabel(status)}</Badge>}
						contentClassName="pt-0"
					>
						<div className="grid grid-cols-2 gap-2">
							<NovaMiniStat label="Views / reach" value={formatCompact(post.reach)} />
							<NovaMiniStat label="Engagements" value={formatCompact(engagementTotal(post))} />
							<NovaMiniStat label="Engagement rate" value={formatRate(engagementRate(post))} />
							<NovaMiniStat label="Discovery" value={formatCompact(discoveryScore(post))} tone="primary" />
							<NovaMiniStat label="Saves" value={formatCompact(post.saves)} />
							<NovaMiniStat label="Shares / sends" value={formatCompact(post.sends)} />
							<NovaMiniStat label="Replies / comments" value={formatCompact(post.comments)} />
							<NovaMiniStat label="Likes" value={formatCompact(post.likes)} />
						</div>
					</NovaDataPanel>

					<NovaCard title="Context" description="Operational read for this post.">
						<div className="grid gap-3 text-sm">
							<DetailRow label="Account" value={`@${post.accountHandle}`} />
							<DetailRow label="Group" value={post.groupName || "Ungrouped"} />
							<DetailRow label="Published" value={formatDate(post.publishedAt)} />
							<Separator />
							<NovaInset tone={status === "review" ? "danger" : status === "signal" ? "primary" : "default"}>
								<div className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
									Review reason
								</div>
								<p className="mt-1 leading-relaxed text-foreground">
									{reviewReason(post, reviewThreshold)}
								</p>
							</NovaInset>
						</div>
					</NovaCard>

					<div className="flex flex-col gap-2 sm:flex-row">
						<Button asChild className="sm:flex-1">
							<Link to={calendarPath}>
								Open in calendar
								<ArrowUpRight data-icon="inline-end" aria-hidden="true" />
							</Link>
						</Button>
						<Button asChild variant="outline" className="sm:flex-1">
							<Link to="/content-library">Open content library</Link>
						</Button>
						<Button asChild variant="outline" className="sm:flex-1">
							<Link to="/composer">Compose follow-up</Link>
						</Button>
					</div>
				</MotionReveal>
			) : null}
		</Sheet>
	);
}

function DetailRow({ label, value }: { label: string; value: string }) {
	return (
		<div className="flex items-center justify-between gap-4">
			<span className="text-muted-foreground">{label}</span>
			<span className="min-w-0 truncate text-right font-medium text-foreground">{value}</span>
		</div>
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
