/**
 * Instagram-specific API operations
 */

import { mapInstagramAccountRow } from "@/src/lib/mappers.js";
import type { InstagramAccount } from "@/types/index.js";
import { getUserIdAsync, logger, supabase, withRetry } from "./shared.js";

interface InstagramInsights {
	impressions?: number | undefined;
	reach?: number | undefined;
	profileViews?: number | undefined;
	followerCount?: number | undefined;
	accountsEngaged?: number | undefined;
	totalInteractions?: number | undefined;
	websiteClicks?: number | undefined;
	reposts?: number | undefined;
	nonFollowerReachPct?: number | null | undefined;
}

interface InstagramInsightsResponse {
	success?: boolean | undefined;
	insights?: InstagramInsights | undefined;
}

interface InstagramPostInsightsResponse {
	success?: boolean | undefined;
	[key: string]: unknown;
}

function getInsightsPayload(
	value: InstagramInsightsResponse | Record<string, never>,
): InstagramInsights {
	if ("insights" in value && value.insights) {
		return value.insights;
	}

	return value as InstagramInsights;
}

export async function getInstagramAccounts(): Promise<InstagramAccount[]> {
	const userId = await getUserIdAsync();

	const { data, error } = (await withRetry(
		async () => {
			return supabase
				.from("instagram_accounts")
				.select("*")
				.eq("user_id", userId)
				.order("created_at", { ascending: false })
				.limit(500);
		},
		{ name: "getInstagramAccounts" },
	)) as { data: Record<string, unknown>[] | null; error: unknown };

	if (error) {
		logger.error("Failed to fetch Instagram accounts from Supabase:", error);
		throw error;
	}

	return (data || []).map(mapInstagramAccountRow);
}

export async function getInstagramInsights(
	accountId: string,
	period: "day" | "week" | "days_28" = "day",
): Promise<InstagramInsightsResponse | Record<string, never>> {
	// When "ALL", fetch insights for each IG account and aggregate
	if (accountId === "ALL") {
		try {
			const igAccounts = await getInstagramAccounts();
			if (!igAccounts.length) return {};
			const results = await Promise.allSettled(
				igAccounts.map((a) => getInstagramInsights(a.id, period)),
			);
			const fulfilled = results
				.filter(
					(
						r,
					): r is PromiseFulfilledResult<
						InstagramInsightsResponse | Record<string, never>
					> => r.status === "fulfilled",
				)
				.map((r) => r.value)
				.filter((v) => v && v.success !== false);
			if (!fulfilled.length) return {};
			// Sum numeric insight fields across all accounts
			const merged: InstagramInsights = {};
			const numericKeys: Array<keyof InstagramInsights> = [
				"impressions",
				"reach",
				"profileViews",
				"followerCount",
				"accountsEngaged",
				"totalInteractions",
				"websiteClicks",
				"reposts",
			];
			for (const key of numericKeys) {
				const sum = fulfilled.reduce((s, r) => {
					const insights = getInsightsPayload(r);
					return s + (insights[key] || 0);
				}, 0);
				merged[key] = sum;
			}
			// nonFollowerReachPct is a ratio — weighted average by reach
			const totalReach = merged.reach || 1;
			const weightedNonFollower = fulfilled.reduce((s, r) => {
				const ins = getInsightsPayload(r);
				return s + (ins.nonFollowerReachPct || 0) * (ins.reach || 0);
			}, 0);
			merged.nonFollowerReachPct =
				totalReach > 0 ? weightedNonFollower / totalReach : null;
			return { success: true, insights: merged };
		} catch {
			return {};
		}
	}

	if (!accountId) {
		return {};
	}

	const {
		data: { session },
	} = await supabase.auth.getSession();

	const response = await fetch(
		"/api/instagram/insights?action=account-insights",
		{
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session?.access_token}`,
			},
			body: JSON.stringify({ accountId, period }),
		},
	);

	if (!response.ok) {
		const error = await response.json().catch(() => ({}));
		throw new Error(error.error || "Failed to fetch Instagram insights");
	}

	return (await response.json()) as InstagramInsightsResponse;
}

export async function getInstagramPostInsights(
	mediaId: string,
	accountId: string,
): Promise<InstagramPostInsightsResponse | Record<string, never>> {
	if (!accountId || accountId === "ALL") {
		return {};
	}

	const {
		data: { session },
	} = await supabase.auth.getSession();

	const response = await fetch("/api/instagram/insights?action=post-insights", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({ mediaId, accountId }),
	});

	if (!response.ok) {
		const error = await response.json().catch(() => ({}));
		throw new Error(error.error || "Failed to fetch Instagram post insights");
	}

	return (await response.json()) as InstagramPostInsightsResponse;
}
