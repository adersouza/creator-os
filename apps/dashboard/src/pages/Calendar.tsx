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
	CheckCircle2,
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
	NovaDataPanel,
	NovaEmpty,
	NovaHeader,
	NovaSection,
	NovaStat,
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
import { deletePost, duplicatePost, updatePost } from "@/services/api/posts";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";

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

	const metrics = useMemo(() => {
		const scheduled = filteredPosts.filter((post) => post.status === "scheduled").length;
		const published = filteredPosts.filter((post) => post.status === "published").length;
		const failed = filteredPosts.filter((post) => post.status === "failed").length;
		const reach = filteredPosts.reduce(
			(sum, post) => sum + metricValue(post.viewsCount, post.igViews, post.igReach),
			0,
		);
		const completion = filteredPosts.length > 0 ? Math.round((published / filteredPosts.length) * 100) : 0;
		return { scheduled, published, failed, reach, completion };
	}, [filteredPosts]);

	const groupOptions = useMemo(() => {
		const all = [{ value: "all", label: "All groups" }];
		return all.concat(calendarState.groups.map((group) => ({ value: group.id, label: group.name })));
	}, [calendarState.groups]);

	const openComposerForDate = useCallback(
		(date: Date) => {
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
			appToast.success("Post rescheduled");
		} catch (error) {
			void error;
			info.revert();
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
		return (
			<div className="nova-calendar-event" style={{ "--event-accent": eventColor(post) } as React.CSSProperties}>
				<div className="flex min-w-0 items-center gap-1.5">
					<span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--event-accent)]" />
					<span className="truncate text-[0.6875rem] font-semibold text-foreground">{info.timeText}</span>
					<span className="truncate text-[0.6875rem] text-muted-foreground">{platformLabel(post.account.platform)}</span>
				</div>
				<div className="mt-1 truncate text-[0.75rem] font-medium leading-tight text-foreground">{info.event.title}</div>
			</div>
		);
	}, []);

	return (
		<NovaScreen width="wide" className="calendar-page calendar-page--nova">
			<NovaHeader
				eyebrow="Calendar"
				title="Publishing schedule"
				description="Plan, inspect, and move scheduled content across Threads and Instagram."
				meta={formatRangeLabel(anchorDate, viewMode)}
				actions={
					<NovaToolbar>
						<Button variant="outline" size="sm" onClick={refreshCalendar}>
							<RefreshCw data-icon="start" aria-hidden="true" />
							Refresh
						</Button>
						<Button size="sm" onClick={() => openComposerForDate(new Date())}>
							<Plus data-icon="start" aria-hidden="true" />
							New post
						</Button>
					</NovaToolbar>
				}
				filters={
					<>
						{scopedAccount ? (
							<AccountScopeChip
								handle={scopedAccount.handle}
								color={scopedAccount.platform === "instagram" ? "#E4405F" : "var(--color-oxblood)"}
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
							className="w-[180px]"
						/>
					</>
				}
			/>

			<NovaSection className="grid gap-3 md:grid-cols-4">
				<NovaStat
					label="Scheduled"
					value={metrics.scheduled}
					description="Ready to publish in this window"
					icon={<CalendarDays aria-hidden="true" />}
					loading={calendarState.isLoading}
				/>
				<NovaStat
					label="Published"
					value={metrics.published}
					description="Completed posts in view"
					icon={<CheckCircle2 aria-hidden="true" />}
					progress={{ value: metrics.completion, label: "Published share" }}
					loading={calendarState.isLoading}
				/>
				<NovaStat
					label="Reach"
					value={formatNumber(metrics.reach)}
					description="Visible post reach and views"
					trend={metrics.reach > 0 ? { direction: "up", label: "Live data" } : "No data"}
					loading={calendarState.isLoading}
				/>
				<NovaStat
					label="Needs attention"
					value={calendarState.gapsCount + metrics.failed}
					description={`${calendarState.gapsCount} gaps · ${metrics.failed} failed`}
					status={metrics.failed > 0 ? "Action" : "Clear"}
					loading={calendarState.isLoading}
				/>
			</NovaSection>

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
			<div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
				<NovaDataPanel
					title="Calendar"
					description="Drag unpublished posts to reschedule. Click empty time to compose."
					loading={calendarState.isLoading}
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
					) : filteredPosts.length === 0 ? (
						<NovaEmpty
							title="No posts in this view"
							description="Select an open slot to create the first scheduled post for this range."
						>
							<Button onClick={() => openComposerForDate(anchorDate)}>
								<Plus data-icon="start" aria-hidden="true" />
								Create post
							</Button>
						</NovaEmpty>
					) : (
						<div className="nova-calendar-shell">
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
								slotMinTime="05:00:00"
								slotMaxTime="23:00:00"
								slotDuration="00:30:00"
								height="auto"
								events={events}
								eventContent={renderEventContent}
								eventClick={handleEventClick}
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
					)}
				</NovaDataPanel>

				<NovaSection className="grid content-start gap-4">
					<UpcomingPanel posts={filteredPosts} onSelect={setSelectedPost} />
				</NovaSection>
			</div>
			)}

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

					<div className="flex flex-wrap items-center gap-2">
						<Button variant="outline" onClick={() => onDuplicate(post)}>
							<Copy data-icon="start" aria-hidden="true" />
							Duplicate
						</Button>
						<Button variant="outline" onClick={() => onOpenComposer(post)}>
							<CalendarDays data-icon="start" aria-hidden="true" />
							Edit in composer
						</Button>
						{post.permalink ? (
							<Button variant="ghost" asChild>
								<a href={post.permalink} target="_blank" rel="noreferrer">
									<ExternalLink data-icon="start" aria-hidden="true" />
									Open
								</a>
							</Button>
						) : null}
						<Button className="ml-auto" variant="danger" onClick={() => onDelete(post)}>
							<Trash2 data-icon="start" aria-hidden="true" />
							Delete
						</Button>
					</div>
				</div>
			) : null}
		</Sheet>
	);
}
