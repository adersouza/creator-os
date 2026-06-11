import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import {
	AlertTriangle,
	Bell,
	Check,
	CheckCheck,
	ChevronDown,
	ChevronUp,
	Sparkles,
	Trash2,
	TrendingUp,
	X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { IconTooltipButton } from "@/components/ui/IconTooltipButton";
import { Separator } from "@/components/ui/Separator";
import {
	type ActivityEvent as RealActivityEvent,
	useActivityEvents,
} from "@/hooks/useActivityEvents";
import { notificationService } from "@/services/notificationService";
import { type Notification as AppNotification, NotificationType } from "@/types/index";

type ActivityEventType = "pub" | "milestone" | "ai" | "crit";
type ActivityFilter = "all" | "publishes" | "errors" | "engagement" | "ai";

interface ActivityEvent {
	id: string;
	type: ActivityEventType;
	body: React.ReactNode;
	time: string;
	action?: { label: string; href: string } | undefined;
}

function ActivityIcon({ type }: { type: ActivityEventType }) {
	const map = {
		pub: { Icon: Check, color: "var(--color-health-good)" },
		milestone: { Icon: TrendingUp, color: "var(--color-gold)" },
		ai: { Icon: Sparkles, color: "var(--color-oxblood)" },
		crit: { Icon: AlertTriangle, color: "var(--color-negative)" },
	} as const;
	const { Icon, color } = map[type];
	return (
		<span
			className="w-6 h-6 rounded-md inline-flex items-center justify-center shrink-0 mt-0.5"
			style={{
				color,
				backgroundColor: `color-mix(in srgb, ${color} 12%, transparent)`,
			}}
		>
			<Icon className="w-3 h-3" />
		</span>
	);
}

function ActivityRow({
	event,
	critical = false,
	read = false,
	onActionNavigate,
	onMarkRead,
	onDelete,
}: {
	event: ActivityEvent;
	critical?: boolean | undefined;
	read?: boolean | undefined;
	onActionNavigate?: () => void;
	onMarkRead?: (id: string) => void;
	onDelete?: (id: string) => void;
}) {
	return (
		<div
			className={`group relative flex items-start gap-2.5 py-2.5 pr-14 ${critical ? "px-3 rounded-md" : "border-t border-border first:border-t-0"} ${read ? "opacity-55" : ""}`}
			style={
				critical
					? {
							backgroundColor:
								"color-mix(in srgb, var(--color-negative) 6%, transparent)",
						}
					: undefined
			}
		>
			<ActivityIcon type={event.type} />
			<div className="flex-1 min-w-0">
				<div
					className={`text-[0.78125rem] leading-[1.45] ${read ? "text-muted-foreground line-through decoration-muted-foreground/40" : "text-muted-foreground"}`}
				>
					{event.body}
				</div>
				<div className="flex items-center gap-2 mt-1">
					<span className="text-[0.625rem] text-muted-foreground tabular-nums">
						{event.time}
					</span>
					{event.action && !read && (
						<Link
							to={event.action.href}
							onClick={onActionNavigate}
							className="text-[0.65625rem] font-medium hover:underline"
							style={{ color: "var(--color-oxblood)" }}
						>
							{event.action.label}
						</Link>
					)}
				</div>
			</div>

			<div
				className={`absolute top-2 right-1 flex items-center gap-0.5 transition-opacity ${
					read
						? "opacity-100"
						: "opacity-40 group-hover:opacity-100 focus-within:opacity-100"
				}`}
			>
				{!read && (
					<IconTooltipButton
						label="Mark as read"
						onClick={() => onMarkRead?.(event.id)}
						className="text-muted-foreground hover:text-foreground"
					>
						<span className="w-6 h-6 rounded-md inline-flex items-center justify-center hover:bg-muted">
							<CheckCheck className="w-3.5 h-3.5" />
						</span>
					</IconTooltipButton>
				)}
				<IconTooltipButton
					label="Delete notification"
					onClick={() => onDelete?.(event.id)}
					className="text-muted-foreground hover:text-[color:var(--color-oxblood)]"
				>
					<span className="w-6 h-6 rounded-md inline-flex items-center justify-center hover:bg-[color-mix(in_srgb,var(--color-oxblood)_8%,transparent)]">
						<Trash2 className="w-3.5 h-3.5" />
					</span>
				</IconTooltipButton>
			</div>
		</div>
	);
}

export function activityStorageKey(
	kind: "read" | "deleted",
	userId: string | null | undefined,
): string | null {
	if (!userId) return null;
	return `juno33-activity-${kind}:${userId}`;
}

export function loadIdSet(key: string | null): Set<string> {
	if (!key || typeof localStorage === "undefined") return new Set();
	try {
		const raw = localStorage.getItem(key);
		if (!raw) return new Set();
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed) ? new Set(parsed) : new Set();
	} catch {
		return new Set();
	}
}

export function persistIdSet(key: string | null, set: Set<string>) {
	if (!key || typeof localStorage === "undefined") return;
	try {
		localStorage.setItem(key, JSON.stringify(Array.from(set)));
	} catch {
		/* quota / disabled - silent */
	}
}

function adaptRealEvent(e: RealActivityEvent): ActivityEvent {
	const type: ActivityEventType =
		e.kind === "publish"
			? "pub"
			: e.kind === "error"
				? "crit"
				: e.kind === "engagement"
					? "milestone"
					: "ai";
	const body = (
		<span>
			<b className="text-foreground">{e.account ?? e.title}</b>{" "}
			{e.account
				? e.title.replace(e.account, "").replace(/^[·:\s]+/, "")
				: e.detail}
		</span>
	);
	return {
		id: e.id,
		type,
		body,
		time: e.ago,
		action: e.action?.href
			? { label: e.action.label, href: e.action.href }
			: undefined,
	};
}

export function isActionableActivityEvent(e: RealActivityEvent): boolean {
	return (
		e.bucket === "critical" || e.bucket === "today" || e.bucket === "yesterday"
	);
}

function dateFromTimestamp(value: AppNotification["createdAt"]): Date {
	if (value instanceof Date) return value;
	if (typeof value === "string") return new Date(value);
	return value.toDate?.() ?? new Date();
}

function formatRelativeTime(from: Date, now: Date): string {
	const diffMin = Math.max(
		0,
		Math.floor((now.getTime() - from.getTime()) / 60000),
	);
	if (diffMin < 1) return "just now";
	if (diffMin < 60) return `${diffMin}m ago`;
	const diffHours = Math.floor(diffMin / 60);
	if (diffHours < 24) return `${diffHours}h ago`;
	const diffDays = Math.floor(diffHours / 24);
	return `${diffDays}d ago`;
}

function notificationTypeFor(n: AppNotification): ActivityEventType {
	if (
		n.priority === "urgent" ||
		n.priority === "high" ||
		n.type === NotificationType.POST_FAILED ||
		n.type === NotificationType.TOKEN_EXPIRING ||
		n.type === NotificationType.GOAL_AT_RISK
	) {
		return "crit";
	}
	if (
		n.type === NotificationType.FOLLOWER_MILESTONE ||
		n.type === NotificationType.ENGAGEMENT_SPIKE ||
		n.type === NotificationType.TREND_SPIKE ||
		n.type === NotificationType.GOAL_MILESTONE ||
		n.type === NotificationType.GOAL_COMPLETED
	) {
		return "milestone";
	}
	if (
		n.type === NotificationType.SYSTEM_ANNOUNCEMENT ||
		n.type === NotificationType.FEATURE_UPDATE ||
		n.type === NotificationType.QUICK_WIN_RESULT ||
		n.type === NotificationType.QUICK_WIN_REGRESSED ||
		n.type === NotificationType.QUICK_WIN_FADED
	) {
		return "ai";
	}
	return "pub";
}

function notificationMatchesFilter(
	n: AppNotification,
	filter: ActivityFilter,
): boolean {
	if (filter === "all") return true;
	const type = notificationTypeFor(n);
	if (filter === "publishes") return type === "pub";
	if (filter === "errors") return type === "crit";
	if (filter === "engagement") return type === "milestone";
	return type === "ai";
}

function adaptNotification(n: AppNotification): ActivityEvent {
	return {
		id: n.id,
		type: notificationTypeFor(n),
		body: (
			<span>
				<b className="text-foreground">{n.title}</b>{" "}
				{n.message ? <span>{n.message}</span> : null}
			</span>
		),
		time: formatRelativeTime(dateFromTimestamp(n.createdAt), new Date()),
		action: n.actionUrl ? { label: "Open", href: n.actionUrl } : undefined,
	};
}

interface ActivityPanelProps {
	onClose: () => void;
	readIds: Set<string>;
	setReadIds: React.Dispatch<React.SetStateAction<Set<string>>>;
	deletedIds: Set<string>;
	setDeletedIds: React.Dispatch<React.SetStateAction<Set<string>>>;
	notifications: AppNotification[];
	setNotifications: React.Dispatch<React.SetStateAction<AppNotification[]>>;
	notificationsError: boolean;
}

export function ActivityPanel({
	onClose,
	readIds,
	setReadIds,
	deletedIds,
	setDeletedIds,
	notifications,
	setNotifications,
	notificationsError,
}: ActivityPanelProps) {
	const [filter, setFilter] = useState<ActivityFilter>("all");
	const [yesterdayOpen, setYesterdayOpen] = useState(true);
	const {
		events: realEvents,
		isLoading: realLoading,
		hasError: realError,
	} = useActivityEvents();

	useEffect(() => {
		const FILTER_BY_KEY: Record<string, ActivityFilter> = {
			"1": "all",
			"2": "publishes",
			"3": "errors",
			"4": "engagement",
			"5": "ai",
		};
		const handler = (e: KeyboardEvent) => {
			if (e.metaKey || e.ctrlKey || e.altKey) return;
			const target = e.target as HTMLElement | null;
			const tag = target?.tagName;
			if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable)
				return;
			const next = FILTER_BY_KEY[e.key];
			if (!next) return;
			e.preventDefault();
			setFilter(next);
		};
		window.addEventListener("keydown", handler);
		return () => window.removeEventListener("keydown", handler);
	}, []);

	const { realCritical, realToday, realYesterday } = useMemo(() => {
		if (realLoading || realError)
			return { realCritical: [], realToday: [], realYesterday: [] };
		const crit: ActivityEvent[] = [];
		const today: ActivityEvent[] = [];
		const yest: ActivityEvent[] = [];
		for (const e of realEvents) {
			const adapted = adaptRealEvent(e);
			if (e.bucket === "today") today.push(adapted);
			else if (e.bucket === "yesterday") yest.push(adapted);
			else if (e.bucket === "critical") crit.push(adapted);
		}
		return { realCritical: crit, realToday: today, realYesterday: yest };
	}, [realEvents, realLoading, realError]);

	const criticalSource = realCritical;
	const todaySource = realToday;
	const yesterdaySource = realYesterday;

	const matchesFilter = (event: ActivityEvent) => {
		switch (filter) {
			case "all":
				return true;
			case "publishes":
				return event.type === "pub";
			case "errors":
				return event.type === "crit";
			case "engagement":
				return event.type === "milestone";
			case "ai":
				return event.type === "ai";
			default:
				return true;
		}
	};

	const markRead = (id: string) =>
		setReadIds((s) => {
			const next = new Set(s);
			next.add(id);
			return next;
		});

	const deleteEvent = (id: string) =>
		setDeletedIds((s) => {
			const next = new Set(s);
			next.add(id);
			return next;
		});

	const markNotificationRead = (id: string) => {
		setNotifications((items) =>
			items.map((item) => (item.id === id ? { ...item, read: true } : item)),
		);
		void notificationService.markAsRead(id);
	};

	const deleteNotification = (id: string) => {
		setNotifications((items) => items.filter((item) => item.id !== id));
		void notificationService.deleteNotification(id);
	};

	const visibleCritical = criticalSource.filter(
		(e) => !deletedIds.has(e.id) && matchesFilter(e),
	);
	const visibleToday = todaySource.filter(
		(e) => !deletedIds.has(e.id) && matchesFilter(e),
	);
	const visibleYesterday = yesterdaySource.filter(
		(e) => !deletedIds.has(e.id) && matchesFilter(e),
	);
	const visibleNotifications = notifications.filter((n) =>
		notificationMatchesFilter(n, filter),
	);

	const visibleAll = [...visibleCritical, ...visibleToday, ...visibleYesterday];
	const visibleUnreadNotifications = visibleNotifications.filter((n) => !n.read);
	const globalVisibleEvents = [
		...criticalSource,
		...todaySource,
		...yesterdaySource,
	].filter((e) => !deletedIds.has(e.id));
	const globalUnreadCount =
		globalVisibleEvents.filter((e) => !readIds.has(e.id)).length +
		notifications.filter((n) => !n.read).length;
	const visibleUnreadCount =
		visibleAll.filter((e) => !readIds.has(e.id)).length +
		visibleUnreadNotifications.length;
	const isEmpty =
		!realLoading &&
		!realError &&
		!notificationsError &&
		visibleAll.length === 0 &&
		visibleNotifications.length === 0;

	const markAllRead = () => {
		if (visibleUnreadCount === 0) return;
		setReadIds((s) => {
			const next = new Set(s);
			visibleAll.forEach((e) => {
				next.add(e.id);
			});
			return next;
		});
		if (visibleUnreadNotifications.length > 0) {
			const ids = new Set(visibleUnreadNotifications.map((n) => n.id));
			setNotifications((items) =>
				items.map((item) =>
					ids.has(item.id) ? { ...item, read: true } : item,
				),
			);
			void Promise.all(
				visibleUnreadNotifications.map((n) => notificationService.markAsRead(n.id)),
			);
		}
	};

	const clearAllVisible = () => {
		if (visibleAll.length === 0 && visibleNotifications.length === 0) return;
		setDeletedIds((s) => {
			const next = new Set(s);
			visibleAll.forEach((e) => {
				next.add(e.id);
			});
			return next;
		});
		if (visibleNotifications.length > 0) {
			const ids = new Set(visibleNotifications.map((n) => n.id));
			setNotifications((items) => items.filter((item) => !ids.has(item.id)));
			void Promise.all(
				visibleNotifications.map((n) =>
					notificationService.deleteNotification(n.id),
				),
			);
		}
	};

	const filters: { id: ActivityFilter; label: string }[] = [
		{ id: "all", label: "All" },
		{ id: "publishes", label: "Publishes" },
		{ id: "errors", label: "Errors" },
		{ id: "engagement", label: "Engagement" },
		{ id: "ai", label: "AI flags" },
	];

	if (typeof document === "undefined") return null;

	return createPortal(
		<>
			<div
				onClick={onClose}
				className="fixed inset-0 bg-foreground/40 backdrop-blur-sm z-40"
			/>
			<div
				className="fixed top-0 right-0 h-dvh w-full sm:w-[360px] bg-card-elevated border-l border-border shadow-2xl z-50 flex flex-col"
			>
				<div className="px-5 py-4 border-b border-border flex items-center justify-between">
					<h3 className="font-semibold text-[0.9375rem] tracking-tight text-foreground">
						Activity
					</h3>
					<IconTooltipButton
						label="Close activity panel"
						onClick={onClose}
						className="text-muted-foreground hover:text-foreground"
						side="bottom"
					>
						<span className="w-7 h-7 rounded-md inline-flex items-center justify-center hover:bg-muted">
							<X className="w-4 h-4" />
						</span>
					</IconTooltipButton>
				</div>

				<div className="px-5 py-2.5 border-b border-border flex items-center gap-2 min-h-11">
					<div className="flex items-center gap-1 overflow-x-auto hide-scrollbar flex-1 min-w-0">
						{filters.map((f) => {
							const active = filter === f.id;
							const showBadge = f.id === "all" && globalUnreadCount > 0;
							return (
								<Button
									key={f.id}
									variant="ghost"
									size="sm"
									type="button"
									onClick={() => setFilter(f.id)}
									className={`h-7 px-2.5 rounded-full text-[0.6875rem] font-medium tabular-nums whitespace-nowrap transition-colors inline-flex items-center gap-1.5 shrink-0 outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring-oxblood)] ${
										active
											? "bg-muted text-foreground"
											: "text-muted-foreground hover:text-foreground"
									}`}
								>
									{f.label}
									{showBadge && (
										<span
											className="inline-flex items-center justify-center min-w-[14px] h-[14px] px-1 rounded-full text-[0.59375rem] font-semibold tabular-nums"
											style={{
												color: "var(--color-primary-foreground)",
												backgroundColor: "var(--color-oxblood)",
											}}
										>
											{globalUnreadCount}
										</span>
									)}
								</Button>
							);
						})}
					</div>

					<Separator orientation="vertical" className="h-5 shrink-0" />

					<div className="flex items-center gap-0.5 shrink-0">
						<IconTooltipButton
							label="Mark all as read"
							onClick={markAllRead}
							disabled={visibleUnreadCount === 0}
							className="text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-muted-foreground"
							side="bottom"
						>
							<span className="w-7 h-7 rounded-md inline-flex items-center justify-center hover:bg-muted active:bg-muted">
								<CheckCheck className="w-3.5 h-3.5" aria-hidden="true" />
							</span>
						</IconTooltipButton>
						<IconTooltipButton
							label="Clear all visible notifications"
							onClick={clearAllVisible}
							disabled={isEmpty}
							className="text-muted-foreground hover:text-[color:var(--color-oxblood)] disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-muted-foreground"
							side="bottom"
						>
							<span className="w-7 h-7 rounded-md inline-flex items-center justify-center hover:bg-[color-mix(in_srgb,var(--color-oxblood)_8%,transparent)] active:bg-[color-mix(in_srgb,var(--color-oxblood)_14%,transparent)]">
								<Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
							</span>
						</IconTooltipButton>
					</div>
				</div>

				<div className="flex-1 overflow-y-auto">
					{realLoading && (
						<div className="px-5 py-14 flex flex-col items-center justify-center text-center">
							<div className="w-12 h-12 rounded-full bg-muted border border-border inline-flex items-center justify-center mb-3">
								<Bell className="w-5 h-5 text-muted-foreground" />
							</div>
							<div className="text-[0.875rem] font-medium text-foreground">
								Catching up on activity
							</div>
							<p className="mt-1 text-[0.75rem] text-muted-foreground max-w-[220px]">
								Pulling the latest publishes, alerts, and AI flags now.
							</p>
						</div>
					)}

					{realError && (
						<div className="px-5 py-14 flex flex-col items-center justify-center text-center">
							<div className="w-12 h-12 rounded-full bg-muted border border-border inline-flex items-center justify-center mb-3">
								<Bell className="w-5 h-5 text-muted-foreground" />
							</div>
							<div className="text-[0.875rem] font-medium text-foreground">
								Activity unavailable
							</div>
							<p className="mt-1 text-[0.75rem] text-muted-foreground max-w-[220px]">
								Live activity could not be loaded right now. Try again in a
								moment.
							</p>
						</div>
					)}

					{notificationsError && !realError && visibleNotifications.length === 0 && (
						<div className="px-5 py-14 flex flex-col items-center justify-center text-center">
							<div className="w-12 h-12 rounded-full bg-muted border border-border inline-flex items-center justify-center mb-3">
								<Bell className="w-5 h-5 text-muted-foreground" />
							</div>
							<div className="text-[0.875rem] font-medium text-foreground">
								Notifications unavailable
							</div>
							<p className="mt-1 text-[0.75rem] text-muted-foreground max-w-[220px]">
								In-app notifications could not be loaded right now.
							</p>
						</div>
					)}

					{isEmpty && (
						<div className="px-5 py-14 flex flex-col items-center justify-center text-center">
							<div className="w-12 h-12 rounded-full bg-muted border border-border inline-flex items-center justify-center mb-3">
								<Bell className="w-5 h-5 text-muted-foreground" />
							</div>
							<div className="text-[0.875rem] font-medium text-foreground">
								No activity yet
							</div>
							<p className="mt-1 text-[0.75rem] text-muted-foreground max-w-[220px]">
								{filter === "all"
									? "Publishes, milestones, AI flags, and critical alerts will appear here as they happen."
									: "No matching activity for this filter yet. Try another filter or come back once more events land."}
							</p>
						</div>
					)}

					{visibleNotifications.length > 0 && (
						<section className="px-5 py-4">
							<div className="text-[0.6875rem] font-semibold text-muted-foreground mb-1">
								Notifications
							</div>
							<div>
								{visibleNotifications.map((n) => (
									<ActivityRow
										key={n.id}
										event={adaptNotification(n)}
										read={n.read}
										onActionNavigate={onClose}
										onMarkRead={markNotificationRead}
										onDelete={deleteNotification}
									/>
								))}
							</div>
						</section>
					)}

					{visibleCritical.length > 0 && (
						<section className="px-5 py-4 border-t border-border first:border-t-0">
							<div className="text-[0.6875rem] font-semibold text-muted-foreground mb-2">
								Critical
							</div>
							<div className="flex flex-col gap-1.5">
								{visibleCritical.map((e) => (
									<ActivityRow
										key={e.id}
										event={e}
										critical
										read={readIds.has(e.id)}
										onActionNavigate={onClose}
										onMarkRead={markRead}
										onDelete={deleteEvent}
									/>
								))}
							</div>
						</section>
					)}

					{visibleToday.length > 0 && (
						<section className="px-5 py-4 border-t border-border">
							<div className="text-[0.6875rem] font-semibold text-muted-foreground mb-1">
								Today
							</div>
							<div>
								{visibleToday.map((e) => (
									<ActivityRow
										key={e.id}
										event={e}
										read={readIds.has(e.id)}
										onActionNavigate={onClose}
										onMarkRead={markRead}
										onDelete={deleteEvent}
									/>
								))}
							</div>
						</section>
					)}

					{visibleYesterday.length > 0 && (
						<section className="px-5 py-4 border-t border-border">
							<Button
								variant="ghost"
								size="sm"
								type="button"
								onClick={() => setYesterdayOpen((v) => !v)}
								className="w-full flex items-center justify-between text-left mb-1 group"
							>
								<span className="text-[0.6875rem] font-semibold text-muted-foreground group-hover:text-foreground transition-colors">
									Yesterday
								</span>
								{yesterdayOpen ? (
									<ChevronUp className="w-3 h-3 text-muted-foreground" />
								) : (
									<ChevronDown className="w-3 h-3 text-muted-foreground" />
								)}
							</Button>
							<div
								className={
									yesterdayOpen
										? "grid grid-rows-[1fr] opacity-100 transition-[grid-template-rows,opacity] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)]"
										: "grid grid-rows-[0fr] opacity-0 transition-[grid-template-rows,opacity] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)]"
								}
								aria-hidden={!yesterdayOpen}
							>
								<div className="overflow-hidden">
									{visibleYesterday.map((e) => (
										<ActivityRow
											key={e.id}
											event={e}
											read={readIds.has(e.id)}
											onActionNavigate={onClose}
											onMarkRead={markRead}
											onDelete={deleteEvent}
										/>
									))}
								</div>
							</div>
						</section>
					)}
				</div>
			</div>
		</>,
		document.body,
	);
}
