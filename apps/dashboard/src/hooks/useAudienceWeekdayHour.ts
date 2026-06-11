// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/services/supabase";
import { useAuthUser } from "@/hooks/useAuthUser";

interface PostRow {
	published_at: string | null;
	views_count: number | null;
	ig_views: number | null;
	ig_reach: number | null;
}

export interface WeekdayHourMatrix {
	/** 7 × 24 normalized intensity matrix. matrix[dow][hour] in 0..1.
	 *  dow: 0 = Sunday … 6 = Saturday. hour: 0..23 (local time of viewer). */
	matrix: number[][];
	/** Peak cell (dow, hour) by absolute intensity. -1/-1 if empty. */
	peakDow: number;
	peakHour: number;
	/** Total posts sampled across the window. */
	postsSampled: number;
	isLoading: boolean;
	hasError: boolean;
}

const EMPTY: WeekdayHourMatrix = {
	matrix: Array.from({ length: 7 }, () => Array(24).fill(0)),
	peakDow: -1,
	peakHour: -1,
	postsSampled: 0,
	isLoading: false,
	hasError: false,
};

const WINDOW_DAYS = 30;
const POST_SAMPLE_LIMIT = 2000;

/**
 * Audience weekday-hour density — derived from historical post reach in
 * the last 30 days. Used by the AudienceOnlineTile heatmap (mockup #6).
 *
 * Why historical instead of `ig_online_followers`? Meta's online_followers
 * endpoint returns hour-of-day only, no weekday axis. Past post reach by
 * weekday×hour is a structurally honest proxy for "when does your
 * audience engage?" — the mockup's labeled intent ("7-day median").
 */
export function useAudienceWeekdayHour(
	accountIds?: string[] | null,
): WeekdayHourMatrix {
	const auth = useAuthUser();
	const userId = auth?.id ?? null;
	const scopedIds = accountIds?.filter(Boolean) ?? [];
	const scopedKey = Array.isArray(accountIds)
		? scopedIds.slice().sort().join(",")
		: null;

	const { data, isPending, isError } = useQuery({
		queryKey: ["audienceWeekdayHour", userId, scopedKey],
		enabled: !!userId,
		staleTime: 5 * 60 * 1000,
		queryFn: async (): Promise<
			Omit<WeekdayHourMatrix, "isLoading" | "hasError">
		> => {
			if (Array.isArray(accountIds) && scopedIds.length === 0) return EMPTY;
			const since = new Date();
			since.setDate(since.getDate() - WINDOW_DAYS);
			let query = supabase
				.from("posts")
				.select("published_at, views_count, ig_views, ig_reach")
				.eq("user_id", userId)
				.gte("published_at", since.toISOString())
				.not("published_at", "is", null);

			if (scopedIds.length > 0) {
				const ids = scopedIds.join(",");
				query = query.or(
					`account_id.in.(${ids}),instagram_account_id.in.(${ids})`,
				);
			}

			const { data, error } = await query.limit(POST_SAMPLE_LIMIT);
			if (error) throw error;

			const totals = Array.from({ length: 7 }, () => Array(24).fill(0));
			const counts = Array.from({ length: 7 }, () => Array(24).fill(0));
			let sampled = 0;

			for (const row of (data ?? []) as PostRow[]) {
				if (!row.published_at) continue;
				const d = new Date(row.published_at);
				const dow = d.getDay();
				const hour = d.getHours();
				const reach = row.ig_reach ?? row.ig_views ?? row.views_count ?? 0;
				if (reach <= 0) continue;
				totals[dow]![hour] += reach;
				counts[dow]![hour] += 1;
				sampled += 1;
			}

			// Average reach per cell, then normalize to 0..1 across the whole matrix.
			let max = 0;
			const averaged = totals.map((row, dow) =>
				row.map((sum, h) => {
					const c = counts[dow]![h];
					const avg = c > 0 ? sum / c : 0;
					if (avg > max) max = avg;
					return avg;
				}),
			);
			const matrix = averaged.map((row) =>
				row.map((v) => (max > 0 ? v / max : 0)),
			);

			let peakDow = -1;
			let peakHour = -1;
			let peakVal = 0;
			for (let d = 0; d < 7; d += 1) {
				for (let h = 0; h < 24; h += 1) {
					if (matrix[d]![h]! > peakVal) {
						peakVal = matrix[d]![h]!;
						peakDow = d;
						peakHour = h;
					}
				}
			}

			return {
				matrix,
				peakDow,
				peakHour,
				postsSampled: sampled,
			};
		},
	});

	if (!data)
		return { ...EMPTY, isLoading: isPending, hasError: !!userId && isError };
	return { ...data, isLoading: isPending, hasError: false };
}
