import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import listPlugin from "@fullcalendar/list";
import interactionPlugin from "@fullcalendar/interaction";
import type {
	DateSelectArg,
	DatesSetArg,
	EventClickArg,
	EventContentArg,
	EventDropArg,
	EventInput,
} from "@fullcalendar/core";
import {
	CalendarDays,
	ChevronLeft,
	ChevronRight,
	Copy,
	ExternalLink,
	Plus,
	RefreshCw,
	Trash2,
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { AccountScopeChip } from "@/components/ui/AccountScopeChip";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
	NovaCard,
	NovaBentoGrid,
	NovaDataPanel,
	NovaEmpty,
	NovaHeader,
	NovaToolbar,
} from "@/components/ui/NovaPrimitives";
import { Select } from "@/components/ui/Select";
import { Separator } from "@/components/ui/Separator";
import { Sheet } from "@/components/ui/Sheet";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup";
import {
	useCalendarPosts,
	type CalendarPlatform,
	type CalendarPost,
	type CalendarStatus,
} from "@/hooks/useCalendarPosts";
import { PortfolioMatrix } from "@/components/calendar/PortfolioMatrix";
import { queryClient } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";
import { appToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { deletePost, duplicatePost, updatePost } from "@/services/api/posts";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { haptics } from "@/utils/haptics";

type CalendarView = "week" | "month" | "agenda" | "portfolio";
type PlatformFilter = "all" | CalendarPlatform;

const FULL_CALENDAR_VIEW: Record<Exclude<CalendarView, "portfolio">, string> = {
	week: "timeGridWeek",
	month: "dayGridMonth",
	agenda: "listWeek",
};

const STATUS_TONE: Record<CalendarStatus, "secondary" | "outline" | "danger" | "oxblood"> = {
	draft: "outline",
	scheduled: "oxblood",
	published: "secondary",
	failed: "danger",
	review: "outline",
};

const STATUS_LABEL: Record<CalendarStatus, string> = {
	draft: "Draft",
	scheduled: "Scheduled",
	published: "Published",
	failed: "Failed",
	review: "Review",
};

function parseView(value: string | null): CalendarView {
	if (value === "portfolio") return "portfolio";
	if (value === "month" || value === "agenda" || value === "list") return value === "list" ? "agenda" : value;
	return "week";
}

function parseDate(value: string | null): Date {
	if (!value) return new Date();
	const parsed = new Date(`${value}T12:00:00`);
	return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}

function sameDay(a: Date, b: Date) {
	return (
		a.getFullYear() === b.getFullYear() &&
		a.getMonth() === b.getMonth() &&
		a.getDate() === b.getDate()
	);
}

function startOfWeek(date: Date) {
	const next = new Date(date);
	const day = next.getDay();
	const diff = day === 0 ? -6 : 1 - day;
	next.setDate(next.getDate() + diff);
	next.setHours(0, 0, 0, 0);
	return next;
}

function formatDateParam(date: Date) {
	const yyyy = date.getFullYear();
	const mm = String(date.getMonth() + 1).padStart(2, "0");
	const dd = String(date.getDate()).padStart(2, "0");
	return `${yyyy}-${mm}-${dd}`;
}

function formatWeekStartForUrl(date: Date) {
	return formatDateParam(date);
}

function formatTimeParam(date: Date) {
	const hh = String(date.getHours()).padStart(2, "0");
	const mm = String(date.getMinutes()).padStart(2, "0");
	return `${hh}:${mm}`;
}

function formatRangeLabel(date: Date, view: CalendarView) {
	return new Intl.DateTimeFormat(undefined, {
		month: "short",
		day: view === "month" ? undefined : "numeric",
		year: "numeric",
	}).format(date);
}

function postStart(post: CalendarPost) {
	return post.scheduledFor ?? post.publishedAt ?? post.createdAt ?? new Date().toISOString();
}

function postTitle(post: CalendarPost) {
	const content = post.content?.trim();
	if (!content) return "Untitled post";
	const firstLine = content.split(/\n+/)[0]?.trim() || "Untitled post";
	return firstLine.length > 78 ? `${firstLine.slice(0, 75)}...` : firstLine;
}

function metricValue(...values: Array<number | null | undefined>): number {
	return values.reduce<number>((sum, value) => sum + (typeof value === "number" ? value : 0), 0);
}

function formatNumber(value: number) {
	return new Intl.NumberFormat(undefined, { notation: value > 9999 ? "compact" : "standard" }).format(value);
}

function platformLabel(platform: CalendarPlatform) {
	return platform === "instagram" ? "Instagram" : "Threads";
}

function eventColor(post: CalendarPost) {
	if (post.status === "failed") return "var(--color-danger)";
	if (post.status === "published") return "var(--color-chart-2)";
	return "var(--color-oxblood)";
}

export function Calendar() {
	const navigate = useNavigate();
	const [searchParams, setSearchParams] = useSearchParams();
	const calendarRef = useRef<FullCalendar | null>(null);
	const scopedAccount = useAccountScopeStore((state) => state.scopedAccount);
	const clearScope = useAccountScopeStore((state) => state.clearScope);
	const [anchorDate, setAnchorDate] = useState(() => parseDate(searchParams.get("date")));
	const [viewMode, setViewMode] = useState<CalendarView>(() => parseView(searchParams.get("view")));
	const [platformFilter, setPlatformFilter] = useState<PlatformFilter>(() => {
		const value = searchParams.get("platform");
		return value === "threads" || value === "instagram" ? value : "all";
	});
	const [groupFilter, setGroupFilter] = useState(() => searchParams.get("group") ?? "all");
	const [selectedPost, setSelectedPost] = useState<CalendarPost | null>(null);
	const [upcomingOpen, setUpcomingOpen] = useState(false);
	const [draggingPostId, setDraggingPostId] = useState<string | null>(null);
	const accountId = searchParams.get("accountId");
	const accountHandle = searchParams.get("accountHandle");

	const weekStart = useMemo(() => startOfWeek(anchorDate), [anchorDate]);
	const calendarState = useCalendarPosts(weekStart, viewMode === "month" ? 6 : 1);

	useEffect(() => {
		const next = new URLSearchParams(searchParams);
		const nextDate = formatDateParam(anchorDate);
		let changed = false;

		if (next.get("date") !== nextDate) {
			next.set("date", nextDate);
			changed = true;
		}
		if (next.get("view") !== viewMode) {
			next.set("view", viewMode);
			changed = true;
		}
		if (platformFilter === "all") {
			if (next.has("platform")) {
				next.delete("platform");
				changed = true;
			}
		} else if (next.get("platform") !== platformFilter) {
			next.set("platform", platformFilter);
			changed = true;
		}
		if (groupFilter === "all") {
			if (next.has("group")) {
				next.delete("group");
				changed = true;
			}
		} else if (next.get("group") !== groupFilter) {
			next.set("group", groupFilter);
			changed = true;
		}

		if (changed) setSearchParams(next, { replace: true });
	}, [anchorDate, groupFilter, platformFilter, searchParams, setSearchParams, viewMode]);

	useEffect(() => {
		if (viewMode === "portfolio") return;
		const api = calendarRef.current?.getApi();
		if (!api) return;
		if (api.view.type !== FULL_CALENDAR_VIEW[viewMode]) {
			api.changeView(FULL_CALENDAR_VIEW[viewMode]);
		}
	}, [viewMode]);

	const filteredPosts = useMemo(() => {
		return calendarState.posts.filter((post) => {
			if (scopedAccount) {
				const accountMatches =
					post.account.id === scopedAccount.id ||
					post.account.handle === scopedAccount.handle ||
					`@${post.account.handle}` === scopedAccount.handle;
				if (!accountMatches || post.account.platform !== scopedAccount.platform) return false;
			}
			if (platformFilter !== "all" && post.account.platform !== platformFilter) return false;
			if (groupFilter !== "all" && post.account.groupId !== groupFilter) return false;
			return true;
		});
	}, [calendarState.posts, groupFilter, platformFilter, scopedAccount]);

	const events = useMemo<EventInput[]>(() => {
		return filteredPosts.map((post) => ({
			id: post.id,
			title: postTitle(post),
			start: postStart(post),
			allDay: false,
			editable: post.status !== "published",
			backgroundColor: "transparent",
			borderColor: "transparent",
			textColor: "var(--color-foreground)",
			classNames: [`nova-calendar-event-shell`, `is-${post.status}`],
			extendedProps: { post },
		}));
	}, [filteredPosts]);

	const calendarEventMaxStack = viewMode === "week" ? 2 : 3;
	const calendarShellClassName = cn(
		"nova-calendar-shell overflow-auto",
		draggingPostId && "is-dragging-event",
		viewMode === "week" &&
			"min-h-[860px] sm:min-h-[1020px]",
		viewMode === "month" &&
			"min-h-[660px] sm:min-h-[820px]",
		viewMode === "agenda" &&
			"max-h-[min(76vh,900px)] min-h-[560px] sm:min-h-[640px]",
	);
	const calendarCanvasClassName =
		viewMode === "week"
			? "min-w-[1120px] min-[1600px]:min-w-[1360px] min-[1920px]:min-w-[1480px]"
			: "min-w-0";

	const metrics = useMemo(() => {
		const scheduled = filteredPosts.filter((post) => post.status === "scheduled").length;
		const published = filteredPosts.filter((post) => post.status === "published").length;
		const failed = filteredPosts.filter((post) => post.status === "failed").length;
		const reach = filteredPosts.reduce(
			(sum, post) => sum + metricValue(post.viewsCount, post.igViews, post.igReach),
			0,
		);
		return { scheduled, published, failed, reach };
	}, [filteredPosts]);
	const attentionCount = calendarState.gapsCount + metrics.failed;

	const groupOptions = useMemo(() => {
		const all = [{ value: "all", label: "All groups" }];
		return all.concat(calendarState.groups.map((group) => ({ value: group.id, label: group.name })));
	}, [calendarState.groups]);

	const openComposerForDate = useCallback(
		(date: Date) => {
			haptics.selection();
			const next = new URLSearchParams();
			next.set("date", formatDateParam(date));
			next.set("time", formatTimeParam(date));
			if (platformFilter !== "all") next.set("platform", platformFilter);
			navigate(`/composer?${next.toString()}`);
		},
		[navigate, platformFilter],
	);

	const openComposerForAccountDate = useCallback(
		(nextAccountId: string, dateKey: string) => {
			haptics.selection();
			const next = new URLSearchParams();
			next.set("date", dateKey);
			next.set("accountId", nextAccountId);
			if (platformFilter !== "all") next.set("platform", platformFilter);
			navigate(`/composer?${next.toString()}`);
		},
		[navigate, platformFilter],
	);

	const refreshCalendar = useCallback(() => {
		void queryClient.invalidateQueries({ queryKey: queryKeys.calendar.all });
		appToast.info("Refreshing calendar");
	}, []);

	const changeView = useCallback((nextView: CalendarView) => {
		setViewMode(nextView);
		if (nextView === "portfolio") return;
		calendarRef.current?.getApi().changeView(FULL_CALENDAR_VIEW[nextView]);
	}, []);

	const moveCalendar = useCallback((direction: "prev" | "next" | "today") => {
		const api = calendarRef.current?.getApi();
		if (!api) return;
		if (direction === "prev") api.prev();
		if (direction === "next") api.next();
		if (direction === "today") api.today();
	}, []);

	const handleDatesSet = useCallback((info: DatesSetArg) => {
		const next = info.view.currentStart ?? info.start;
		setAnchorDate((prev) => (sameDay(prev, next) ? prev : new Date(next)));
	}, []);

	const handleSelect = useCallback(
		(info: DateSelectArg) => {
			openComposerForDate(info.start);
		},
		[openComposerForDate],
	);

	const handleEventClick = useCallback((info: EventClickArg) => {
		const post = info.event.extendedProps.post as CalendarPost | undefined;
		if (post) setSelectedPost(post);
	}, []);

	const handleEventDrop = useCallback(async (info: EventDropArg) => {
		const post = info.event.extendedProps.post as CalendarPost | undefined;
		const nextStart = info.event.start;
		setDraggingPostId(null);
		if (!post || !nextStart) {
			info.revert();
			return;
		}
		try {
			await updatePost(post.id, {
				scheduledDate: nextStart.toISOString(),
				status: post.status === "draft" || post.status === "review" ? "scheduled" : post.status,
			});
			await queryClient.invalidateQueries({ queryKey: queryKeys.calendar.all });
			haptics.success();
			appToast.success("Post rescheduled");
		} catch (error) {
			void error;
			info.revert();
			haptics.error();
			appToast.error("Could not reschedule that post");
		}
	}, []);

	const handleDuplicate = useCallback(async (post: CalendarPost) => {
		try {
			await duplicatePost(post.id);
			await queryClient.invalidateQueries({ queryKey: queryKeys.calendar.all });
			appToast.success("Post duplicated");
		} catch (error) {
			void error;
			appToast.error("Could not duplicate that post");
		}
	}, []);

	const handleDelete = useCallback(async (post: CalendarPost) => {
		try {
			await deletePost(post.id);
			setSelectedPost(null);
			await queryClient.invalidateQueries({ queryKey: queryKeys.calendar.all });
			appToast.success("Post deleted");
		} catch (error) {
			void error;
			appToast.error("Could not delete that post");
		}
	}, []);

	const renderEventContent = useCallback((info: EventContentArg) => {
		const post = info.event.extendedProps.post as CalendarPost | undefined;
		if (!post) return <span>{info.event.title}</span>;
		const platformShort = post.account.platform === "instagram" ? "IG" : "TH";
		return (
			<div className="nova-calendar-event" style={{ "--event-accent": eventColor(post) } as React.CSSProperties}>
				<div className="nova-calendar-event__meta">
					<span className="size-1.5 shrink-0 rounded-full bg-[var(--event-accent)]" />
					<span className="nova-calendar-event__time">{info.timeText}</span>
					<span className="nova-calendar-event__platform" title={platformLabel(post.account.platform)}>
						{platformShort}
					</span>
				</div>
				<div className="nova-calendar-event__title">{info.event.title}</div>
				<div className="nova-calendar-event__account">@{post.account.handle}</div>
			</div>
		);
	}, []);

	return (
		<NovaScreen
			width="full"
			density="compact"
			className="calendar-page calendar-page--nova px-3 md:px-5 xl:px-6"
		>
			<NovaHeader
				variant="compact"
				eyebrow="Calendar"
				title="Publishing schedule"
				description="Plan, inspect, and move scheduled content across Threads and Instagram."
				meta={formatRangeLabel(anchorDate, viewMode)}
				actions={
					<NovaToolbar>
						<Button variant="outline" size="sm" onClick={refreshCalendar}>
							<RefreshCw data-icon="inline-start" aria-hidden="true" />
							Refresh
						</Button>
						<Button variant="outline" size="sm" onClick={() => setUpcomingOpen(true)} className="min-[1920px]:hidden">
							<CalendarDays data-icon="inline-start" aria-hidden="true" />
							Next posts
						</Button>
						<Button size="sm" onClick={() => openComposerForDate(new Date())}>
							<Plus data-icon="inline-start" aria-hidden="true" />
							New post
						</Button>
					</NovaToolbar>
				}
				filters={
					<>
						{scopedAccount ? (
							<AccountScopeChip
								handle={scopedAccount.handle}
								color={scopedAccount.platform === "instagram" ? "var(--color-primary)" : "var(--color-oxblood)"}
								onClear={clearScope}
							/>
						) : (
							<AccountScopeChip mode="fleet" count={calendarState.posts.length} />
						)}
						<ToggleGroup
							type="single"
							value={viewMode}
							onValueChange={(value) => {
								if (value) changeView(value as CalendarView);
							}}
							aria-label="Calendar view"
						>
							<ToggleGroupItem value="week">Week</ToggleGroupItem>
							<ToggleGroupItem value="month">Month</ToggleGroupItem>
							<ToggleGroupItem value="agenda">Agenda</ToggleGroupItem>
							<ToggleGroupItem value="portfolio">Portfolio</ToggleGroupItem>
						</ToggleGroup>
						<ToggleGroup
							type="single"
							value={platformFilter}
							onValueChange={(value) => {
								if (value) setPlatformFilter(value as PlatformFilter);
							}}
							aria-label="Platform filter"
						>
							<ToggleGroupItem value="all">All</ToggleGroupItem>
							<ToggleGroupItem value="threads">Threads</ToggleGroupItem>
							<ToggleGroupItem value="instagram">Instagram</ToggleGroupItem>
						</ToggleGroup>
						<Select
							value={groupFilter}
							onChange={(event) => setGroupFilter(event.target.value)}
							options={groupOptions}
							aria-label="Group filter"
							sizeVariant="sm"
							className="w-full sm:w-[180px]"
						/>
					</>
				}
			>
				<div className="hidden min-w-0 flex-wrap items-center gap-2 md:flex">
					<Badge tone="outline">{metrics.scheduled} scheduled</Badge>
					<Badge tone="outline">{metrics.published} published</Badge>
					<Badge tone="outline">{formatNumber(metrics.reach)} reach</Badge>
					<Badge tone={attentionCount > 0 ? "danger" : "secondary"}>
						{attentionCount} need attention
					</Badge>
				</div>
			</NovaHeader>

			{viewMode === 'portfolio' ? (
				<PortfolioMatrix
					capacityStart={formatWeekStartForUrl(weekStart)}
					groupFilter={groupFilter}
					platformFilter={platformFilter}
					scopedAccount={scopedAccount}
					accountId={accountId}
					accountHandle={accountHandle}
					onComposeForAccountDate={openComposerForAccountDate}
				/>
			) : (
			<div className="grid min-w-0 gap-5 md:gap-6 min-[1920px]:grid-cols-[minmax(0,1fr)_360px]">
				<NovaDataPanel
					title="Calendar"
					description="Drag unpublished posts to reschedule. Click empty time to compose."
					loading={calendarState.isLoading}
					contentClassName="px-2 pb-2 pt-0 sm:px-3 sm:pb-3 md:px-4 md:pb-4"
					toolbar={
						<NovaToolbar className="gap-1">
							<Button variant="outline" size="icon" aria-label="Previous range" onClick={() => moveCalendar("prev")}>
								<ChevronLeft data-icon aria-hidden="true" />
							</Button>
							<Button variant="outline" size="sm" onClick={() => moveCalendar("today")}>
								Today
							</Button>
							<Button variant="outline" size="icon" aria-label="Next range" onClick={() => moveCalendar("next")}>
								<ChevronRight data-icon aria-hidden="true" />
							</Button>
						</NovaToolbar>
					}
				>
					{calendarState.hasError ? (
						<NovaEmpty
							title="Calendar could not load"
							description="Refresh the schedule or try again after the API recovers."
						/>
					) : (
						<>
							<div className="mb-2 rounded-lg border border-border bg-muted/45 px-3 py-2 text-xs text-muted-foreground md:hidden">
								<span className="font-medium text-foreground">{metrics.scheduled} scheduled</span>
								<span> · {metrics.published} published · {attentionCount} to review</span>
							</div>
							{draggingPostId ? (
								<div className="mb-2 rounded-lg border border-primary/25 bg-primary/10 px-3 py-2 text-xs font-medium text-primary">
									Drop on a new time to reschedule.
								</div>
							) : null}
							<div className={calendarShellClassName}>
							{viewMode === "week" ? (
								<div className="sticky left-0 top-0 z-10 mb-2 rounded-lg border border-border bg-card/95 px-3 py-2 text-xs text-muted-foreground shadow-sm backdrop-blur md:hidden">
									Swipe the schedule horizontally to inspect the full week.
								</div>
							) : null}
							<div className={calendarCanvasClassName}>
								<FullCalendar
								ref={calendarRef}
								plugins={[dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin]}
								initialView={FULL_CALENDAR_VIEW[viewMode]}
								initialDate={anchorDate}
								firstDay={1}
								headerToolbar={false}
								nowIndicator
								editable
								selectable
								selectMirror
								allDaySlot={false}
								dayMaxEvents={3}
								eventMaxStack={calendarEventMaxStack}
								eventMinHeight={56}
								slotEventOverlap={false}
								slotMinTime="05:00:00"
								slotMaxTime="23:00:00"
								slotDuration="01:00:00"
								slotLabelInterval="01:00:00"
								slotLabelFormat={{
									hour: "numeric",
									meridiem: "short",
								}}
								snapDuration="00:30:00"
								height="auto"
								dayHeaderFormat={{
									weekday: "short",
									day: "numeric",
								}}
								events={events}
								eventContent={renderEventContent}
								eventClick={handleEventClick}
								eventDragStart={(info) => setDraggingPostId(info.event.id)}
								eventDragStop={() => setDraggingPostId(null)}
								eventDrop={handleEventDrop}
								select={handleSelect}
								dateClick={(info) => openComposerForDate(info.date)}
								datesSet={handleDatesSet}
								eventTimeFormat={{
									hour: "numeric",
									minute: "2-digit",
									meridiem: "short",
								}}
								/>
							</div>
						</div>
						</>
					)}
				</NovaDataPanel>

				<NovaBentoGrid className="hidden min-[1920px]:grid">
					<UpcomingPanel posts={filteredPosts} onSelect={setSelectedPost} />
				</NovaBentoGrid>
			</div>
			)}

			<Sheet
				open={upcomingOpen}
				onClose={() => setUpcomingOpen(false)}
				title="Next posts"
				description="Upcoming scheduled content"
				widthClass="w-full sm:w-[440px]"
			>
				<div className="p-4">
					<UpcomingPanel
						posts={filteredPosts}
						onSelect={(post) => {
							setSelectedPost(post);
							setUpcomingOpen(false);
						}}
					/>
				</div>
			</Sheet>

			<PostDetailSheet
				post={selectedPost}
				onClose={() => setSelectedPost(null)}
				onDuplicate={handleDuplicate}
				onDelete={handleDelete}
				onOpenComposer={(post) => openComposerForDate(new Date(postStart(post)))}
			/>
		</NovaScreen>
	);
}

function UpcomingPanel({
	posts,
	onSelect,
}: {
	posts: CalendarPost[];
	onSelect: (post: CalendarPost) => void;
}) {
	const upcoming = useMemo(() => {
		return [...posts]
			.filter((post) => post.status === "scheduled" || post.status === "review")
			.sort((a, b) => new Date(postStart(a)).getTime() - new Date(postStart(b)).getTime())
			.slice(0, 6);
	}, [posts]);

	return (
		<NovaCard title="Next posts" description="Upcoming scheduled content">
			<div className="grid gap-2">
				{upcoming.length === 0 ? (
					<NovaEmpty
						title="No upcoming posts"
						description="Use the calendar grid to schedule the next item."
					/>
				) : (
					upcoming.map((post) => (
						<Button
							key={post.id}
							variant="ghost"
							onClick={() => onSelect(post)}
							className="h-auto min-w-0 justify-start gap-3 rounded-lg border border-border bg-muted/35 p-3 text-left hover:bg-muted"
						>
							<div className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground">
								{post.account.platform === "instagram" ? (
									<span className="text-xs font-semibold">IG</span>
								) : (
									<span className="text-sm font-semibold">@</span>
								)}
							</div>
							<div className="min-w-0 flex-1">
								<div className="flex min-w-0 items-center gap-2">
									<span className="truncate text-sm font-medium text-foreground">{postTitle(post)}</span>
									<Badge tone={STATUS_TONE[post.status]}>{STATUS_LABEL[post.status]}</Badge>
								</div>
								<p className="mt-1 truncate text-xs text-muted-foreground">
									@{post.account.handle} · {new Date(postStart(post)).toLocaleString([], {
										month: "short",
										day: "numeric",
										hour: "numeric",
										minute: "2-digit",
									})}
								</p>
							</div>
						</Button>
					))
				)}
			</div>
		</NovaCard>
	);
}

function PostDetailSheet({
	post,
	onClose,
	onDuplicate,
	onDelete,
	onOpenComposer,
}: {
	post: CalendarPost | null;
	onClose: () => void;
	onDuplicate: (post: CalendarPost) => void;
	onDelete: (post: CalendarPost) => void;
	onOpenComposer: (post: CalendarPost) => void;
}) {
	return (
		<Sheet
			open={Boolean(post)}
			onClose={onClose}
			title={post ? postTitle(post) : "Post details"}
			description={post ? `@${post.account.handle} · ${platformLabel(post.account.platform)}` : undefined}
			widthClass="w-full sm:w-[440px]"
		>
			{post ? (
				<div className="grid gap-4 p-5">
					<div className="flex flex-wrap items-center gap-2">
						<Badge tone={STATUS_TONE[post.status]}>{STATUS_LABEL[post.status]}</Badge>
						<Badge tone="outline">{new Date(postStart(post)).toLocaleString()}</Badge>
						{post.approvalStatus ? <Badge tone="outline">{post.approvalStatus}</Badge> : null}
					</div>

					<NovaCard variant="panel">
						<p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{post.content || "No caption yet."}</p>
					</NovaCard>

					<div className="grid grid-cols-2 gap-3">
						<NovaCard variant="panel">
							<div className="text-xs text-muted-foreground">Views / reach</div>
							<div className="mt-1 text-2xl font-semibold tracking-[-0.04em]">
								{formatNumber(metricValue(post.viewsCount, post.igViews, post.igReach))}
							</div>
						</NovaCard>
						<NovaCard variant="panel">
							<div className="text-xs text-muted-foreground">Engagement</div>
							<div className="mt-1 text-2xl font-semibold tracking-[-0.04em]">
								{formatNumber(metricValue(post.likesCount, post.repliesCount, post.sharesCount, post.igCommentCount, post.igSaved, post.igShares))}
							</div>
						</NovaCard>
					</div>

					{post.mediaUrls.length > 0 ? (
						<div className="grid grid-cols-2 gap-2">
							{post.mediaUrls.slice(0, 4).map((url) => (
								<img
									key={url}
									src={url}
									alt=""
									className="aspect-square rounded-lg border border-border object-cover"
									loading="lazy"
								/>
							))}
						</div>
					) : null}

					<Separator />

					<div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center">
						<Button variant="outline" onClick={() => onDuplicate(post)} className="justify-center">
							<Copy data-icon="inline-start" aria-hidden="true" />
							Duplicate
						</Button>
						<Button variant="outline" onClick={() => onOpenComposer(post)} className="justify-center">
							<CalendarDays data-icon="inline-start" aria-hidden="true" />
							Edit in composer
						</Button>
						{post.permalink ? (
							<Button variant="ghost" asChild className="justify-center">
								<a href={post.permalink} target="_blank" rel="noreferrer">
									<ExternalLink data-icon="inline-start" aria-hidden="true" />
									Open
								</a>
							</Button>
						) : null}
						<Button className="col-span-2 justify-center sm:ml-auto" variant="danger" onClick={() => onDelete(post)}>
							<Trash2 data-icon="inline-start" aria-hidden="true" />
							Delete
						</Button>
					</div>
				</div>
			) : null}
		</Sheet>
	);
}
