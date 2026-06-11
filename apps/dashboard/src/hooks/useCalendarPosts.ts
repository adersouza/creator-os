import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/services/supabase";
import { subscribe } from "@/services/realtimeManager";
import { queryClient } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";
import { useAuthUser } from "@/hooks/useAuthUser";
import { getCampaignFactoryMetadata } from "@/lib/campaignFactory";

export type CalendarPlatform = "threads" | "instagram";
export type CalendarStatus =
	| "draft"
	| "scheduled"
	| "published"
	| "failed"
	| "review";

export interface CalendarPost {
	id: string;
	content: string;
	mediaUrls: string[];
	metadata?: Record<string, unknown> | null | undefined;
	createdAt?: string | null | undefined;
	permalink?: string | null | undefined;
	mediaType?: string | null | undefined;
	igMediaType?: string | null | undefined;
	viewsCount?: number | null | undefined;
	likesCount?: number | null | undefined;
	repliesCount?: number | null | undefined;
	sharesCount?: number | null | undefined;
	igViews?: number | null | undefined;
	igCommentCount?: number | null | undefined;
	igReach?: number | null | undefined;
	igSaved?: number | null | undefined;
	igShares?: number | null | undefined;
	threadsPostId: string | null;
	status: CalendarStatus;
	/** Raw approval_status from the DB, passed through for UI hints */
	approvalStatus: string | null;
	scheduledFor: string | null;
	publishedAt: string | null;
	account: {
		id: string | null;
		handle: string;
		displayName: string;
		platform: CalendarPlatform;
		groupId: string | null;
		groupName: string;
		groupColor: string;
	};
}

export interface QueueHealthGroup {
	id: string;
	name: string;
	color: string;
	postsCount: number;
	/** Days of content = future scheduled posts / average posts-per-day target (3). */
	daysOfContent: number;
}

interface State {
	posts: CalendarPost[];
	/** User-defined groups, in stable sort order. Empty array → UI hides group filter. */
	groups: Array<{ id: string; name: string; color: string }>;
	queueHealthByGroup: Record<string, QueueHealthGroup>;
	/** Accounts active but with no scheduled post in next 48h — mirrors useNeedsAttention. */
	gapsCount: number;
	/** Total future scheduled posts across the whole queue. */
	totalQueue: number;
	campaignFactoryReferencePosts: CalendarPost[];
	isLoading: boolean;
	hasError: boolean;
}

const UNASSIGNED_COLOR = "#6B6B70";
/** Target posts-per-day per group for the queue-health "days of content" math.
 *  Exported so Calendar.tsx and any future scheduler code use the same baseline. */
export const TARGET_POSTS_PER_DAY = 3;

const EMPTY: Omit<State, "isLoading" | "hasError"> = {
	posts: [],
	groups: [],
	queueHealthByGroup: {},
	gapsCount: 0,
	totalQueue: 0,
	campaignFactoryReferencePosts: [],
};

interface CalendarRpcPost {
	id: string;
	content: string;
	media_urls: string[] | null;
	status: string | null;
	approval_status: string | null;
	scheduled_for: string | null;
	published_at: string | null;
	platform: string | null;
	account_id: string | null;
	instagram_account_id?: string | null;
	metadata?: Record<string, unknown> | null;
	created_at?: string | null;
	permalink?: string | null;
	media_type?: string | null;
	ig_media_type?: string | null;
	views_count?: number | null;
	likes_count?: number | null;
	replies_count?: number | null;
	shares_count?: number | null;
	ig_views?: number | null;
	ig_comment_count?: number | null;
	ig_reach?: number | null;
	ig_saved?: number | null;
	ig_shares?: number | null;
	username: string | null;
	display_name: string | null;
	group_id: string | null;
	group_name: string | null;
	group_color: string | null;
	threads_post_id?: string | null;
}

interface CalendarRpcPayload {
	posts: CalendarRpcPost[];
	groups: Array<{ id: string; name: string; color: string }>;
	queueHealthByGroup: Record<string, QueueHealthGroup>;
	gapsCount: number;
	totalQueue: number;
}

function normalizeStatus(
	raw: string | null | undefined,
	approvalStatus: string | null | undefined,
): CalendarStatus {
	if (approvalStatus === "pending" || approvalStatus === "in_review")
		return "review";
	switch (raw) {
		case "published":
			return "published";
		case "failed":
		case "publish_failed":
		case "error":
			return "failed";
		case "draft":
			return "draft";
		case "scheduled":
		case "queued":
		case "publishing":
			return "scheduled";
		default:
			return "scheduled";
	}
}

function normalizePlatform(raw: string | null | undefined): CalendarPlatform {
	return raw === "instagram" ? "instagram" : "threads";
}

type PostMetaRow = {
	id: string;
	threads_post_id: string | null;
	metadata: Record<string, unknown> | null;
	created_at: string | null;
	permalink: string | null;
	media_type: string | null;
	ig_media_type: string | null;
	views_count: number | null;
	likes_count: number | null;
	replies_count: number | null;
	shares_count: number | null;
	ig_views: number | null;
	ig_comment_count: number | null;
	ig_reach: number | null;
	ig_saved: number | null;
	ig_shares: number | null;
};

type InstagramAccountRow = {
	id: string;
	username: string | null;
	display_name: string | null;
	group_id: string | null;
};

function normalizeCalendarPost(
	p: CalendarRpcPost,
	metaRows: Map<string, PostMetaRow>,
	instagramAccounts: Map<string, InstagramAccountRow>,
	groups: Map<string, { id: string; name: string; color: string }>,
): CalendarPost {
	const meta = metaRows.get(p.id);
	const instagramAccountId = p.instagram_account_id ?? null;
	const instagramAccount = instagramAccountId
		? instagramAccounts.get(instagramAccountId)
		: undefined;
	const accountId = p.account_id ?? instagramAccountId;
	const username = p.username ?? instagramAccount?.username ?? null;
	const displayName = p.display_name ?? instagramAccount?.display_name ?? null;
	const groupId = p.group_id ?? instagramAccount?.group_id ?? null;
	const group = groupId ? groups.get(groupId) : undefined;

	return {
		id: p.id,
		content: p.content ?? "",
		mediaUrls: p.media_urls ?? [],
		metadata: p.metadata ?? meta?.metadata ?? null,
		createdAt: p.created_at ?? meta?.created_at ?? null,
		permalink: p.permalink ?? meta?.permalink ?? null,
		mediaType: p.media_type ?? meta?.media_type ?? null,
		igMediaType: p.ig_media_type ?? meta?.ig_media_type ?? null,
		viewsCount: p.views_count ?? meta?.views_count ?? null,
		likesCount: p.likes_count ?? meta?.likes_count ?? null,
		repliesCount: p.replies_count ?? meta?.replies_count ?? null,
		sharesCount: p.shares_count ?? meta?.shares_count ?? null,
		igViews: p.ig_views ?? meta?.ig_views ?? null,
		igCommentCount: p.ig_comment_count ?? meta?.ig_comment_count ?? null,
		igReach: p.ig_reach ?? meta?.ig_reach ?? null,
		igSaved: p.ig_saved ?? meta?.ig_saved ?? null,
		igShares: p.ig_shares ?? meta?.ig_shares ?? null,
		threadsPostId: p.threads_post_id ?? meta?.threads_post_id ?? null,
		status: normalizeStatus(p.status, p.approval_status),
		approvalStatus: p.approval_status ?? null,
		scheduledFor: p.scheduled_for,
		publishedAt: p.published_at,
		account: {
			id: accountId,
			handle: username ? `@${username}` : "Unassigned Instagram",
			displayName: displayName || username || "Unassigned Instagram",
			platform: normalizePlatform(p.platform),
			groupId,
			groupName: group?.name ?? p.group_name ?? "Unassigned",
			groupColor: group?.color ?? p.group_color ?? UNASSIGNED_COLOR,
		},
	};
}

const CAMPAIGN_FACTORY_REFERENCE_LIMIT = 300;
const CAMPAIGN_FACTORY_REFERENCE_LOOKBACK_DAYS = 120;

async function fetchCampaignFactoryRows(
	userKey: string,
): Promise<CalendarRpcPost[]> {
	const since = new Date(
		Date.now() - CAMPAIGN_FACTORY_REFERENCE_LOOKBACK_DAYS * 86_400_000,
	).toISOString();
	const { data, error } = await supabase
		.from("posts")
		.select(
			"id, content, media_urls, status, approval_status, scheduled_for, published_at, platform, account_id, instagram_account_id, metadata, created_at, permalink, media_type, ig_media_type, threads_post_id, views_count, likes_count, replies_count, shares_count, ig_views, ig_comment_count, ig_reach, ig_saved, ig_shares",
		)
		.eq("user_id", userKey)
		.in("status", ["draft", "scheduled", "published"])
		.not("metadata", "is", null)
		// Calendar needs all current unscheduled CF drafts, plus a recent bounded
		// reference set for reuse badges. The previous implementation paged every
		// historical metadata row into memory on each calendar load, which is too
		// expensive for large 2026 workspaces.
		.or(`status.eq.draft,created_at.gte.${since}`)
		.order("created_at", { ascending: false })
		.limit(CAMPAIGN_FACTORY_REFERENCE_LIMIT);

	if (error) throw error;
	return ((data ?? []) as CalendarRpcPost[]).filter((row) =>
		getCampaignFactoryMetadata({ metadata: row.metadata ?? null }),
	);
}

/**
 * Calendar week data via `get_calendar_week` RPC. Server consolidates:
 * weekly posts (scheduled OR published in window), user groups,
 * queue-health by group, 48h gap count, and total queue. Client just
 * normalizes status/platform enums. 9–13 queries → 1 RPC.
 */
export function useCalendarPosts(weekStart: Date, weekSpan = 1): State {
	const authUser = useAuthUser();
	const userKey = authUser ? authUser.id : null;

	// Normalize weekStart to midnight so a parent passing a non-midnight Date
	// doesn't thrash the query key.
	const weekKey = new Date(weekStart);
	weekKey.setHours(0, 0, 0, 0);
	const weekCacheKey = weekKey.getTime();
	const normalizedWeekSpan = Math.max(1, Math.min(8, Math.floor(weekSpan)));

	const { data, isPending, isError } = useQuery({
		queryKey: queryKeys.calendar.posts(userKey, weekCacheKey, normalizedWeekSpan),
		enabled: !!userKey,
		// Calendar freshness matters when the operator tabs back from Threads/IG
		// to verify a just-scheduled post landed. Overrides the app-wide
		// refetchOnWindowFocus: false set in queryClient.ts. The short stale
		// window stops in-route remounts from refetching while still letting
		// window-focus refresh the data.
		refetchOnWindowFocus: true,
		staleTime: 30_000,
		gcTime: 5 * 60_000,
		queryFn: async (): Promise<Omit<State, "isLoading" | "hasError">> => {
			if (!userKey) return EMPTY;
			const payloads: CalendarRpcPayload[] = [];
			for (let offset = 0; offset < normalizedWeekSpan; offset += 1) {
				const start = new Date(weekCacheKey);
				start.setDate(start.getDate() + offset * 7);
				const { data, error } = await supabase.rpc("get_calendar_week", {
					p_week_start: start.toISOString(),
				});
				if (error) throw error;
				if (data) payloads.push(data as CalendarRpcPayload);
			}
			if (payloads.length === 0) return EMPTY;
			const firstPayload = payloads[0];
			if (!firstPayload) return EMPTY;
			const postMap = new Map<string, CalendarRpcPost>();
			const groupMap = new Map<string, { id: string; name: string; color: string }>();
			for (const payload of payloads) {
				for (const post of payload.posts ?? []) {
					if (post.id) postMap.set(post.id, post);
				}
				for (const group of payload.groups ?? []) {
					groupMap.set(group.id, group);
				}
			}
			const payload: CalendarRpcPayload = {
				posts: Array.from(postMap.values()),
				groups: Array.from(groupMap.values()),
				queueHealthByGroup: firstPayload.queueHealthByGroup ?? {},
				gapsCount: firstPayload.gapsCount ?? 0,
				totalQueue: firstPayload.totalQueue ?? 0,
			};
			const groups = new Map(
				(payload.groups ?? []).map((group) => [group.id, group] as const),
			);
			const metaRows = new Map<string, PostMetaRow>();
			const postIds = (payload.posts ?? [])
				.map((p) => p.id)
				.filter((id): id is string => !!id);
			if (postIds.length > 0) {
				const { data: idRows } = await supabase
					.from("posts")
					.select(
						"id, threads_post_id, metadata, created_at, permalink, media_type, ig_media_type, views_count, likes_count, replies_count, shares_count, ig_views, ig_comment_count, ig_reach, ig_saved, ig_shares",
					)
					.in("id", postIds)
					.eq("user_id", userKey);
				for (const row of (idRows ?? []) as PostMetaRow[]) {
					metaRows.set(row.id, row);
				}
			}

			const campaignFactoryRows = await fetchCampaignFactoryRows(userKey);
			for (const row of campaignFactoryRows) {
				metaRows.set(row.id, {
					id: row.id,
					threads_post_id: row.threads_post_id ?? null,
					metadata: row.metadata ?? null,
					created_at: row.created_at ?? null,
					permalink: row.permalink ?? null,
					media_type: row.media_type ?? null,
					ig_media_type: row.ig_media_type ?? null,
					views_count: row.views_count ?? null,
					likes_count: row.likes_count ?? null,
					replies_count: row.replies_count ?? null,
					shares_count: row.shares_count ?? null,
					ig_views: row.ig_views ?? null,
					ig_comment_count: row.ig_comment_count ?? null,
					ig_reach: row.ig_reach ?? null,
					ig_saved: row.ig_saved ?? null,
					ig_shares: row.ig_shares ?? null,
				});
			}

			const instagramAccountIds = Array.from(
				new Set(
					campaignFactoryRows
						.map((row) => row.instagram_account_id)
						.filter(
							(id): id is string => typeof id === "string" && id.length > 0,
						),
				),
			);
			const instagramAccounts = new Map<string, InstagramAccountRow>();
			if (instagramAccountIds.length > 0) {
				const { data: accountRows } = await supabase
					.from("instagram_accounts")
					.select("id, username, display_name, group_id")
					.eq("user_id", userKey)
					.in("id", instagramAccountIds);
				for (const row of (accountRows ?? []) as InstagramAccountRow[]) {
					instagramAccounts.set(row.id, row);
				}
			}

			const posts: CalendarPost[] = (payload.posts ?? []).map((p) =>
				normalizeCalendarPost(p, metaRows, instagramAccounts, groups),
			);

			const campaignFactoryReferencePosts = campaignFactoryRows.map((row) =>
				normalizeCalendarPost(row, metaRows, instagramAccounts, groups),
			);

			return {
				posts,
				groups: payload.groups ?? [],
				queueHealthByGroup: payload.queueHealthByGroup ?? {},
				gapsCount: payload.gapsCount ?? 0,
				totalQueue: payload.totalQueue ?? 0,
				campaignFactoryReferencePosts,
			};
		},
	});

	// Realtime: invalidate when any posts row changes for this user.
	// Debounced via the realtimeManager + 400ms setTimeout so a publish
	// burst doesn't hammer the DB.
	useEffect(() => {
		if (!authUser) return;
		let timer: ReturnType<typeof setTimeout> | null = null;
		const schedule = () => {
			if (timer) clearTimeout(timer);
			timer = setTimeout(() => {
				queryClient.invalidateQueries({ queryKey: queryKeys.calendar.userPosts(userKey) });
			}, 400);
		};

		const unsubscribe = subscribe(
			`calendar-posts:${authUser.id}`,
			async (signal) => {
				const {
					data: { user },
				} = await supabase.auth.getUser();
				if (signal.aborted || !user) return null;
				return supabase
					.channel(`calendar-posts:${user.id}`)
					.on(
						"postgres_changes",
						{
							event: "*",
							schema: "public",
							table: "posts",
							filter: `user_id=eq.${user.id}`,
						},
						schedule,
					)
					.subscribe();
			},
			schedule,
		);

		return () => {
			if (timer) clearTimeout(timer);
			unsubscribe();
		};
	}, [authUser, userKey]);

	return {
		...(data ?? EMPTY),
		isLoading: !!userKey && isPending,
		hasError: !!userKey && isError,
	};
}
