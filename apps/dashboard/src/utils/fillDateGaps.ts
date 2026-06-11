/**
 * Fill missing dates in a time-series array so charts render continuous X-axes.
 * Uses carry-forward for followers (last known value) and zero for engagement metrics.
 */
import { formatShortDate } from "./timezone";

interface TimeSeriesPoint {
	date: string;
	rawDate: Date;
	[key: string]: unknown;
}

const ZERO_FILL_KEYS = [
	"views",
	"likes",
	"replies",
	"reposts",
	"shares",
	"engagementRate",
	"postsCount",
] as const;

const CARRY_FORWARD_KEYS = [
	"followers",
	"followersCount",
] as const;

export function fillDateGaps<T extends TimeSeriesPoint>(
	data: T[],
	start: Date,
	end: Date,
): T[] {
	// Build a map of existing data keyed by date string (day precision)
	const dataByDay = new Map<string, T>();
	for (const point of data) {
		const dayKey = toDateKey(point.rawDate);
		dataByDay.set(dayKey, point);
	}

	const result: T[] = [];
	const lastCarry: Record<string, unknown> = {};

	// Seed carry-forward from the FIRST real data point so days before it
	// show the earliest known value instead of 0 (avoids flat-at-zero charts)
	const firstPoint = data[0];
	for (const key of CARRY_FORWARD_KEYS) {
		lastCarry[key] =
			firstPoint && key in firstPoint && firstPoint[key] != null
				? firstPoint[key]
				: 0;
	}

	// Walk every day in the range (local-time based — rawDate uses local midnight)
	const cursor = new Date(start.getFullYear(), start.getMonth(), start.getDate());
	const endDay = new Date(end.getFullYear(), end.getMonth(), end.getDate(), 23, 59, 59, 999);

	while (cursor <= endDay) {
		const dayKey = toDateKey(cursor);
		const existing = dataByDay.get(dayKey);

		if (existing) {
			// Update carry-forward values from real data
			for (const key of CARRY_FORWARD_KEYS) {
				if (key in existing && existing[key] != null) {
					lastCarry[key] = existing[key];
				}
			}
			result.push(existing);
		} else {
			// Create a zero-filled point for this missing date
			const fill: Record<string, unknown> = {
				date: formatShortDate(cursor),
				rawDate: new Date(cursor),
			};
			for (const key of ZERO_FILL_KEYS) {
				fill[key] = 0;
			}
			for (const key of CARRY_FORWARD_KEYS) {
				fill[key] = lastCarry[key] ?? 0;
			}
			result.push(fill as T);
		}

		cursor.setDate(cursor.getDate() + 1);
	}

	return result;
}

function toDateKey(d: Date): string {
	return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}
