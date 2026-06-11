/* =========================================================================
   Calendar — shared types, constants, and helpers shared across sub-components.
   Extracted from src/pages/Calendar.tsx verbatim to preserve behavior.
   ========================================================================= */

export type ViewMode = "week" | "month" | "list" | "portfolio" | "streaks";
export type Platform = "threads" | "instagram";
export type Status = "draft" | "scheduled" | "published" | "failed" | "review";

export const UNASSIGNED_COLOR = "var(--color-health-idle)";
export const UNASSIGNED_GROUP_ID = "unassigned";
/** Queue-health target — "14 days of content". */
export const QUEUE_TARGET_DAYS = 14;

export const STATUS_STYLE: Record<
	Status,
	{ label: string; color: string; bg: string }
> = {
	draft: {
		label: "Draft",
		color: "var(--color-warning)",
		bg: "color-mix(in srgb, var(--color-warning) 12%, transparent)",
	},
	scheduled: {
		label: "Scheduled",
		color: "var(--color-ink)",
		bg: "color-mix(in srgb, var(--color-ink) 8%, transparent)",
	},
	published: {
		label: "Published",
		color: "var(--color-health-good)",
		bg: "color-mix(in srgb, var(--color-health-good) 12%, transparent)",
	},
	failed: {
		label: "Failed",
		color: "var(--color-critical)",
		bg: "color-mix(in srgb, var(--color-critical) 12%, transparent)",
	},
	review: {
		label: "In Review",
		color: "var(--color-vale)",
		bg: "color-mix(in srgb, var(--color-vale) 14%, transparent)",
	},
};

export interface Post {
	id: string;
	accountId: string | null;
	threadsPostId?: string | null | undefined;
	/** Day index 0..6 for current week (Mon..Sun) */
	day: number;
	/** Hour (0..23) */
	hour: number;
	/** Minute (0..59) for precise sort */
	minute: number;
	title: string;
	account: string;
	groupId: string;
	groupName: string;
	groupColor: string;
	platform: Platform;
	status: Status;
	instagramLoginType?: string | null | undefined;
	instagramPublishingQuota?:
		| {
				usage: number;
				limit: number;
				remaining: number;
				windowHours: number;
		  }
		| undefined;
	mediaCount?: number | undefined;
	mediaUrls?: string[] | undefined;
	/** First media URL — rendered as a tiny thumbnail on the card when present. */
	thumbnailUrl?: string | undefined;
	permalink?: string | null | undefined;
	publishedAt?: string | null | undefined;
	viewsCount?: number | null | undefined;
	likesCount?: number | null | undefined;
	repliesCount?: number | null | undefined;
	sharesCount?: number | null | undefined;
	igViews?: number | null | undefined;
	igCommentCount?: number | null | undefined;
	igReach?: number | null | undefined;
	igSaved?: number | null | undefined;
	igShares?: number | null | undefined;
	metadata?: Record<string, unknown> | null | undefined;
	campaignFactory?:
		| import("@/lib/campaignFactory").CampaignFactoryMetadata
		| null
		| undefined;
	campaignFactoryReuse?:
		| import("@/lib/campaignFactory").CampaignFactoryReuseCounts
		| undefined;
	createdAt?: string | null | undefined;
	igMediaType?: string | null | undefined;
	mediaType?: string | null | undefined;
	isUnscheduledDraft?: boolean | undefined;
}

export const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const DAY_NAMES_LONG = [
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
	"Sunday",
];

/* ---- Time-axis constants for Week view ---- */
export const START_HOUR = 0; // full day visible; card scrolls internally
export const END_HOUR = 24; // midnight (exclusive)
export const HOUR_HEIGHT = 56; // pixels per hour
export const VISIBLE_HOURS = END_HOUR - START_HOUR;
export const CALENDAR_HEIGHT = VISIBLE_HOURS * HOUR_HEIGHT;
export const CARD_HEIGHT = 50; // fits within one hour slot
/** Max lanes a cluster of overlapping posts can split into before we cap + overflow. */
export const MAX_LANES_PER_CLUSTER = 3;
/** Approx minutes a card "occupies" — used for overlap math. CARD_HEIGHT / HOUR_HEIGHT × 60. */
export const CARD_OCCUPIES_MINUTES = Math.ceil(
	(CARD_HEIGHT / HOUR_HEIGHT) * 60,
);
export const MIN_DROP_MINUTE = START_HOUR * 60;
export const MAX_DROP_MINUTE = (END_HOUR - 1) * 60 + 45;

/** Per-day visible cap. Beyond this we show a "+N more" pill that opens a
 *  side drawer listing every post for that day. Items in the drawer keep the
 *  same drag-to-reschedule behaviour as inline cards. */
export const MAX_VISIBLE_PER_DAY = 8;

/** Where the calendar scrolls to on mount — peak posting windows start here. */
export const INITIAL_SCROLL_HOUR = 7;
/** Max visible height inside the card (calendar body scrolls past this). */
export const CALENDAR_VIEWPORT = 680;
/** Extra pixels after the last hour so late-night cards (up to 11:45p + CARD_HEIGHT)
 *  don't clip. Kept tight so the user doesn't scroll into a huge dead zone. */
export const CALENDAR_BOTTOM_BUFFER = 16;

/** Pixel y-offset for a given time within the day column. */
export function timeToY(hour: number, minute: number): number {
	const effectiveHour = Math.max(
		START_HOUR,
		Math.min(END_HOUR - 0.25, hour + minute / 60),
	);
	return (effectiveHour - START_HOUR) * HOUR_HEIGHT;
}
/** Convert a y-offset within the day column back to a snapped time (15-min grid). */
export function yToTime(y: number): { hour: number; minute: number } {
	const rawMinutes = START_HOUR * 60 + (y / HOUR_HEIGHT) * 60;
	const clamped = Math.max(
		MIN_DROP_MINUTE,
		Math.min(MAX_DROP_MINUTE, rawMinutes),
	);
	const snapped = Math.round(clamped / 15) * 15;
	return { hour: Math.floor(snapped / 60), minute: snapped % 60 };
}
/** Short hour label for the gutter: "6a", "12p", "11p". */
export function formatHourLabel(h: number): string {
	if (h === 0 || h === 24) return "12a";
	if (h === 12) return "12p";
	return h < 12 ? `${h}a` : `${h - 12}p`;
}

export function formatHour(h: number, m: number): string {
	const suffix = h >= 12 ? "p" : "a";
	const hh = h === 0 ? 12 : h > 12 ? h - 12 : h;
	const mm = m === 0 ? "" : `:${m.toString().padStart(2, "0")}`;
	return `${hh}${mm}${suffix}`;
}

export interface GroupOption {
	id: string;
	name: string;
	color: string;
}

export interface QueueHealthRow {
	id: string;
	name: string;
	color: string;
	daysOfContent: number;
	postsCount: number;
}

/** Delay before hover preview opens. Long enough to not fire while scanning. */
export const HOVER_PREVIEW_DELAY_MS = 450;

/** Drag threshold in pixels. Movement below this = click; above = drag. */
export const DRAG_THRESHOLD = 5;
/** Long-press duration. Hold without moving = "lift" mode (reorder affordance). */
export const LONG_PRESS_MS = 350;
/** Movement tolerance while the hold timer is running — larger than DRAG_THRESHOLD
 *  so tiny jitter during "holding" doesn't cancel the long-press intent. */
export const HOLD_JITTER_TOLERANCE = 10;
