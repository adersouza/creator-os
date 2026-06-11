// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Post publishing, deletion, scheduling API operations
 */

import { subscribe } from "@/services/realtimeManager";
import { mapPostRow } from "@/lib/mappers";
import type { ThreadPost } from "@/types/index";
import type { PlatformFilter } from "@/types/platform";
import { sanitizeMediaURLs, sanitizeText, validatePostContent } from "@/utils/sanitize";
import { randomUUID } from "@/lib/uuid";
import type { CampaignFactoryAudioBatchAction } from "@/lib/campaignFactory";
import type { Unsubscribe } from "./shared.js";
import {
	detectMediaType,
	getUserIdAsync,
	logger,
	safeJsonParse,
	supabase,
} from "./shared.js";

import { apiUrl } from '@/lib/apiUrl';
export type PublishStage =
	| "queued"
	| "preflight"
	| "publishing"
	| "scheduling"
	| "processing"
	| "published"
	| "retrying"
	| "failed";

type PublishJobResponse = {
	success?: boolean;
	jobId: string;
	status: "queued" | "publishing" | "retrying" | "published" | "failed";
	stage: PublishStage;
	result?: Record<string, unknown> | null;
	errorCode?: string | null;
	errorMessage?: string | null;
	requestId?: string | null;
};

export type CampaignFactoryAudioEvent = {
	id: string | null;
	postId: string | null;
	campaignId: string | null;
	renderedAssetId: string | null;
	action: string | null;
	previousStatus: string | null;
	nextStatus: string | null;
	proofComplete: boolean | null;
	nativeAudioLocator: string | null;
	platformAudioId: string | null;
	platformUrl: string | null;
	note: string | null;
	reason: string | null;
	timestamp: string | null;
};

export type CampaignFactoryAudioEventFilters = {
	postId?: string | undefined;
	campaignId?: string | undefined;
	renderedAssetId?: string | undefined;
	limit?: number | undefined;
};

const PENDING_PUBLISH_JOBS_KEY = "juno33.pendingPublishJobs";

const CANONICAL_POST_MEDIA_TYPES: Record<string, string> = {
	text: "text",
	text_post: "text",
	image: "image",
	video: "video",
	carousel: "carousel",
	carousel_album: "carousel",
	reel: "reel",
	reels: "reel",
	story: "story",
	stories: "story",
};

type ComposerContentInput = {
	platform?: string | undefined;
	content?: unknown;
};

function sanitizeComposerContent(
	post: ComposerContentInput,
	sanitizedMediaUrls: string[],
): string {
	const platform = post.platform || "threads";
	const rawContent = typeof post.content === "string" ? post.content : "";
	const trimmed = rawContent.trim();
	const hasMedia = sanitizedMediaUrls.length > 0;

	if (platform === "instagram") {
		if (!trimmed && hasMedia) return "";
		if (!trimmed) throw new Error("Instagram posts need media or a caption");
		const sanitized = sanitizeText(rawContent);
		if (sanitized.length > 2200) {
			throw new Error("Instagram captions must be 2,200 characters or less");
		}
		return sanitized;
	}

	return validatePostContent(rawContent);
}

function normalizePostMediaType(
	mediaType: string | null | undefined,
	fallback = "text",
): string {
	const normalizedFallback =
		CANONICAL_POST_MEDIA_TYPES[fallback.trim().toLowerCase()] || "text";
	if (!mediaType) return normalizedFallback;

	return (
		CANONICAL_POST_MEDIA_TYPES[mediaType.trim().toLowerCase()] ||
		normalizedFallback
	);
}

function compactRecord(record: Record<string, unknown>): Record<string, unknown> {
	return Object.fromEntries(
		Object.entries(record).filter(([, value]) => {
			if (value === undefined || value === null || value === "") return false;
			if (Array.isArray(value) && value.length === 0) return false;
			return true;
		}),
	);
}

function nullableString(value: unknown): string | null {
	return typeof value === "string" && value.trim() ? value.trim() : null;
}

function nullableBoolean(value: unknown): boolean | null {
	return typeof value === "boolean" ? value : null;
}

export function parseCampaignFactoryAudioEvent(value: unknown): CampaignFactoryAudioEvent {
	const record =
		value && typeof value === "object" && !Array.isArray(value)
			? (value as Record<string, unknown>)
			: {};
	const platformUrl = nullableString(record.platformUrl ?? record.platform_url);
	const platformAudioId = nullableString(record.platformAudioId ?? record.platform_audio_id);
	return {
		id: nullableString(record.id),
		postId: nullableString(record.postId ?? record.post_id),
		campaignId: nullableString(record.campaignId ?? record.campaign_id),
		renderedAssetId: nullableString(record.renderedAssetId ?? record.rendered_asset_id),
		action: nullableString(record.action),
		previousStatus: nullableString(record.previousStatus ?? record.previous_status),
		nextStatus: nullableString(record.nextStatus ?? record.next_status),
		proofComplete: nullableBoolean(record.proofComplete ?? record.proof_complete),
		nativeAudioLocator:
			nullableString(record.nativeAudioLocator ?? record.native_audio_locator) ||
			platformUrl ||
			platformAudioId,
		platformAudioId,
		platformUrl,
		note: nullableString(record.note),
		reason: nullableString(record.reason),
		timestamp: nullableString(record.timestamp ?? record.created_at),
	};
}

function titleCaseStatus(value: string | null): string {
	if (!value) return "Unknown";
	return value
		.split(/[_\s-]+/)
		.filter(Boolean)
		.map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
		.join(" ");
}

export function formatCampaignFactoryAudioEventLine(
	event: Pick<CampaignFactoryAudioEvent, "action" | "previousStatus" | "nextStatus">,
): string {
	const action = titleCaseStatus(event.action);
	if (event.previousStatus || event.nextStatus) {
		return `${action}: ${titleCaseStatus(event.previousStatus)} -> ${titleCaseStatus(event.nextStatus)}`;
	}
	return action;
}

async function pollPublishJob(
	jobId: string,
	accessToken: string | undefined,
	onPublishStage: ((stage: PublishStage) => void) | null,
): Promise<Record<string, unknown>> {
	rememberPendingPublishJob(jobId);
	const startedAt = Date.now();
	let delayMs = 800;
	while (Date.now() - startedAt < 120_000) {
		await new Promise((resolve) => globalThis.setTimeout(resolve, delayMs));
		const response = await fetch(
			apiUrl(`/api/jobs?action=publish-status&id=${encodeURIComponent(jobId)}`),
			{
				headers: {
					Authorization: `Bearer ${accessToken}`,
					"X-Request-Id": randomUUID(),
				},
			},
		);
		const data = (await response.json().catch(() => null)) as PublishJobResponse | null;
		if (!response.ok || !data) {
			const error = new Error(data?.errorMessage || "Failed to load publish status") as Error & {
				requestId?: string | undefined;
			};
			if (data?.requestId) error.requestId = data.requestId;
			throw error;
		}
		if (data.stage) onPublishStage?.(data.stage);
		if (data.status === "published") {
			onPublishStage?.("published");
			forgetPendingPublishJob(jobId);
			return data.result || { jobId, status: data.status };
		}
		if (data.status === "failed") {
			onPublishStage?.("failed");
			forgetPendingPublishJob(jobId);
			const error = new Error(data.errorMessage || "Publish failed") as Error & {
				requestId?: string | undefined;
			};
			if (data.requestId) error.requestId = data.requestId;
			throw error;
		}
		delayMs = Math.min(Math.round(delayMs * 1.35), 3000);
	}
	throw new Error("Publish is still running. Check the composer again shortly.");
}

export async function resumePendingPublishJobs(
	onPublishStage?: ((stage: PublishStage) => void) | undefined,
): Promise<Array<PromiseSettledResult<Record<string, unknown>>>> {
	const pending = readPendingPublishJobs();
	if (pending.length === 0) return [];
	const {
		data: { session },
	} = await supabase.auth.getSession();
	return Promise.allSettled(
		pending.map((jobId) =>
			pollPublishJob(jobId, session?.access_token, onPublishStage ?? null),
		),
	);
}

function rememberPendingPublishJob(jobId: string) {
	if (typeof window === "undefined") return;
	try {
		const pending = new Set(readPendingPublishJobs());
		pending.add(jobId);
		window.localStorage.setItem(
			PENDING_PUBLISH_JOBS_KEY,
			JSON.stringify(Array.from(pending).slice(-20)),
		);
	} catch {
		// Best-effort recovery state only.
	}
}

function forgetPendingPublishJob(jobId: string) {
	if (typeof window === "undefined") return;
	try {
		const pending = readPendingPublishJobs().filter((id) => id !== jobId);
		if (pending.length === 0) {
			window.localStorage.removeItem(PENDING_PUBLISH_JOBS_KEY);
		} else {
			window.localStorage.setItem(PENDING_PUBLISH_JOBS_KEY, JSON.stringify(pending));
		}
	} catch {
		// Best-effort recovery state only.
	}
}

function readPendingPublishJobs(): string[] {
	if (typeof window === "undefined") return [];
	try {
		const raw = window.localStorage.getItem(PENDING_PUBLISH_JOBS_KEY);
		if (!raw) return [];
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed)
			? parsed.filter((value): value is string => typeof value === "string" && value.length > 0)
			: [];
	} catch {
		return [];
	}
}

export type PublishPreflightIssue = {
	severity: "error" | "warning" | "info";
	category:
		| "account"
		| "caption"
		| "instagram"
		| "media"
		| "threads"
		| "token";
	code: string;
	message: string;
};

export type PublishPreflightResult = {
	ok: boolean;
	issues: PublishPreflightIssue[];
	summary: {
		errors: number;
		warnings: number;
		infos: number;
	};
};

// biome-ignore lint/suspicious/noExplicitAny: mirrors the flexible createPost payload
export async function preflightPost(post: any): Promise<PublishPreflightResult> {
	const sanitizedMediaUrls = sanitizeMediaURLs(post.mediaUrls || []);
	const sanitizedContent = sanitizeComposerContent(post, sanitizedMediaUrls);
	const {
		data: { session },
	} = await supabase.auth.getSession();
	const platform = post.platform || "threads";

	const payload = {
		platform,
		publishMode: post.publishMode || undefined,
		accountId: platform === "threads" ? post.accountId : undefined,
		instagramAccountId:
			platform === "instagram" ? post.instagramAccountId : undefined,
		igMediaType: post.igMediaType || undefined,
		altText: post.altText || undefined,
		content: sanitizedContent,
		media: sanitizedMediaUrls.map((url: string, index: number) => ({
			type: detectMediaType(url),
			url,
			altText: post.mediaAltTexts?.[index] || post.altText || undefined,
		})),
		topics: post.topics || [],
		linkUrl: post.linkUrl || undefined,
		locationId: post.locationId || undefined,
		collaborators: post.collaborators || undefined,
		pollAttachment: post.pollAttachment || undefined,
		isSpoiler: post.isSpoiler || undefined,
		textSpoilers: post.textSpoilers || undefined,
		allowlistedCountryCodes: post.allowlistedCountryCodes || undefined,
		isTrialReel: post.isTrialReel || undefined,
		replyApprovalMode: post.replyApprovalMode || undefined,
		gifAttachment: post.gifAttachment || undefined,
		isGhostPost: post.isGhostPost || undefined,
		crossreshareToIg: post.crossreshareToIg || undefined,
		crossreshareToIgDarkMode: post.crossreshareToIgDarkMode || undefined,
		textAttachment: post.textAttachment || undefined,
		settings: post.settings || {
			allowReplies: true,
			whoCanReply: "everyone",
		},
		firstComment: post.firstComment || undefined,
		userTags: post.userTags || undefined,
		productTags: post.productTags || undefined,
		brandedContentSponsorIds: post.brandedContentSponsorIds || undefined,
		isPaidPartnership: post.isPaidPartnership || undefined,
		shareToFeed: post.shareToFeed,
		graduation: post.graduation || undefined,
		thumbOffset: post.thumbOffset ?? post.reelCover ?? undefined,
		reelCover: post.reelCover ?? undefined,
		coverUrl: post.coverUrl || undefined,
		audioName: post.audioName || undefined,
		igAudioId: post.igAudioId || undefined,
		commentEnabled: post.commentEnabled,
		replyToId: post.replyToId || undefined,
		topicTag: post.topics?.[0] || undefined,
		metadata: post.metadata || undefined,
	};

	const response = await fetch(apiUrl("/api/posts?action=preflight"), {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify(payload),
	});
	const data = await response.json();
	if (!response.ok) {
		const result = data.preflight as PublishPreflightResult | undefined;
		if (result) return result;
		throw new Error(data.error || "Publish preflight failed");
	}
	return data as PublishPreflightResult;
}

// Paginated posts fetching with total count
export async function getPosts(
	accountId: string = "ALL",
	page: number = 1,
	pageSize: number = 50,
	platformFilter?: PlatformFilter,
	since?: string, // ISO date string — only fetch posts after this date
	statusFilter?: string, // e.g. "scheduled", "draft", "published" — server-side filter for pagination
): Promise<{ posts: ThreadPost[]; total: number }> {
	const userId = await getUserIdAsync();

	// Count query only when paginating (page > 1 or explicit need)
	// Skip for analytics/heatmap use cases where total isn't needed
	let count: number | null = null;
	if (page > 1 || !since) {
		let countQuery = supabase
			.from("posts")
			.select("*", { count: "exact", head: true })
			.eq("user_id", userId);

		if (accountId !== "ALL") {
			if (platformFilter === "instagram") {
				countQuery = countQuery.eq("instagram_account_id", accountId);
			} else {
				countQuery = countQuery.eq("account_id", accountId);
			}
		}

		if (platformFilter && platformFilter !== "all") {
			// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped
			countQuery = (countQuery as any).eq("platform", platformFilter);
		}

		if (statusFilter && statusFilter !== "All") {
			countQuery = countQuery.eq("status", statusFilter);
		}

		if (since) {
			countQuery = countQuery.or(
				`published_at.gte.${since},scheduled_for.gte.${since}`,
			);
		}

		const { count: c, error: countError } = await countQuery;
		if (countError) {
			logger.error("Failed to fetch posts count from Supabase:", countError);
			throw countError;
		}
		count = c;
	}

	const from = (page - 1) * pageSize;
	const to = from + pageSize - 1;

	// Sort scheduled/draft posts by scheduled_for, published by published_at
	const isScheduledOrDraft =
		statusFilter === "scheduled" || statusFilter === "draft";

	let dataQuery = supabase
		.from("posts")
		.select("*")
		.eq("user_id", userId)
		.order(isScheduledOrDraft ? "scheduled_for" : "published_at", {
			ascending: isScheduledOrDraft,
			nullsFirst: false,
		})
		.order("created_at", { ascending: false })
		.range(from, to);

	if (accountId !== "ALL") {
		if (platformFilter === "instagram") {
			dataQuery = dataQuery.eq("instagram_account_id", accountId);
		} else {
			dataQuery = dataQuery.eq("account_id", accountId);
		}
	}

	if (platformFilter && platformFilter !== "all") {
		// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped
		dataQuery = (dataQuery as any).eq("platform", platformFilter);
	}

	if (statusFilter && statusFilter !== "All") {
		dataQuery = dataQuery.eq("status", statusFilter);
	}

	if (since) {
		dataQuery = dataQuery.or(
			`published_at.gte.${since},scheduled_for.gte.${since}`,
		);
	}

	const { data, error } = await dataQuery;

	if (error) {
		logger.error("Failed to fetch posts from Supabase:", error);
		throw error;
	}

	const posts: ThreadPost[] = (data || []).map((row: Record<string, unknown>) =>
		mapPostRow(row as Record<string, unknown>),
	);

	return { posts, total: count || 0 };
}

/**
 * Fetch pending auto_post_queue items as ThreadPost-shaped objects for calendar display.
 * These are autoposter-scheduled posts that haven't published yet.
 */
export async function getQueuedPostsForCalendar(): Promise<ThreadPost[]> {
	const userId = await getUserIdAsync();
	if (!userId) return [];

	// Get workspace ID from workspace_members
	const { data: membership } = await supabase
		.from("workspace_members")
		.select("workspace_id")
		.eq("user_id", userId)
		.limit(1)
		.maybeSingle();

	if (!membership?.workspace_id) return [];

	const { data: items, error } = await supabase
		.from("auto_post_queue")
		.select(
			"id, content, status, scheduled_for, created_at, media_urls, group_id, topic_tag",
		)
		.eq("workspace_id", membership.workspace_id)
		.eq("status", "pending")
		.not("scheduled_for", "is", null)
		.order("scheduled_for", { ascending: true })
		.limit(200);

	if (error || !items) return [];

	// Map queue items to ThreadPost shape
	return (items as Record<string, unknown>[]).map(
		(row) =>
			({
				id: `queue-${row.id}`,
				content: String(row.content ?? ""),
				status: "scheduled" as ThreadPost["status"],
				platform: "threads" as ThreadPost["platform"],
				accountId: "",
				scheduledDate: row.scheduled_for as string,
				createdAt: row.created_at as string,
				mediaUrls: (row.media_urls as string[]) ?? [],
				media: (row.media_urls as string[]) ?? [],
				views: 0,
				likes: 0,
				replies: 0,
				topics: [],
				performance: {
					views: 0,
					likes: 0,
					replies: 0,
					reposts: 0,
					quotes: 0,
					shares: 0,
				},
				source: "auto-poster",
				// Store queue metadata for display
				metadata: {
					isQueueItem: true,
					topicTag: row.topic_tag,
					groupId: row.group_id,
				},
			}) as unknown as ThreadPost,
	);
}

// Legacy method for backward compatibility (used by real-time subscription)
export async function getPostsLegacy(
	accountId: string = "ALL",
	platformFilter?: PlatformFilter,
): Promise<ThreadPost[]> {
	const { posts } = await getPosts(accountId, 1, 2000, platformFilter);
	return posts;
}

// Real-time listener for posts
export function subscribeToPostsRealtime(
	accountId: string = "ALL",
	onUpdate: (posts: ThreadPost[]) => void,
	platformFilter?: PlatformFilter,
): Unsubscribe {
	let unsubscribed = false;

	const fetchPosts = async () => {
		if (unsubscribed) return;
		try {
			const posts = await getPostsLegacy(accountId, platformFilter);
			if (!unsubscribed) {
				onUpdate(posts);
			}
		} catch (error) {
			logger.error("Failed to fetch posts in real-time subscription:", error);
		}
	};

	const unsub = subscribe(
		`posts:${accountId}`,
		async (signal) => {
			const userId = await getUserIdAsync();
			if (signal.aborted || !userId) return null;

			await fetchPosts();
			if (signal.aborted) return null;

			return supabase
				.channel(`posts-${userId}-${accountId}`)
				.on(
					"postgres_changes",
					{
						event: "*",
						schema: "public",
						table: "posts",
						filter: `user_id=eq.${userId}`,
					},
					() => {
						fetchPosts();
					},
				)
				.subscribe();
		},
		fetchPosts,
	);

	return () => {
		unsubscribed = true;
		unsub();
	};
}

export async function getPost(id: string): Promise<ThreadPost> {
	const userId = await getUserIdAsync();
	const { data, error } = await supabase
		.from("posts")
		.select("*")
		.eq("id", id)
		.eq("user_id", userId)
		.maybeSingle();

	if (error || !data) {
		throw new Error("Post not found");
	}

	return mapPostRow(data as Record<string, unknown>);
}

/**
 * Parse a Threads/IG permalink to find the matching row in posts(id).
 * Supported shapes:
 *   https://www.threads.com/@user/post/<threads_post_id>
 *   https://www.threads.net/@user/post/<threads_post_id>
 *   https://www.instagram.com/p/<shortcode>/
 *   https://www.instagram.com/reel/<shortcode>/
 * Robust to: query strings, trailing slash variance, http vs https, www vs
 * no-www. For Instagram, matches on the shortcode via ILIKE against the
 * stored permalink rather than exact-match so users pasting from Share →
 * Copy Link (which adds utm_source) or pasting without the trailing slash
 * still resolve. Returns the DB id or null if no match.
 */
async function resolveQuotePostIdFromUrl(url: string, userId: string): Promise<string | null> {
	const trimmed = url.trim();
	if (!trimmed) return null;

	// Threads: /@<user>/post/<id>  (regex already tolerates trailing slash,
	// query params, www/no-www, http/https.)
	const threadsMatch = trimmed.match(/threads\.(?:com|net)\/@[^/]+\/post\/([A-Za-z0-9_-]+)/);
	if (threadsMatch) {
		const { data } = await supabase
			.from("posts")
			.select("id")
			.eq("user_id", userId)
			.eq("threads_post_id", threadsMatch[1])
			.maybeSingle();
		return data?.id ?? null;
	}

	// Instagram: extract the shortcode from /p/<code>/ or /reel/<code>/, then
	// ILIKE-match against the stored permalink. Exact-match was brittle — it
	// failed on pasted URLs with query strings or missing trailing slashes.
	const igMatch = trimmed.match(/instagram\.com\/(?:p|reel|tv)\/([A-Za-z0-9_-]+)/);
	if (igMatch) {
		const shortcode = igMatch[1];
		const { data } = await supabase
			.from("posts")
			.select("id")
			.eq("user_id", userId)
			.ilike("permalink", `%/${shortcode}/%`)
			.maybeSingle();
		return data?.id ?? null;
	}

	return null;
}

// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped
export async function createPost(post: any): Promise<any> {
	const sanitizedMediaUrls = sanitizeMediaURLs(post.mediaUrls || []);
	const sanitizedContent = sanitizeComposerContent(post, sanitizedMediaUrls);
	const onPublishStage =
		typeof post.onPublishStage === "function"
			? (post.onPublishStage as (stage: PublishStage) => void)
			: null;

	if (post.status === "published" || post.status === "scheduled") {
		onPublishStage?.("preflight");
		const preflight = await preflightPost(post);
		if (preflight.ok === false) {
			throw new Error(
				preflight.issues?.find((issue) => issue.severity === "error")?.message ||
					"Publish preflight failed",
			);
		}
	}

	const userId = await getUserIdAsync();
	const {
		data: { session },
	} = await supabase.auth.getSession();

	// Resolve quoteUrl → quotePostId once, before the publish/draft branching.
	// Composer sends a URL; callers that already have a DB id can pass quotePostId
	// directly and skip the lookup. An unmatched URL surfaces as a clear error
	// rather than silently dropping.
	let resolvedQuotePostId: string | null = post.quotePostId ?? null;
	if (!resolvedQuotePostId && post.quoteUrl) {
		resolvedQuotePostId = await resolveQuotePostIdFromUrl(post.quoteUrl, userId);
		if (!resolvedQuotePostId) {
			throw new Error(
				"Quoted post URL does not match any of your published posts. Paste the permalink of the post you want to quote.",
			);
		}
	}

	if (post.status === "published") {
		const platform = post.platform || "threads";
		onPublishStage?.("publishing");
		const publishRequestId = randomUUID();

		const response = await fetch(apiUrl("/api/posts?action=publish"), {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session?.access_token}`,
				"X-Request-Id": publishRequestId,
				...(post.asyncPublish ? { Prefer: "respond-async" } : {}),
				"Idempotency-Key":
					post.idempotencyKey ||
					`publish-post:${platform}:${post.accountId || post.instagramAccountId || "unknown"}:${publishRequestId}`,
			},
			body: JSON.stringify({
				platform,
				accountId: platform === "threads" ? post.accountId : undefined,
				instagramAccountId:
					platform === "instagram" ? post.instagramAccountId : undefined,
				igMediaType: post.igMediaType || undefined,
				altText: post.altText || undefined,
				content: sanitizedContent,
				media: sanitizedMediaUrls.map((url: string, index: number) => ({
					type: detectMediaType(url),
					url,
					altText: post.mediaAltTexts?.[index] || post.altText || undefined,
				})),
				topics: post.topics || [],
				crossPostGroupId: post.crossPostGroupId || undefined,
				linkUrl: post.linkUrl || undefined,
				locationId: post.locationId || undefined,
				quotePostId: resolvedQuotePostId || undefined,
				collaborators: post.collaborators || undefined,
				pollAttachment: post.pollAttachment || undefined,
				isSpoiler: post.isSpoiler || undefined,
				textSpoilers: post.textSpoilers || undefined,
				allowlistedCountryCodes: post.allowlistedCountryCodes || undefined,
				isTrialReel: post.isTrialReel || undefined,
				replyApprovalMode: post.replyApprovalMode || undefined,
				gifAttachment: post.gifAttachment || undefined,
				isGhostPost: post.isGhostPost || undefined,
				crossreshareToIg: post.crossreshareToIg || undefined,
				crossreshareToIgDarkMode: post.crossreshareToIgDarkMode || undefined,
				textAttachment: post.textAttachment || undefined,
				settings: post.settings || {
					allowReplies: true,
					whoCanReply: "everyone",
				},
				// Composer fields that used to silently drop at publish.
				persona: post.persona || undefined,
				crossFb: post.crossFb || undefined,
				firstComment: post.firstComment || undefined,
				userTags: post.userTags || undefined,
				productTags: post.productTags || undefined,
				brandedContentSponsorIds: post.brandedContentSponsorIds || undefined,
				isPaidPartnership: post.isPaidPartnership || undefined,
				shareToFeed: post.shareToFeed,
				graduation: post.graduation || undefined,
				thumbOffset: post.thumbOffset ?? post.reelCover ?? undefined,
				reelCover: post.reelCover ?? undefined,
				coverUrl: post.coverUrl || undefined,
				audioName: post.audioName || undefined,
				igAudioId: post.igAudioId || undefined,
				commentEnabled: post.commentEnabled,
				threadChain: post.threadChain || undefined,
				ghostDuration: post.ghostDuration || undefined,
				replyToId: post.replyToId || undefined,
			}),
		});

		if (!response.ok) {
			const error = await response.json();
			throw new Error(error.error || "Failed to publish post");
		}

		const data = await response.json();
		if (response.status === 202 && data?.jobId) {
			onPublishStage?.("queued");
			return pollPublishJob(String(data.jobId), session?.access_token, onPublishStage);
		}
		onPublishStage?.(data?.status === "processing" ? "processing" : "published");
		return data;
	}

	const platform = post.platform || "threads";
	if (post.status === "scheduled") {
		onPublishStage?.("scheduling");
		const scheduleRequestId = randomUUID();
		const media = sanitizedMediaUrls.map((url: string, index: number) => ({
			type: detectMediaType(url),
			url,
			altText: post.mediaAltTexts?.[index] || post.altText || undefined,
		}));

		const response = await fetch(apiUrl("/api/posts?action=schedule"), {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session?.access_token}`,
				"X-Request-Id": scheduleRequestId,
				"Idempotency-Key":
					post.idempotencyKey ||
					`schedule-post:${platform}:${post.accountId || post.instagramAccountId || "unknown"}:${scheduleRequestId}`,
			},
			body: JSON.stringify({
				platform,
				accountId: platform === "threads" ? post.accountId : undefined,
				instagramAccountId:
					platform === "instagram" ? post.instagramAccountId : undefined,
				content: sanitizedContent,
				scheduledFor: post.scheduledDate,
				publishMode: post.publishMode || undefined,
				media,
				mediaType:
					platform === "instagram"
						? post.igMediaType || post.mediaType || undefined
						: post.mediaType || undefined,
				pollOptions: Array.isArray(post.pollAttachment?.options)
					? post.pollAttachment.options
					: undefined,
				quotePostId: resolvedQuotePostId || undefined,
				linkUrl: post.linkUrl || undefined,
				gifAttachment: post.gifAttachment || undefined,
				textAttachment: post.textAttachment || undefined,
				locationId: post.locationId || undefined,
				topicTag: post.topics?.[0] || post.topicTag || undefined,
				textSpoilers: post.textSpoilers || undefined,
				isSpoilerMedia: post.isSpoiler || undefined,
				crossreshareToIg:
					post.crossreshareToIg || post.crossFb || undefined,
				crossreshareToIgDarkMode:
					post.crossreshareToIgDarkMode || undefined,
				settings: post.settings || {
					allowReplies: true,
					whoCanReply: "everyone",
				},
				altText: post.altText || undefined,
				collaborators: post.collaborators || undefined,
				replyApprovalMode: post.replyApprovalMode || undefined,
				isGhostPost: post.isGhostPost || undefined,
				threadChain: post.threadChain || undefined,
				replyToId: post.replyToId || undefined,
				persona: post.persona || undefined,
				coverUrl: post.coverUrl || undefined,
				shareToFeed: post.shareToFeed,
				userTags: post.userTags || undefined,
				trialReels: post.isTrialReel || post.trialReels || undefined,
				isTrialReel: post.isTrialReel || undefined,
				thumbOffset: post.thumbOffset ?? post.reelCover ?? undefined,
				audioName: post.audioName || undefined,
				igAudioId: post.igAudioId || undefined,
				productTags: post.productTags || undefined,
				brandedContentSponsorIds:
					post.brandedContentSponsorIds || undefined,
				isPaidPartnership: post.isPaidPartnership || undefined,
				commentEnabled: post.commentEnabled,
				graduation: post.graduation || undefined,
				firstComment: post.firstComment || undefined,
				ghostDuration: post.ghostDuration || undefined,
				metadata: post.metadata || undefined,
			}),
		});

		const data = await response.json();
		if (!response.ok) {
			throw new Error(data.error || "Failed to schedule post");
		}
		onPublishStage?.("queued");
		return {
			id: data.postId,
			...post,
			content: sanitizedContent,
			mediaUrls: sanitizedMediaUrls,
			scheduledFor: data.scheduledFor,
			publishMode: data.publishMode || post.publishMode,
			qstashMessageId: data.qstashMessageId,
			exactDispatchScheduled: data.exactDispatchScheduled,
		};
	}

	const inferredMediaType =
		sanitizedMediaUrls.length > 1
			? "CAROUSEL"
			: sanitizedMediaUrls.length === 1
				? detectMediaType(sanitizedMediaUrls[0]!) === "video"
					? "VIDEO"
					: "IMAGE"
				: "TEXT";
	const mediaType = normalizePostMediaType(
		platform === "instagram"
			? post.igMediaType || inferredMediaType
			: inferredMediaType,
		platform === "instagram" ? "image" : "text",
	);

	const advancedFeatures = compactRecord({
		pollAttachment: post.pollAttachment || null,
		isSpoiler: post.isSpoiler || false,
		textSpoilers: post.textSpoilers || null,
		allowlistedCountryCodes: post.allowlistedCountryCodes || null,
		linkUrl: post.linkUrl || null,
		gifAttachment: post.gifAttachment || null,
		textAttachment: post.textAttachment || null,
		settings: post.settings || null,
		ghostDuration: post.ghostDuration || null,
		crossreshareToIg: post.crossreshareToIg || post.crossFb || null,
		crossreshareToIgDarkMode: post.crossreshareToIgDarkMode || null,
		mediaAltTexts: post.mediaAltTexts || null,
		collaborators: post.collaborators || null,
		coverUrl: post.coverUrl || null,
		shareToFeed: post.shareToFeed,
		userTags: post.userTags || null,
		productTags: post.productTags || null,
		brandedContentSponsorIds: post.brandedContentSponsorIds || null,
		isPaidPartnership: post.isPaidPartnership || null,
		trialReels: post.isTrialReel || post.trialReels || null,
		trialGraduationStrategy: post.graduation || null,
		thumbOffset: post.thumbOffset ?? post.reelCover ?? null,
		audioName: post.audioName || null,
		igAudioId: post.igAudioId || null,
		commentEnabled: post.commentEnabled,
		firstComment: post.firstComment || null,
		...(post.metadata || {}),
	});

	// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped
	const insertData: Record<string, any> = {
		user_id: userId,
		content: sanitizedContent,
		media_urls: sanitizedMediaUrls,
		media_type: mediaType,
		status: post.status || "draft",
		scheduled_for: post.scheduledDate || null,
		platform,
		location_id: post.locationId || null,
		quoted_post_id: resolvedQuotePostId,
		is_quote: !!resolvedQuotePostId,
		is_carousel: sanitizedMediaUrls.length > 1,
		hashtags: post.topics || [],
		metadata: advancedFeatures,
		cross_post_group_id: post.crossPostGroupId || null,
		persona: post.persona ?? null,
		cross_fb: !!post.crossFb,
		first_comment: post.firstComment ?? null,
		user_tags: post.userTags ?? null,
		product_tags: post.productTags ?? null,
		share_to_feed: post.shareToFeed ?? true,
		graduation: post.graduation ?? null,
		reel_cover: post.thumbOffset ?? post.reelCover ?? null,
		cover_url: post.coverUrl ?? null,
		audio_name: post.audioName ?? null,
		thread_chain: !!post.threadChain,
		reply_to_id: post.replyToId ?? null,
	};

	if (platform === "instagram") {
		insertData.instagram_account_id = post.instagramAccountId;
		insertData.ig_media_type = post.igMediaType || null;
		insertData.alt_text = post.altText || null;
		insertData.collaborators = post.collaborators || null;
		insertData.account_id = null;
	} else {
		insertData.account_id = post.accountId;
	}

	const { data, error } = await supabase
		.from("posts")
		// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped
		.insert(insertData as any)
		.select()
		.maybeSingle();

	if (error) {
		logger.error("Failed to create post:", error);
		throw error;
	}
	if (!data) throw new Error("Failed to create post: no data returned");

	return {
		id: data.id,
		...post,
		content: sanitizedContent,
		mediaUrls: sanitizedMediaUrls,
	};
}

// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped
export async function updatePost(id: string, updates: any): Promise<any> {
	const userId = await getUserIdAsync();

	// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped
	const updateData: any = {
		updated_at: new Date().toISOString(),
	};

	if (updates.content !== undefined) updateData.content = updates.content;
	if (updates.status !== undefined) updateData.status = updates.status;
	if (updates.scheduledDate !== undefined)
		updateData.scheduled_for = updates.scheduledDate;
	if (updates.mediaUrls !== undefined)
		updateData.media_urls = updates.mediaUrls;
	if (updates.metadata !== undefined)
		updateData.metadata = updates.metadata;
	if (updates.mediaUrls !== undefined) {
		updateData.media_type = normalizePostMediaType(
			updates.mediaUrls.length > 1
				? "CAROUSEL"
				: updates.mediaUrls.length === 1
					? detectMediaType(updates.mediaUrls[0]) === "video"
						? "VIDEO"
						: "IMAGE"
					: "TEXT",
		);
	}

	const { error } = await supabase
		.from("posts")
		.update(updateData)
		.eq("id", id)
		.eq("user_id", userId);

	if (error) {
		logger.error("Failed to update post:", error);
		throw error;
	}

	return { id, ...updates };
}

export async function updateCampaignFactoryAudioState(
	postIds: string[],
	action: CampaignFactoryAudioBatchAction,
	options: {
		note?: string | undefined;
		proofUrl?: string | undefined;
		proofType?: string | undefined;
		proofNote?: string | undefined;
		selectedAudioId?: string | undefined;
		nowIso?: string | undefined;
	} = {},
): Promise<{
	posts: Array<Record<string, unknown>>;
	eventsWritten: number;
	skipped: Array<{ postId: string; reason: string }>;
}> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	const response = await fetch(apiUrl("/api/posts?action=campaign-factory-audio"), {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
			"X-Request-Id": randomUUID(),
		},
		body: JSON.stringify({
			postIds,
			action,
			note: options.note || undefined,
			proofUrl: options.proofUrl || undefined,
			proofType: options.proofType || undefined,
			proofNote: options.proofNote || undefined,
			selectedAudioId: options.selectedAudioId || undefined,
			nowIso: options.nowIso || undefined,
		}),
	});
	const data = (await response.json().catch(() => null)) as
		| {
				posts?: Array<Record<string, unknown>>;
				eventsWritten?: number;
				skipped?: Array<{ postId: string; reason: string }>;
				error?: string;
		  }
		| null;
	if (!response.ok) {
		throw new Error(data?.error || "Failed to update Campaign Factory audio state");
	}
	return {
		posts: data?.posts || [],
		eventsWritten: data?.eventsWritten || 0,
		skipped: data?.skipped || [],
	};
}

export async function fetchCampaignFactoryAudioEvents(
	filters: CampaignFactoryAudioEventFilters,
): Promise<CampaignFactoryAudioEvent[]> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	const params = new URLSearchParams({ action: "campaign-factory-audio-events" });
	if (filters.postId) params.set("postId", filters.postId);
	if (filters.campaignId) params.set("campaignId", filters.campaignId);
	if (filters.renderedAssetId) params.set("renderedAssetId", filters.renderedAssetId);
	if (typeof filters.limit === "number" && Number.isFinite(filters.limit)) {
		params.set("limit", String(Math.max(1, Math.floor(filters.limit))));
	}

	const response = await fetch(apiUrl(`/api/posts?${params.toString()}`), {
		headers: {
			Authorization: `Bearer ${session?.access_token}`,
			"X-Request-Id": randomUUID(),
		},
	});
	const data = (await response.json().catch(() => null)) as
		| { events?: unknown[]; error?: string }
		| null;
	if (!response.ok) {
		throw new Error(data?.error || "Failed to load Campaign Factory audio events");
	}
	const events = data?.events;
	return (Array.isArray(events) ? events : []).map(parseCampaignFactoryAudioEvent);
}

export async function deletePost(id: string): Promise<void> {
	const userId = await getUserIdAsync();
	const {
		data: { session },
	} = await supabase.auth.getSession();

	const { data: post } = await supabase
		.from("posts")
		.select("threads_post_id")
		.eq("id", id)
		.eq("user_id", userId)
		.maybeSingle();

	if (post?.threads_post_id) {
		const deleteRequestId = randomUUID();
		const response = await fetch(apiUrl("/api/posts?action=delete"), {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session?.access_token}`,
				"X-Request-Id": deleteRequestId,
				"Idempotency-Key": `delete-post:${id}:${deleteRequestId}`,
			},
			body: JSON.stringify({ postId: id }),
		});

		if (!response.ok) {
			const error = await response.json();
			throw new Error(error.error || "Failed to delete post");
		}
		return;
	}

	const { error } = await supabase
		.from("posts")
		.delete()
		.eq("id", id)
		.eq("user_id", userId);

	if (error) {
		logger.error("Failed to delete post:", error);
		throw error;
	}
}

export async function repostPost(
	accountId: string,
	mediaId: string,
): Promise<{ success: boolean; repostId?: string | undefined }> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	const response = await fetch(apiUrl("/api/posts?action=repost"), {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
			"Idempotency-Key": `repost:${accountId}:${mediaId}`,
		},
		body: JSON.stringify({ accountId, mediaId }),
	});

	if (!response.ok) {
		const error = await response.json();
		throw new Error(error.error || "Failed to repost");
	}

	return response.json();
}

export async function fetchGhostPosts(
	accountId: string,
	// biome-ignore lint/suspicious/noExplicitAny: API response shape
): Promise<any[]> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	const response = await fetch(apiUrl("/api/posts?action=ghost-posts"), {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({ accountId }),
	});

	if (!response.ok) {
		const error = await response.json();
		throw new Error(error.error || "Failed to fetch ghost posts");
	}

	const data = await response.json();
	return data.posts || [];
}

export async function fetchConversation(
	accountId: string,
	mediaId: string,
	reverse = false,
	// biome-ignore lint/suspicious/noExplicitAny: API response shape
): Promise<any> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	const response = await fetch(apiUrl("/api/replies?action=conversation"), {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({ accountId, mediaId, reverse }),
	});

	if (!response.ok) {
		const error = await response.json();
		throw new Error(error.error || "Failed to fetch conversation");
	}

	return response.json();
}

export interface SendReplyInput {
	platform: "threads" | "instagram";
	/** Threads account id OR instagram account id, depending on platform. */
	accountId: string;
	/**
	 * For Threads: the parent post id on threads.net the operator is replying to.
	 * For IG: the comment_id (for a comment reply) OR the media_id (for a
	 *   top-level comment on a post). The backend disambiguates by target shape.
	 */
	replyToId: string;
	/** For IG DMs, the conversation/participant id; ignored otherwise. */
	conversationId?: string | undefined;
	/** Message text. Platform-specific length limits enforced server-side. */
	content: string;
	/** 'dm' | 'comment' | 'reply' — lets the backend pick the right Meta endpoint. */
	kind: "dm" | "comment" | "reply";
	/** Stable per-click key so retries/double-clicks do not duplicate external replies. */
	idempotencyKey?: string | undefined;
	/** Snapshot of the inbox row the operator saw before sending. */
	context?: {
		conversationId?: string | undefined;
		lastSeenAt?: string | undefined;
		lastTurnId?: string | undefined;
	} | undefined;
}

export interface SendReplyResult {
	ok: boolean;
	replyId?: string | undefined;
	error?: string | undefined;
}

/**
 * Send a reply/comment/DM via the Juno33 `/api/replies?action=send`
 * endpoint. The backend holds the Meta OAuth token (encrypted at rest),
 * resolves the right Graph API call per `kind`, and records the outgoing
 * message to `sent_replies` so the inbox thread view shows your message.
 *
 * Errors bubble up as `{ ok: false, error }` rather than throwing so the UI
 * can toast without needing a try/catch at every call site.
 */
export async function sendReply(input: SendReplyInput): Promise<SendReplyResult> {
	try {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session?.access_token) {
			return { ok: false, error: "Not signed in" };
		}
		const response = await fetch(apiUrl("/api/replies?action=send"), {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
				"Idempotency-Key":
					input.idempotencyKey ||
					`inbox-reply:${input.accountId}:${input.kind}:${input.replyToId}:${Date.now()}:${Math.random().toString(36).slice(2)}`,
			},
			body: JSON.stringify(input),
		});
		if (!response.ok) {
			const err = await response.json().catch(() => ({}));
			return { ok: false, error: err?.error || `HTTP ${response.status}` };
		}
		const json = await response.json().catch(() => ({}));
		return { ok: true, replyId: typeof json?.replyId === "string" ? json.replyId : undefined };
	} catch (err) {
		return { ok: false, error: err instanceof Error ? err.message : "Network error" };
	}
}

// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped
export async function duplicatePost(id: string): Promise<any> {
	const userId = await getUserIdAsync();

	const { data: originalPost, error: fetchError } = await supabase
		.from("posts")
		.select("*")
		.eq("id", id)
		.eq("user_id", userId)
		.maybeSingle();

	if (fetchError || !originalPost) {
		throw new Error("Post not found");
	}

	const { data, error } = await supabase
		.from("posts")
		.insert({
			user_id: userId,
			account_id: originalPost.account_id,
			content: originalPost.content,
			media_urls: originalPost.media_urls,
			status: "draft",
			threads_post_id: null,
			published_at: null,
		})
		.select()
		.maybeSingle();

	if (error) {
		logger.error("Failed to duplicate post:", error);
		throw error;
	}
	if (!data) throw new Error("Failed to duplicate post: no data returned");

	return { id: data.id };
}

// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped
export async function publishPostNow(postId: string): Promise<any> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	const response = await fetch(apiUrl("/api/posts?action=publish"), {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({ postId }),
	});

	if (!response.ok) {
		const error = await response.json();
		throw new Error(error.error || "Failed to publish post");
	}

	return response.json();
}

export async function lookupPostByUrl(postUrl: string): Promise<{
	success: boolean;
	post?: {
        		id: string;
        		text: string;
        		username: string;
        		mediaUrl?: string | undefined;
        	} | undefined;
	error?: string | undefined;
}> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	const response = await fetch(apiUrl("/api/posts?action=lookup"), {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({ postUrl }),
	});

	try {
		const data = await safeJsonParse<{
			success: boolean;
			post?: { id: string; text: string; username: string; mediaUrl?: string | undefined } | undefined;
			error?: string | undefined;
		}>(response, "Post lookup");

		if (!response.ok) {
			return {
				success: false,
				error: data.error || "Failed to look up post",
			};
		}

		return data;
	} catch (error: unknown) {
		return {
			success: false,
			error: error instanceof Error ? error.message : "Failed to look up post",
		};
	}
}

/**
 * Refresh metrics for posts with stale/zero engagement data.
 * Calls the Threads API via our backend to fetch fresh views, likes, etc.
 * Returns the number of posts updated.
 */
export async function refreshPostMetrics(
	accountId?: string,
): Promise<{ updated: number }> {
	try {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session?.access_token) return { updated: 0 };

		const response = await fetch(apiUrl("/api/posts?action=refresh-metrics"), {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ accountId }),
		});

		if (!response.ok) return { updated: 0 };
		return response.json();
	} catch {
		return { updated: 0 };
	}
}

// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped
export async function cleanupDuplicatePosts(): Promise<any> {
	const userId = await getUserIdAsync();

	const { data: posts } = await supabase
		.from("posts")
		.select("id, threads_post_id, created_at")
		.eq("user_id", userId)
		.not("threads_post_id", "is", null)
		.order("created_at", { ascending: true });

	if (!posts || posts.length === 0) {
		return { removed: 0 };
	}

	const seen = new Map<string, string>();
	const duplicateIds: string[] = [];

	for (const post of posts) {
		if (post.threads_post_id) {
			if (seen.has(post.threads_post_id)) {
				duplicateIds.push(post.id);
			} else {
				seen.set(post.threads_post_id, post.id);
			}
		}
	}

	if (duplicateIds.length > 0) {
		await supabase.from("posts").delete().in("id", duplicateIds);
	}

	return { removed: duplicateIds.length };
}
