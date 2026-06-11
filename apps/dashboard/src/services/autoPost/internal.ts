/**
 * Auto-Post Service — internal helpers shared across submodules.
 * NOT exported from the barrel.
 */

import { getUserIdAsync, supabase } from "../api/shared";

// Helper to get current user ID for Supabase
export const getSupabaseUserId = async (): Promise<string | null> => {
	try {
		return await getUserIdAsync();
	} catch {
		return null;
	}
};

// Helper to get browser timezone
export const getBrowserTimezone = (): string => {
	try {
		return Intl.DateTimeFormat().resolvedOptions().timeZone;
	} catch {
		return "UTC";
	}
};

export function isValidTimezone(tz: string): boolean {
	try {
		Intl.DateTimeFormat(undefined, { timeZone: tz });
		return true;
	} catch {
		return false;
	}
}

/**
 * Get current hour in a specific timezone
 */
export const getCurrentHourInTimezone = (timezone: string): number => {
	const tz = isValidTimezone(timezone) ? timezone : "UTC";
	try {
		const formatter = new Intl.DateTimeFormat("en-US", {
			timeZone: tz,
			hour: "numeric",
			hour12: false,
		});
		const hour = parseInt(formatter.format(new Date()), 10);
		return hour === 24 ? 0 : hour;
	} catch {
		return new Date().getHours();
	}
};

/**
 * Get current day of week in a specific timezone (0 = Sunday, 6 = Saturday)
 */
export const getCurrentDayInTimezone = (timezone: string): number => {
	const tz = isValidTimezone(timezone) ? timezone : "UTC";
	try {
		const formatter = new Intl.DateTimeFormat("en-US", {
			timeZone: tz,
			weekday: "short",
		});
		const dayStr = formatter.format(new Date());
		const dayMap: Record<string, number> = {
			Sun: 0,
			Mon: 1,
			Tue: 2,
			Wed: 3,
			Thu: 4,
			Fri: 5,
			Sat: 6,
		};
		return dayMap[dayStr] ?? new Date().getDay();
	} catch {
		return new Date().getDay();
	}
};

/**
 * Calculate a Date object for a specific hour in a timezone
 * Used to schedule posts at the right time regardless of server timezone
 */
export const getDateForHourInTimezone = (
	hour: number,
	timezone: string,
	addDays: number = 0,
): Date => {
	const tz = isValidTimezone(timezone) ? timezone : "UTC";
	const now = new Date();

	// Get current date parts in target timezone
	const formatter = new Intl.DateTimeFormat("en-US", {
		timeZone: tz,
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
	});
	const parts = formatter.formatToParts(now);
	const year = parseInt(
		parts.find((p) => p.type === "year")?.value || "2024",
		10,
	);
	const month =
		parseInt(parts.find((p) => p.type === "month")?.value || "1", 10) - 1;
	const day =
		parseInt(parts.find((p) => p.type === "day")?.value || "1", 10) + addDays;

	// Create date at the target hour in the target timezone
	// We use an iterative approach to handle DST and half-hour offsets
	let guess = new Date(Date.UTC(year, month, day, hour));

	// Get what hour our guess represents in the target timezone
	const getHourInTz = (d: Date): number => {
		return (
			parseInt(
				new Intl.DateTimeFormat("en-US", {
					timeZone: tz,
					hour: "numeric",
					hour12: false,
				}).format(d),
				10,
			) % 24
		);
	};

	// Adjust for timezone offset (iterate to handle DST edge cases)
	for (let i = 0; i < 3; i++) {
		const actualHour = getHourInTz(guess);
		if (actualHour === hour) break;
		const diff = hour - actualHour;
		guess = new Date(guess.getTime() + diff * 60 * 60 * 1000);
	}

	return guess;
};

/**
 * Get the workspace ID for the current user
 * (In production, this would come from workspace context)
 */
export const getWorkspaceId = async (): Promise<string | null> => {
	const userId = await getSupabaseUserId();
	if (!userId) return null;

	// Get user's default workspace (first one they own)
	const { data, error } = await supabase
		.from("workspaces")
		.select("id")
		.eq("owner_id", userId)
		.limit(1)
		.maybeSingle();

	if (error || !data) return null;
	return data.id;
};

/**
 * Resolve workspaceId, throwing if none can be found.
 * Use in top-level callers that cannot proceed without a workspace.
 */
export async function requireWorkspaceId(
	workspaceId?: string,
): Promise<string> {
	const id = workspaceId || (await getWorkspaceId());
	if (!id) throw new Error("No workspace found");
	return id;
}
