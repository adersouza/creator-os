// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.

import { X } from "lucide-react";
import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/Button";
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Z } from "@/components/ui/overlayZ";
import { AITopHoursOverlay } from "./AITopHoursOverlay";
import { PostCard } from "./PostCardRow";
import { MagnetGuide, SlotIndicator } from "./SlotIndicator";
import {
	CALENDAR_BOTTOM_BUFFER,
	CALENDAR_HEIGHT,
	CALENDAR_VIEWPORT,
	CARD_HEIGHT,
	CARD_OCCUPIES_MINUTES,
	DAY_NAMES,
	END_HOUR,
	formatHour,
	HOUR_HEIGHT,
	INITIAL_SCROLL_HOUR,
	MAX_LANES_PER_CLUSTER,
	MAX_VISIBLE_PER_DAY,
	type Post,
	START_HOUR,
	timeToY,
	yToTime,
} from "./shared";
import { TimezoneGutter } from "./TimezoneGutter";

/**
 * Assign side-by-side lanes to posts that overlap in time so they render
 * like Google Calendar / Fantastical instead of stacking on top of each
 * other. Input must be sorted by start time. Output gives each laid-out
 * post a `lane` index (0..N-1) and a `laneCount` (total lanes in that
 * post's contiguous-overlap cluster) so the renderer can compute
 * `left: lane/laneCount` + `width: 1/laneCount`.
 *
 * Posts that would push a cluster beyond MAX_LANES_PER_CLUSTER get
 * dropped into `overflow` so the existing "+N more" drawer keeps
 * surfacing them. This caps visual density without hiding data.
 */
function assignLanes(
	posts: Post[],
	maxLanes: number,
	cardMinutes: number,
): {
	laid: Array<{ post: Post; lane: number; laneCount: number }>;
	overflow: Post[];
} {
	const laid: Array<{ post: Post; lane: number; laneCount: number }> = [];
	const overflow: Post[] = [];
	if (posts.length === 0) return { laid, overflow };

	let clusterStart = 0;
	let clusterEndMin = -1;
	let laneEnds: number[] = [];

	const closeCluster = () => {
		const peak = laneEnds.length;
		for (let i = clusterStart; i < laid.length; i++) laid[i]!.laneCount = peak;
		clusterStart = laid.length;
		clusterEndMin = -1;
		laneEnds = [];
	};

	for (const p of posts) {
		const startMin = p.hour * 60 + p.minute;
		const endMin = startMin + cardMinutes;

		// New cluster when this post starts after the furthest-reaching
		// occupant in the current cluster. Until then we're still stacked.
		if (startMin >= clusterEndMin) closeCluster();

		// Smallest lane whose previous occupant ended by this post's start.
		let lane = laneEnds.findIndex((e) => e <= startMin);
		if (lane === -1) {
			if (laneEnds.length < maxLanes) {
				lane = laneEnds.length;
				laneEnds.push(endMin);
			} else {
				overflow.push(p);
				continue;
			}
		} else {
			laneEnds[lane] = endMin;
		}

		laid.push({ post: p, lane, laneCount: 0 });
		if (endMin > clusterEndMin) clusterEndMin = endMin;
	}
	closeCluster();

	return { laid, overflow };
}

/* =========================================================================
   WEEK VIEW — 7 day columns, posts sorted by time, empty-slot CTA.
   Extracted from src/pages/Calendar.tsx verbatim.
   ========================================================================= */
interface WeekViewProps {
	posts: Post[];
	weekStart: Date;
	today: Date;
	now: Date;
	onCardClick: (p: Post, e: React.MouseEvent) => void;
	onFillSlot: (day: number, hour: number, minute: number) => void;
	selectedIds: Set<string>;
	dropTargetDay: number | null;
	dropHintY: number | null;
	onDragMove: (x: number, y: number) => void;
	onDragEnd: (postId: string, moved: boolean) => void;
	onQuickMove?:
		| ((
				post: Post,
				action: "minus-hour" | "plus-hour" | "tomorrow" | "next-peak",
		  ) => void)
		| undefined;
	riskLabelsByPostId?: Record<string, string[]> | undefined;
	/** Hour buckets (0–23) where the user's past published posts earned the
	 *  highest engagement rate. Used to tint matching rows in the grid. */
	bestHours: number[];
	travelTimeZones?: string[] | undefined;
	aiHoursEnabled?: boolean | undefined;
}

export function WeekViewGrid({
	posts,
	weekStart,
	today,
	now,
	onCardClick,
	onFillSlot,
	selectedIds,
	dropTargetDay,
	dropHintY,
	onDragMove,
	onDragEnd,
	onQuickMove,
	riskLabelsByPostId = {},
	bestHours,
	travelTimeZones = [],
	aiHoursEnabled = false,
}: WeekViewProps) {
	const isToday = (dayIdx: number) => {
		const d = new Date(weekStart);
		d.setDate(weekStart.getDate() + dayIdx);
		return d.toDateString() === today.toDateString();
	};
	const dateFor = (dayIdx: number) => {
		const d = new Date(weekStart);
		d.setDate(weekStart.getDate() + dayIdx);
		return d.getDate();
	};

	const hourLabels = useMemo(() => {
		const labels: number[] = [];
		for (let h = START_HOUR; h < END_HOUR; h++) labels.push(h);
		return labels;
	}, []);

	// Group-and-sort posts by day once, not per day in the map loop below.
	const postsByDay = useMemo(() => {
		const grouped: Record<number, Post[]> = {};
		for (let d = 0; d < 7; d++) grouped[d] = [];
		for (const p of posts) {
			const bucket = grouped[p.day];
			if (bucket) bucket.push(p);
		}
		for (const d of Object.keys(grouped)) {
			grouped[Number(d)]!.sort(
				(a, b) => a.hour * 60 + a.minute - (b.hour * 60 + b.minute),
			);
		}
		return grouped;
	}, [posts]);

	const nowY =
		now.getHours() >= START_HOUR && now.getHours() < END_HOUR
			? timeToY(now.getHours(), now.getMinutes())
			: null;
	const peakHours = useMemo(() => bestHours.slice(0, 3), [bestHours]);
	const allTimeZones = useMemo(() => {
		const local = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
		return [local, ...travelTimeZones.filter((tz) => tz && tz !== local)];
	}, [travelTimeZones]);

	// Hover-indicator state — oxblood line + time chip following the cursor
	// over an empty day column. Replaces the ugly OS `cursor: copy` affordance.
	const [hoverSlot, setHoverSlot] = useState<{ day: number; y: number } | null>(
		null,
	);
	const [keyboardSlot, setKeyboardSlot] = useState<{
		day: number;
		hour: number;
		minute: number;
	} | null>(null);

	// Which day column has its "more" drawer open (0..6 or null).
	const [drawerDay, setDrawerDay] = useState<number | null>(null);

	// Inner scroll — on mount, scroll to INITIAL_SCROLL_HOUR so the user lands
	// at peak posting hours instead of midnight.
	const scrollRef = useRef<HTMLDivElement | null>(null);
	const [scrolled, setScrolled] = useState(false);
	useEffect(() => {
		const el = scrollRef.current;
		if (!el) return;
		el.scrollTop = (INITIAL_SCROLL_HOUR - START_HOUR) * HOUR_HEIGHT;
		setScrolled(el.scrollTop > 8);
		const onScroll = () => setScrolled(el.scrollTop > 8);
		el.addEventListener("scroll", onScroll, { passive: true });
		return () => el.removeEventListener("scroll", onScroll);
	}, []);

	const weekEnd = new Date(weekStart);
	weekEnd.setDate(weekStart.getDate() + 6);
	const weekRangeLabel = `${weekStart.toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${weekEnd.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;

	return (
		<NovaCard
			contentClassName="relative p-0"
			aria-label={`Week calendar, ${weekRangeLabel}`}
		>
			{/* Subtle top gradient shadow — signals scrolled content above the viewport.
          Positioned below sticky header so it fades directly into the first row. */}
			<div
				className="pointer-events-none absolute left-0 right-0 z-[25] transition-opacity duration-200"
				style={{
					top: 69, // directly under header row
					height: 14,
					opacity: scrolled ? 1 : 0,
					background:
						"linear-gradient(to bottom, color-mix(in srgb, var(--color-foreground) 8%, transparent), transparent)",
				}}
				aria-hidden="true"
			/>
			<div
				ref={scrollRef}
				className="hide-scrollbar overflow-auto"
				// `height` (not maxHeight) forces the scroll box to exactly the viewport
				// regardless of content — otherwise some layouts let the inner grid's
				// 1360px height push the whole card tall, leaving dead space under the
				// last hour that the user reads as "I'm scrolling past the day".
				style={{ height: CALENDAR_VIEWPORT }}
			>
				{/* Column headers — sticky so they stay visible while scrolling time
            axis. Needs an OPAQUE background: the "+N more" overflow pill is
            z-15 and parks right below the header; if the header stayed at
            bg-card (~7% in dark mode) the pill bleeds through. bg-background
            matches the substrate so the handoff into the grid stays clean. */}
				<div
					role="rowgroup"
					className="sticky top-0 z-30 grid border-b border-border bg-background"
					style={{
						gridTemplateColumns: `${56 * allTimeZones.length}px repeat(7,minmax(0,1fr))`,
					}}
				>
					<div className="border-r border-border" aria-hidden="true" />
					{DAY_NAMES.map((day, i) => {
						const today_ = isToday(i);
						return (
							<div
								key={day}
								role="columnheader"
								tabIndex={0}
								aria-label={`${day} ${dateFor(i)}${today_ ? ", today" : ""}`}
								className={`flex h-[68px] flex-col items-center justify-center border-r border-border px-2 text-center ${
									today_ ? "bg-foreground/[0.03]" : ""
								}`}
							>
								<div
									className={`text-[0.65625rem] font-bold uppercase tracking-[0.12em] ${today_ ? "text-foreground" : "text-muted-foreground"}`}
								>
									{day}
								</div>
								<div
									className={`text-[1.125rem] tracking-[-0.02em] tabular-nums mt-0.5 ${today_ ? "font-medium text-foreground" : "font-normal text-muted-foreground"}`}
								>
									{dateFor(i)}
								</div>
							</div>
						);
					})}
				</div>

				{/* Time axis body */}
				<div
					className="relative grid"
					style={{
						height: CALENDAR_HEIGHT + CALENDAR_BOTTOM_BUFFER,
						gridTemplateColumns: `${56 * allTimeZones.length}px repeat(7,minmax(0,1fr))`,
					}}
				>
					<TimezoneGutter timeZones={allTimeZones} now={now} />

					{/* 7 day columns */}
					{DAY_NAMES.map((_, dayIdx) => {
						const allDayPosts = postsByDay[dayIdx];
						// Cap visible inline cards. Extras live in the per-day drawer the
						// "+N more" pill opens — still fully draggable from there.
						const dayPosts = allDayPosts!.slice(0, MAX_VISIBLE_PER_DAY);
						// Side-by-side lane assignment so overlapping slots don't stack
						// on top of each other. Posts that exceed MAX_LANES_PER_CLUSTER
						// spill into `laneOverflow` and join the "+N more" drawer.
						const { laid: laidPosts, overflow: laneOverflow } = assignLanes(
							dayPosts,
							MAX_LANES_PER_CLUSTER,
							CARD_OCCUPIES_MINUTES,
						);
						const overflowPosts = [
							...allDayPosts!.slice(MAX_VISIBLE_PER_DAY),
							...laneOverflow,
						];
						const isDropTarget = dropTargetDay === dayIdx;
						const today_ = isToday(dayIdx);
						const showHover = hoverSlot?.day === dayIdx && !isDropTarget;
						return (
							<div
								key={dayIdx}
								data-day={dayIdx}
								role="gridcell"
								tabIndex={0}
								aria-label={`${DAY_NAMES[dayIdx]} schedule column. Use arrow keys to choose a time, Enter to create a post.`}
								onFocus={() =>
									setKeyboardSlot((slot) =>
										slot?.day === dayIdx
											? slot
											: { day: dayIdx, hour: INITIAL_SCROLL_HOUR, minute: 0 },
									)
								}
								onKeyDown={(e) => {
									const current =
										keyboardSlot?.day === dayIdx
											? keyboardSlot
											: { day: dayIdx, hour: INITIAL_SCROLL_HOUR, minute: 0 };
									if (e.key === "ArrowUp" || e.key === "ArrowDown") {
										e.preventDefault();
										const delta = e.shiftKey ? 15 : 60;
										const minutes =
											current.hour * 60 +
											current.minute +
											(e.key === "ArrowDown" ? delta : -delta);
										const clamped = Math.max(
											0,
											Math.min(23 * 60 + 45, minutes),
										);
										setKeyboardSlot({
											day: dayIdx,
											hour: Math.floor(clamped / 60),
											minute: clamped % 60,
										});
									}
									if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
										e.preventDefault();
										const nextDay = Math.max(
											0,
											Math.min(6, dayIdx + (e.key === "ArrowRight" ? 1 : -1)),
										);
										setKeyboardSlot({
											day: nextDay,
											hour: current.hour,
											minute: current.minute,
										});
										const next = e.currentTarget.parentElement?.querySelector(
											`[data-day="${nextDay}"]`,
										) as HTMLElement | null;
										next?.focus();
									}
									if (e.key === "Enter") {
										e.preventDefault();
										onFillSlot(dayIdx, current.hour, current.minute);
									}
								}}
								onMouseMove={(e) => {
									// Don't show hover indicator while over a post card — preview there instead
									if ((e.target as HTMLElement).closest("[data-post-id]")) {
										setHoverSlot((prev) =>
											prev?.day === dayIdx ? null : prev,
										);
										return;
									}
									const rect = (
										e.currentTarget as HTMLElement
									).getBoundingClientRect();
									const y = e.clientY - rect.top;
									setHoverSlot({ day: dayIdx, y });
								}}
								onMouseLeave={() => {
									setHoverSlot((prev) => (prev?.day === dayIdx ? null : prev));
								}}
								onClick={(e) => {
									if ((e.target as HTMLElement).closest("[data-post-id]"))
										return;
									const rect = (
										e.currentTarget as HTMLElement
									).getBoundingClientRect();
									const y = e.clientY - rect.top;
									const { hour, minute } = yToTime(y);
									onFillSlot(dayIdx, hour, minute);
								}}
								className={`relative border-r border-border outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset ${
									isDropTarget
										? "bg-[color-mix(in_srgb,var(--color-oxblood)_5%,transparent)]"
										: today_
											? "bg-foreground/[0.012]"
											: "hover:bg-foreground/[0.01]"
								}`}
							>
								{aiHoursEnabled && <AITopHoursOverlay hours={bestHours} />}

								{bestHours.map((h) => {
									const hourStart = h * 60;
									const hourPosts = allDayPosts!.filter((post) => {
										const postStart = post.hour * 60 + post.minute;
										const postEnd = postStart + CARD_OCCUPIES_MINUTES;
										return postStart <= hourStart && postEnd > hourStart;
									});
									if (hourPosts.length > 0) return null;
									return (
										<div
											key={`slot-${h}`}
											className="absolute right-1.5 z-[5]"
											style={{ top: (h - START_HOUR) * HOUR_HEIGHT + 5 }}
										>
											<SlotIndicator
												variant={peakHours.includes(h) ? "peak" : "slot"}
											/>
										</div>
									);
								})}

								{/* Hour grid lines — hairlines every hour. Noon (12p) renders
                    slightly stronger to visually split AM / PM, a long-standing
                    calendar convention. */}
								{hourLabels.map((h) => {
									const isNoon = h === 12;
									return (
										<div
											key={h}
											className="absolute left-0 right-0 h-px pointer-events-none"
											style={{
												top: (h - START_HOUR) * HOUR_HEIGHT,
												backgroundColor: isNoon
													? "color-mix(in srgb, var(--color-foreground) 12%, transparent)"
													: "color-mix(in srgb, var(--color-foreground) 5%, transparent)",
											}}
											aria-hidden="true"
										/>
									);
								})}

								{/* Hover indicator — oxblood time line + chip follows the cursor.
                    Fades in on column enter so it doesn't snap into existence. */}
								{showHover &&
									hoverSlot &&
									(() => {
										const { hour, minute } = yToTime(hoverSlot.y);
										const y = timeToY(hour, minute);
										return (
											<div
												className="pointer-events-none absolute left-0 right-0 z-10"
												style={{ top: y }}
												aria-hidden="true"
											>
												<div
													className="absolute left-0 right-0 h-px"
													style={{
														backgroundColor:
															"color-mix(in srgb, var(--color-oxblood) 55%, transparent)",
													}}
												/>
												<div
													className="absolute left-1.5 -top-[9px] px-1.5 h-[18px] inline-flex items-center rounded font-mono text-[0.625rem] font-semibold tabular-nums shadow-[0_1px_2px_color-mix(in_srgb,var(--color-foreground)_4%,transparent)]"
													style={{
														color: "var(--color-oxblood)",
														backgroundColor:
															"color-mix(in srgb, var(--color-oxblood) 10%, var(--color-card))",
														border:
															"0.5px solid color-mix(in srgb, var(--color-oxblood) 34%, transparent)",
													}}
												>
													{formatHour(hour, minute)}
												</div>
											</div>
										);
									})()}

								{keyboardSlot?.day === dayIdx && (
									<div
										className="pointer-events-none absolute left-0 right-0 z-10"
										style={{
											top: timeToY(keyboardSlot.hour, keyboardSlot.minute),
										}}
										aria-hidden="true"
									>
										<div className="h-px bg-[var(--color-oxblood)]" />
										<div
											className="absolute left-1.5 -top-[9px] rounded px-1.5 font-mono text-[0.625rem] font-semibold tabular-nums"
											style={{
												color: "var(--color-oxblood)",
												backgroundColor:
													"color-mix(in srgb, var(--color-oxblood) 10%, var(--color-card))",
												border:
													"0.5px solid color-mix(in srgb, var(--color-oxblood) 34%, transparent)",
											}}
										>
											{formatHour(keyboardSlot.hour, keyboardSlot.minute)}
										</div>
									</div>
								)}

								{/* Drop indicator — oxblood line at hover y while dragging over this column */}
								{isDropTarget && dropHintY !== null && (
									<div
										className="absolute left-0 right-0 h-[2px] rounded-full pointer-events-none z-10"
										style={{
											top: dropHintY - 1,
											backgroundColor: "var(--color-oxblood)",
											boxShadow:
												"0 0 0 2px color-mix(in srgb, var(--color-oxblood) 18%, transparent)",
										}}
										aria-hidden="true"
									/>
								)}

								{isDropTarget &&
									dropHintY !== null &&
									(() => {
										const nearestPeak = peakHours
											.map((h) => ({
												hour: h,
												distance: Math.abs(timeToY(h, 0) - dropHintY),
											}))
											.sort((a, b) => a.distance - b.distance)[0];
										if (!nearestPeak || nearestPeak.distance > HOUR_HEIGHT / 2)
											return null;
										return (
											<MagnetGuide
												y={timeToY(nearestPeak.hour, 0)}
												label={formatHour(nearestPeak.hour, 0)}
											/>
										);
									})()}

								{/* Posts pinned to their time. Overlapping slots split into
                    side-by-side lanes via assignLanes() so cards never draw
                    on top of each other. Each card's horizontal slot is
                    computed from its lane / laneCount within its cluster. */}
								{laidPosts.map(({ post: p, lane, laneCount }) => {
									const widthPct = 100 / laneCount;
									const leftPct = lane * widthPct;
									return (
										<div
											key={p.id}
											className="absolute"
											style={{
												top: timeToY(p.hour, p.minute),
												height: CARD_HEIGHT,
												left: `calc(${leftPct}% + 4px)`,
												width: `calc(${widthPct}% - 8px)`,
											}}
										>
											<PostCard
												post={p}
												selected={selectedIds.has(p.id)}
												onClick={(e) => onCardClick(p, e)}
												onDragMove={onDragMove}
												onDragEnd={onDragEnd}
												onQuickMove={onQuickMove}
												riskLabels={riskLabelsByPostId[p.id] ?? []}
											/>
										</div>
									);
								})}

								{/* "+N more" pill — shown when the day has posts beyond the
                    visible cap. Sticky below the header row so it stays
                    reachable while scrolling WITHOUT occluding the day
                    number (header is semi-transparent bg-card; z-index
                    alone doesn't hide the pill through it). Opens the
                    day drawer. */}
								{overflowPosts.length > 0 && (
									<Button
										type="button"
										variant="outline"
										size="sm"
										onClick={(e) => {
											e.stopPropagation();
											setDrawerDay(dayIdx);
										}}
										className="sticky inset-x-1 top-[92px] z-[15] mt-2 h-[22px] w-[calc(100%-8px)] text-[0.65625rem] font-semibold tabular-nums text-primary"
										title={`${overflowPosts.length} more posts · open to list`}
										aria-label={`Show ${overflowPosts.length} more posts`}
									>
										+{overflowPosts.length} more
									</Button>
								)}

								{/* Current-time line — only on today's column */}
								{today_ && nowY !== null && (
									<div
										className="absolute left-0 right-0 pointer-events-none z-20"
										style={{ top: nowY }}
										aria-hidden="true"
									>
										<div
											className="absolute -left-1 top-[-4px] w-2 h-2 rounded-full"
											style={{ backgroundColor: "var(--color-oxblood)" }}
										/>
										<div
											className="h-[1.5px]"
											style={{ backgroundColor: "var(--color-oxblood)" }}
										/>
									</div>
								)}
							</div>
						);
					})}
				</div>
			</div>
			{drawerDay !== null && (
				<DayOverflowDrawer
					dayIdx={drawerDay}
					weekStart={weekStart}
					posts={postsByDay[drawerDay] ?? []}
					selectedIds={selectedIds}
					onClose={() => setDrawerDay(null)}
					onCardClick={onCardClick}
					onDragMove={onDragMove}
					onQuickMove={onQuickMove}
					riskLabelsByPostId={riskLabelsByPostId}
					onDragEnd={(postId, moved) => {
						// Close the drawer as soon as a drag results in a move, so the
						// rescheduled card lands cleanly and the grid regains focus.
						if (moved) setDrawerDay(null);
						onDragEnd(postId, moved);
					}}
				/>
			)}
		</NovaCard>
	);
}

/** Side drawer that lists every post for one day. Items are the same PostCard
 *  used inline, so clicks open the detail panel and drags reschedule the post
 *  onto a day column — no separate drag implementation. */
function DayOverflowDrawer({
	dayIdx,
	weekStart,
	posts,
	selectedIds,
	onClose,
	onCardClick,
	onDragMove,
	onQuickMove,
	riskLabelsByPostId,
	onDragEnd,
}: {
	dayIdx: number;
	weekStart: Date;
	posts: Post[];
	selectedIds: Set<string>;
	onClose: () => void;
	onCardClick: (post: Post, e: React.MouseEvent) => void;
	onDragMove: (x: number, y: number) => void;
	onQuickMove?:
		| ((
				post: Post,
				action: "minus-hour" | "plus-hour" | "tomorrow" | "next-peak",
		  ) => void)
		| undefined;
	riskLabelsByPostId: Record<string, string[]>;
	onDragEnd: (postId: string, moved: boolean) => void;
}) {
	if (typeof document === "undefined") return null;
	const date = new Date(weekStart);
	date.setDate(weekStart.getDate() + dayIdx);
	const dayLabel = date.toLocaleDateString(undefined, {
		weekday: "long",
		month: "short",
		day: "numeric",
	});
	return createPortal(
		<>
			{/* Backdrop — light scrim so the calendar is still visible for drag drops. */}
			<div
				onClick={onClose}
				className="fixed inset-0 bg-foreground/15 dark:bg-black/55"
				style={{ zIndex: Z.sheetBackdrop }}
			/>
			<aside
				role="dialog"
				// Non-modal so drag targets remain active across the calendar.
				aria-modal="false"
				aria-label={`${dayLabel} · ${posts.length} posts`}
				style={{
					position: "fixed",
					right: 0,
					top: 0,
					bottom: 0,
					width: 360,
					zIndex: Z.sheet,
				}}
				className="overflow-y-auto border-l border-border bg-card shadow-[-20px_0_40px_-20px_color-mix(in_srgb,var(--color-foreground)_18%,transparent)]"
			>
				<div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-5 py-4">
					<div className="min-w-0">
						<div className="text-[0.65625rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground mb-0.5">
							{dayLabel}
						</div>
						<div className="text-[0.9375rem] font-medium text-foreground tracking-[-0.01em] tabular-nums">
							{posts.length} {posts.length === 1 ? "post" : "posts"}
						</div>
					</div>
					<Button
						type="button"
						variant="ghost"
						size="icon"
						onClick={onClose}
						aria-label="Close day panel"
					>
						<X />
					</Button>
				</div>

				<div className="p-3 flex flex-col gap-2">
					<p className="text-[0.6875rem] text-muted-foreground leading-snug px-2 pb-1">
						Drag any card onto a day column to reschedule. Click to edit.
					</p>
					{posts.map((p) => (
						<div
							key={p.id}
							className="relative"
							style={{ height: CARD_HEIGHT }}
						>
							<PostCard
								post={p}
								selected={selectedIds.has(p.id)}
								onClick={(e) => onCardClick(p, e)}
								onDragMove={onDragMove}
								onDragEnd={onDragEnd}
								onQuickMove={onQuickMove}
								riskLabels={riskLabelsByPostId[p.id] ?? []}
							/>
						</div>
					))}
				</div>
			</aside>
		</>,
		document.body,
	);
}
