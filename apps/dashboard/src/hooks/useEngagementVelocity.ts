// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useEffect, useState } from "react";
import { supabase } from "@/services/supabase";
import { useAuthUser } from "@/hooks/useAuthUser";
import { createHookCache } from "@/hooks/_hookCache";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";

export interface VelocitySample {
	postId: string;
	publishedAt: string;
	hoursSincePublish: number;
	/** Views at the first metric snapshot for this post. */
	viewsAtSnapshot: number;
	/** views / hoursSincePublish — clamped at 1h floor. */
	viewsPerHour: number;
}

export interface VelocityState {
	/** First-hour velocity samples — one per post that has a snapshot
	 *  taken within `maxAgeHours` of publish. */
	samples: VelocitySample[];
	p25: number | null;
	p50: number | null;
	p75: number | null;
	/** Highest single-post velocity in the set. */
	max: number | null;
	isLoading: boolean;
	hasError: boolean;
}

const EMPTY: VelocityState = {
	samples: [],
	p25: null,
	p50: null,
	p75: null,
	max: null,
	isLoading: true,
	hasError: false,
};

interface PostRow {
	id: string;
	published_at: string | null;
	platform: string | null;
	account_id: string | null;
	instagram_account_id: string | null;
}

interface MetricRow {
	post_id: string;
	snapshot_at: string;
	views_count: number | null;
}

const cache = createHookCache<VelocityState>();
const cacheKey = (
	user: string | null,
	days: number,
	platform: "all" | "threads" | "instagram",
	scopedAccount: AccountScopeValue | null,
	maxAgeHours: number,
	accountIdsKey: string | null,
	groupId: string | null,
) =>
	user
		? `${user}:${days}:${platform}:${scopedAccount?.id ?? accountIdsKey ?? groupId ?? "fleet"}:${maxAgeHours}`
		: null;

function quantile(sorted: number[], q: number): number | null {
	if (sorted.length === 0) return null;
	const i = (sorted.length - 1) * q;
	const lo = Math.floor(i);
	const hi = Math.ceil(i);
	if (lo === hi) return sorted[lo]!;
	return sorted[lo]! + (sorted[hi]! - sorted[lo]!) * (i - lo);
}

export interface UseEngagementVelocityArgs {
	/** Recent posts window in days. */
	days: number;
	platform: "all" | "threads" | "instagram";
	scopedAccount?: AccountScopeValue | null | undefined;
	accountIds?: string[] | undefined;
	groupId?: string | null | undefined;
	/** Max hours-since-publish for the first snapshot to count as "first-hour". */
	maxAgeHours?: number | undefined;
}

/**
 * First-hour engagement velocity across recent posts. For each published
 * post in the window, takes the earliest `post_metric_history` snapshot
 * within `maxAgeHours` of publish and computes `views / hours`. Returns
 * the per-post samples plus p25/p50/p75 — the central read for first-hour
 * velocity distribution.
 *
 * Direct Supabase query — no new endpoint required. The post-metrics-history
 * handler also computes velocity but only per-account; this aggregates
 * across the fleet (or a scoped account).
 */
// Signature pattern: options object because velocity combines period, platform, and tuning knobs.
export function useEngagementVelocity(
	args: UseEngagementVelocityArgs,
): VelocityState {
	const {
		days,
		platform,
		scopedAccount = null,
		accountIds,
		groupId = null,
		maxAgeHours = 6,
	} = args;
	const authUser = useAuthUser();
	const userKey = authUser?.id ?? null;
	const accountIdsKey =
		accountIds && accountIds.length > 0 ? accountIds.join(",") : null;
	const [state, setState] = useState<VelocityState>(() => {
		const cached = cache.get(
			cacheKey(
				userKey,
				days,
				platform,
				scopedAccount,
				maxAgeHours,
				accountIdsKey,
				groupId,
			),
		);
		return cached ? { ...cached, isLoading: false } : EMPTY;
	});

	useEffect(() => {
		let cancelled = false;
		if (!authUser) return;

		const key = cacheKey(
			userKey,
			days,
			platform,
			scopedAccount,
			maxAgeHours,
			accountIdsKey,
			groupId,
		);
		const cached = cache.get(key);
		if (cached) setState({ ...cached, isLoading: false });
		if (cache.isFresh(key)) return;

		(async () => {
			try {
				const cutoffIso = new Date(
					Date.now() - days * 86_400_000,
				).toISOString();

				// 1) Fetch published posts in window.
				let postsQuery = supabase
					.from("posts")
					.select(
						"id, published_at, platform, account_id, instagram_account_id",
					)
					.eq("user_id", authUser.id)
					.eq("status", "published")
					.gte("published_at", cutoffIso)
					.order("published_at", { ascending: false })
					.limit(500);

				if (platform !== "all")
					postsQuery = postsQuery.eq("platform", platform);
				if (scopedAccount) {
					if (scopedAccount.platform === "threads") {
						postsQuery = postsQuery.eq("account_id", scopedAccount.id);
					} else {
						postsQuery = postsQuery.eq(
							"instagram_account_id",
							scopedAccount.id,
						);
					}
				} else if (accountIdsKey) {
					const ids = accountIdsKey;
					postsQuery = postsQuery.or(
						`account_id.in.(${ids}),instagram_account_id.in.(${ids})`,
					);
				}
				const postsRes = await postsQuery;
				if (cancelled) return;
				if (postsRes.error) throw postsRes.error;

				const posts = (postsRes.data ?? []) as unknown as PostRow[];
				if (posts.length === 0) {
					const next: VelocityState = { ...EMPTY, isLoading: false };
					cache.set(key, next);
					setState(next);
					return;
				}

				const postIds = posts.map((p) => p.id);
				const publishedById = new Map<string, string>();
				for (const p of posts) {
					if (p.published_at) publishedById.set(p.id, p.published_at);
				}

				// 2) Fetch all snapshots for these posts, ordered ASC so earliest is first.
				// post_metric_history has snapshot_at + views_count.
				const snapshotsRes = await supabase
					.from("post_metric_history")
					.select("post_id, snapshot_at, views_count")
					.in("post_id", postIds)
					.order("post_id", { ascending: true })
					.order("snapshot_at", { ascending: true })
					.limit(20000);

				if (cancelled) return;
				if (snapshotsRes.error) throw snapshotsRes.error;

				const snapshots = (snapshotsRes.data ?? []) as unknown as MetricRow[];

				// Take first snapshot per post.
				const firstByPost = new Map<string, MetricRow>();
				for (const s of snapshots) {
					if (!firstByPost.has(s.post_id)) firstByPost.set(s.post_id, s);
				}

				// 3) Compute velocity for each post whose first snapshot falls within
				// maxAgeHours of publish. Floor at 1h to avoid division by tiny dt.
				const samples: VelocitySample[] = [];
				for (const [postId, first] of firstByPost) {
					const publishedAt = publishedById.get(postId);
					if (!publishedAt) continue;
					const dtMs = Date.parse(first.snapshot_at) - Date.parse(publishedAt);
					if (!Number.isFinite(dtMs) || dtMs <= 0) continue;
					const hours = dtMs / (60 * 60 * 1000);
					if (hours > maxAgeHours) continue;
					const views = first.views_count ?? 0;
					if (views <= 0) continue;
					const denom = Math.max(1, hours);
					samples.push({
						postId,
						publishedAt,
						hoursSincePublish: hours,
						viewsAtSnapshot: views,
						viewsPerHour: views / denom,
					});
				}

				const sorted = samples.map((s) => s.viewsPerHour).sort((a, b) => a - b);
				const next: VelocityState = {
					samples,
					p25: quantile(sorted, 0.25),
					p50: quantile(sorted, 0.5),
					p75: quantile(sorted, 0.75),
					max: sorted.length > 0 ? sorted[sorted.length - 1]! : null,
					isLoading: false,
					hasError: false,
				};
				cache.set(key, next);
				setState(next);
			} catch {
				if (!cancelled)
					setState((prev) => ({ ...prev, isLoading: false, hasError: true }));
			}
		})();

		return () => {
			cancelled = true;
		};
	}, [
		userKey,
		days,
		platform,
		authUser,
		scopedAccount,
		accountIdsKey,
		groupId,
		maxAgeHours,
	]);

	return state;
}
