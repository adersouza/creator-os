import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuthUser } from "@/hooks/useAuthUser";
import { getUserSetting, upsertUserSetting } from "@/services/userSettingsService";
import { supabase } from "@/services/supabase";

const SMART_LINK_CLICK_GOAL_KEY = "smart_link_click_goal";

export interface SmartLinkClickGoal {
	targetClicks: number;
	periodDays: number;
	enabled: boolean;
}

export interface SmartLinkClickSummary {
	totalClicks: number;
	periodDays: number;
	topLink: {
		id: string;
		code: string;
		title: string | null;
		clicks: number;
	} | null;
	linkCount: number;
	isLoading: boolean;
	hasError: boolean;
}

const DEFAULT_GOAL: SmartLinkClickGoal = {
	targetClicks: 200,
	periodDays: 30,
	enabled: true,
};

function normalizeGoal(value: unknown): SmartLinkClickGoal {
	if (!value || typeof value !== "object" || Array.isArray(value)) {
		return DEFAULT_GOAL;
	}
	const raw = value as Partial<SmartLinkClickGoal>;
	const targetClicks =
		typeof raw.targetClicks === "number" && Number.isFinite(raw.targetClicks)
			? Math.max(1, Math.round(raw.targetClicks))
			: DEFAULT_GOAL.targetClicks;
	const periodDays =
		typeof raw.periodDays === "number" && Number.isFinite(raw.periodDays)
			? Math.min(90, Math.max(1, Math.round(raw.periodDays)))
			: DEFAULT_GOAL.periodDays;
	return {
		targetClicks,
		periodDays,
		enabled: raw.enabled !== false,
	};
}

export function useSmartLinkClickGoal() {
	const authUser = useAuthUser();
	const userId = authUser?.id ?? null;
	const [goal, setGoalState] = useState<SmartLinkClickGoal>(DEFAULT_GOAL);
	const [isLoading, setIsLoading] = useState(true);
	const [hasError, setHasError] = useState(false);

	useEffect(() => {
		let cancelled = false;
		if (!userId) {
			setIsLoading(false);
			return;
		}
		setIsLoading(true);
		setHasError(false);
		getUserSetting(userId, SMART_LINK_CLICK_GOAL_KEY)
			.then((value) => {
				if (cancelled) return;
				setGoalState(normalizeGoal(value));
			})
			.catch(() => {
				if (cancelled) return;
				setHasError(true);
			})
			.finally(() => {
				if (!cancelled) setIsLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [userId]);

	async function saveGoal(next: SmartLinkClickGoal) {
		const normalized = normalizeGoal(next);
		setGoalState(normalized);
		if (!userId) return;
		await upsertUserSetting(userId, SMART_LINK_CLICK_GOAL_KEY, normalized);
	}

	return { goal, saveGoal, isLoading, hasError };
}

export function useSmartLinkClickSummary(periodDays: number): SmartLinkClickSummary {
	const authUser = useAuthUser();
	const userId = authUser?.id ?? null;
	const safePeriodDays = Math.min(90, Math.max(1, Math.round(periodDays || 30)));

	const { data, isPending, isError } = useQuery({
		queryKey: ["smartLinkClickSummary", userId, safePeriodDays],
		enabled: !!userId,
		staleTime: 5 * 60 * 1000,
		refetchOnWindowFocus: false,
		queryFn: async () => {
			const { data: links, error: linksError } = await supabase
				.from("smart_links")
				.select("id, code, title")
				.eq("user_id", userId)
				.limit(1000);
			if (linksError) throw linksError;

			const linkRows = (links ?? []) as Array<{
				id: string;
				code: string | null;
				title: string | null;
			}>;
			if (linkRows.length === 0) {
				return { totalClicks: 0, topLink: null, linkCount: 0 };
			}

			const since = new Date();
			since.setDate(since.getDate() - safePeriodDays);

			const { data: clicks, error: clicksError } = await supabase
				.from("smart_link_clicks")
				.select("smart_link_id")
				.in(
					"smart_link_id",
					linkRows.map((link) => link.id),
				)
				.gte("clicked_at", since.toISOString())
				.limit(10000);
			if (clicksError) throw clicksError;

			const clicksByLink = new Map<string, number>();
			for (const click of (clicks ?? []) as Array<{ smart_link_id: string | null }>) {
				if (!click.smart_link_id) continue;
				clicksByLink.set(
					click.smart_link_id,
					(clicksByLink.get(click.smart_link_id) ?? 0) + 1,
				);
			}

			let totalClicks = 0;
			let topLink: SmartLinkClickSummary["topLink"] = null;
			for (const link of linkRows) {
				const linkClicks = clicksByLink.get(link.id) ?? 0;
				totalClicks += linkClicks;
				if (!topLink || linkClicks > topLink.clicks) {
					topLink = {
						id: link.id,
						code: link.code ?? "",
						title: link.title,
						clicks: linkClicks,
					};
				}
			}

			return {
				totalClicks,
				topLink: topLink && topLink.clicks > 0 ? topLink : null,
				linkCount: linkRows.length,
			};
		},
	});

	return {
		totalClicks: data?.totalClicks ?? 0,
		periodDays: safePeriodDays,
		topLink: data?.topLink ?? null,
		linkCount: data?.linkCount ?? 0,
		isLoading: !!userId && isPending,
		hasError: !!userId && isError,
	};
}
