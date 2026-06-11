// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useEffect, useState } from "react";
import { supabase } from "@/services/supabase";

export interface IgBenchmark {
	percentile: number;
	median: number;
	yours: number;
	cohortSize: number;
	note: string;
}

interface State {
	data: IgBenchmark | null;
	loading: boolean;
	/** True when the backend returned a live benchmark for this IG account. */
	hasRealData: boolean;
}

const memoryCache = new Map<string, IgBenchmark>();

interface BenchmarkResponse {
	benchmarks: {
		competitorCount: number;
		averages: { engagementRate: number };
		userAccount: { engagementRate: number } | null;
		competitors: Array<{ engagementRate: number }>;
	} | null;
}

function computePercentile(mine: number, cohort: number[]): number {
	if (cohort.length === 0) return 50;
	const below = cohort.filter((c) => c < mine).length;
	return Math.round((below / cohort.length) * 100);
}

function median(values: number[]): number {
	if (values.length === 0) return 0;
	const sorted = [...values].sort((a, b) => a - b);
	const mid = Math.floor(sorted.length / 2);
	return sorted.length % 2
		? sorted[mid]!
		: (sorted[mid - 1]! + sorted[mid]!) / 2;
}

function noteFor(percentile: number, cohortSize: number): string {
	const cohortLabel = `${cohortSize} tracked ${cohortSize === 1 ? "competitor" : "competitors"}`;
	if (percentile >= 75)
		return `Top quartile — outperforming ${percentile}% of ${cohortLabel}.`;
	if (percentile >= 50)
		return `Above median — ahead of ${percentile}% of ${cohortLabel}.`;
	if (percentile >= 25)
		return `Below median — trailing ${100 - percentile}% of ${cohortLabel}.`;
	return `Bottom quartile vs ${cohortLabel}. Time to experiment with format.`;
}

/**
 * Per-IG-account competitor percentile via the Juno33
 * `/api/competitors?action=ig-benchmarks` endpoint. Returns hasRealData=false
 * when the account has no tracked competitors, the call errors, or the scope
 * isn't a concrete IG account. Consumers should fall back to synthetic copy.
 */
export function useIgBenchmarks(accountId: string | null): State {
	const canFetch = Boolean(accountId);
	const cacheKey = accountId ?? "";
	const [state, setState] = useState<State>({
		data:
			cacheKey && memoryCache.has(cacheKey) ? memoryCache.get(cacheKey)! : null,
		loading: canFetch && !memoryCache.has(cacheKey),
		hasRealData: canFetch && memoryCache.has(cacheKey),
	});

	useEffect(() => {
		if (!canFetch) {
			setState({ data: null, loading: false, hasRealData: false });
			return;
		}
		const cached = memoryCache.get(cacheKey);
		if (cached) {
			setState({ data: cached, loading: false, hasRealData: true });
			return;
		}

		let cancelled = false;
		setState((s) => ({ ...s, loading: true }));

		(async () => {
			try {
				const {
					data: { session },
				} = await supabase.auth.getSession();
				if (!session?.access_token) throw new Error("Not authenticated");

				const response = await fetch(
					`/api/competitors?action=ig-benchmarks&accountId=${encodeURIComponent(cacheKey)}`,
					{
						method: "GET",
						headers: { Authorization: `Bearer ${session.access_token}` },
					},
				);
				if (!response.ok) throw new Error(`Status ${response.status}`);

				const body = await response.json();
				const payload = (body?.data ?? body) as BenchmarkResponse | null;
				const benchmarks = payload?.benchmarks;
				if (cancelled) return;
				if (!benchmarks?.userAccount || benchmarks.competitors.length === 0) {
					setState({ data: null, loading: false, hasRealData: false });
					return;
				}

				const cohort = benchmarks.competitors.map(
					(c) => Number(c.engagementRate) || 0,
				);
				const yours = Number(benchmarks.userAccount.engagementRate) || 0;
				const percentile = computePercentile(yours, cohort);
				const med = median(cohort);
				const data: IgBenchmark = {
					percentile,
					median: Math.round(med * 100) / 100,
					yours: Math.round(yours * 100) / 100,
					cohortSize: benchmarks.competitorCount,
					note: noteFor(percentile, benchmarks.competitorCount),
				};

				memoryCache.set(cacheKey, data);
				setState({ data, loading: false, hasRealData: true });
			} catch {
				if (cancelled) return;
				setState({ data: null, loading: false, hasRealData: false });
			}
		})();

		return () => {
			cancelled = true;
		};
	}, [cacheKey, canFetch]);

	return state;
}
