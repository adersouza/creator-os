// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Threads platform publishing logic for scheduled posts.
 * Handles fetching due Threads posts, validation, thread chains,
 * single post publishing, token refresh, and error handling.
 */

import { deliverNotification } from "../../deliverNotification.js";
import { decrypt } from "../../encryption.js";
import { checkSubscriptionPostLimit } from "../../handlers/posts/shared.js";
import { logger } from "../../logger.js";
import {
	enforceOutboundOperatorGuard,
	recordOutboundOperatorResult,
} from "../../outboundOperatorGuard.js";
import { runPublishPreflight } from "../../publishPreflight.js";
import { withRetry } from "../../retryUtils.js";
import { eqOrNull } from "../../supabaseSafe.js";
import type { Database, Json } from "../../../../types/supabase.js";
import type { PostData } from "../../threadsApi.js";
import { postToThreads } from "../../threadsApi.js";
import { handleCrossPost } from "./crossPost.js";
import { checkMediaUrlAccessible } from "./mediaValidation.js";
import { checkAndIncrementRateLimit, getRateLimitStatus } from "./rateLimit.js";
import type { ProcessingStats } from "./shared.js";
import { db, isTransientError, safeInsertNotification } from "./shared.js";

type PostUpdate = Database["public"]["Tables"]["posts"]["Update"];

function isPreviewScheduleOnly(metadata: Json | null | undefined): boolean {
	const campaignFactory =
		metadata && typeof metadata === "object" && !Array.isArray(metadata)
			? (metadata as Record<string, unknown>).campaign_factory
			: null;
	return (
		!!campaignFactory &&
		typeof campaignFactory === "object" &&
		!Array.isArray(campaignFactory) &&
		(campaignFactory as Record<string, unknown>).preview_schedule_only === true
	);
}

function getPostGroupId(post: Record<string, unknown>): string | null {
	if (typeof post.group_id === "string" && post.group_id.length > 0) {
		return post.group_id;
	}
	const account = post.accounts;
	if (account && typeof account === "object" && !Array.isArray(account)) {
		const groupId = (account as Record<string, unknown>).group_id;
		return typeof groupId === "string" && groupId.length > 0 ? groupId : null;
	}
	return null;
}

async function guardThreadsCronPublish(
	post: {
		id: string;
		user_id: string;
		account_id: string | null;
	},
	metadata: Record<string, unknown>,
) {
	return enforceOutboundOperatorGuard({
		db: db(),
		userId: post.user_id,
		actionName: "publish_post",
		riskLevel: "critical",
		scope: {
			groupId: getPostGroupId(post as unknown as Record<string, unknown>),
			accountId: post.account_id,
		},
		payload: {
			postId: post.id,
			platform: "threads",
			source: "scheduled-posts-cron",
			...metadata,
		},
		idempotencyKey: `publish-post:${post.id}:threads-cron${metadata.chainLength ? "-chain" : ""}`,
		metadata: {
			postId: post.id,
			platform: "threads",
			source: "scheduled-posts-cron",
			...metadata,
		},
	});
}

async function recordThreadsCronPublishResult(
	post: {
		id: string;
		user_id: string;
		account_id: string | null;
	},
	input: {
		outcome: "success" | "failure";
		message: string;
		error?: string | null;
		metadata?: Record<string, unknown>;
	},
) {
	await recordOutboundOperatorResult({
		db: db(),
		userId: post.user_id,
		actionName: "publish_post",
		riskLevel: "critical",
		scope: {
			groupId: getPostGroupId(post as unknown as Record<string, unknown>),
			accountId: post.account_id,
		},
		payload: {
			postId: post.id,
			platform: "threads",
			source: "scheduled-posts-cron",
			...(input.metadata ?? {}),
		},
		idempotencyKey: `publish-post:${post.id}:threads-cron${input.metadata?.chainLength ? "-chain" : ""}`,
		outcome: input.outcome,
		message: input.message,
		error: input.error ?? null,
		metadata: {
			postId: post.id,
			platform: "threads",
			source: "scheduled-posts-cron",
			...(input.metadata ?? {}),
		},
	});
}

/**
 * Process all due Threads scheduled posts.
 * Groups posts by account for parallel processing across accounts,
 * sequential within each account.
 */
export async function processThreadsPosts(
	stats: ProcessingStats,
	startTime: number,
	MAX_RUNTIME_MS: number,
): Promise<void> {
	const now = new Date().toISOString();

	const duePostsQuery = eqOrNull(
		db()
			.from("posts")
			.select(
				`
        id,
        user_id,
        account_id,
        content,
        media_urls,
        media_type,
        hashtags,
        quoted_post_id,
        location_id,
        metadata,
        scheduled_for,
        retry_count,
        accounts!inner (
          id,
          group_id,
          threads_user_id,
          threads_access_token_encrypted,
          username,
          is_active,
          needs_reauth,
          status,
          token_expires_at
        )
      `,
			)
			.eq("status", "scheduled")
			.lte("scheduled_for", now),
		"approval_status",
		"approved",
	);
	const { data: posts, error: postsError } = await duePostsQuery
		.eq("accounts.is_active", true) // skip accounts deactivated by tier downgrade
		.order("scheduled_for", { ascending: true })
		.limit(50);

	if (postsError) {
		logger.error("Query error", { error: postsError.message });
		throw postsError;
	}

	const publishablePosts = (posts ?? []).filter(
		(post: { metadata?: Json | null | undefined }) =>
			!isPreviewScheduleOnly(post.metadata),
	);
	const previewOnlyCount = (posts ?? []).length - publishablePosts.length;
	if (previewOnlyCount > 0) {
		logger.info("Skipping preview-only Threads scheduled posts", {
			count: previewOnlyCount,
		});
	}

	if (publishablePosts.length === 0) {
		logger.info("No Threads scheduled posts due");
		return;
	}

	stats.found = publishablePosts.length;
	logger.info("Found Threads posts to process", {
		count: publishablePosts.length,
	});
	const MAX_CONCURRENT_ACCOUNTS = 5;

	// Group posts by account for parallel processing across accounts
	const postsByAccount = new Map<string, typeof publishablePosts>();
	for (const post of publishablePosts) {
		const acctId = post.account_id || "unknown";
		if (!postsByAccount.has(acctId)) postsByAccount.set(acctId, []);
		postsByAccount.get(acctId)?.push(post);
	}

	// #OWASP-A04: Per-user tier limit cache to avoid repeated DB lookups
	const tierLimitCache = new Map<
		string,
		{ allowed: boolean; tier: string; used: number; limit: number }
	>();
	async function checkTierLimit(
		userId: string,
	): Promise<{ allowed: boolean; tier: string; used: number; limit: number }> {
		const cached = tierLimitCache.get(userId);
		if (cached) return cached;
		const result = await checkSubscriptionPostLimit(userId);
		tierLimitCache.set(userId, result);
		return result;
	}

	// Process posts for a single account sequentially (rate-limit delays between same-account posts)
	const processAccountPosts = async (accountPosts: typeof posts) => {
		for (const post of accountPosts) {
			if (Date.now() - startTime > MAX_RUNTIME_MS) {
				logger.warn("Approaching timeout", {
					published: stats.published,
					total: posts.length,
				});
				break;
			}
			const account = (post as Record<string, unknown>).accounts as {
				id: string;
				threads_user_id: string | null;
				threads_access_token_encrypted: string | null;
				username: string | null;
				group_id: string | null;
				is_active: boolean;
				needs_reauth: boolean | null;
				status: string | null;
				token_expires_at: string | null;
			} | null;

			// Defense-in-depth: skip posts for accounts deactivated by tier downgrade.
			// The query already filters is_active=true, but this guard catches any
			// edge cases where the PostgREST filter on a joined table doesn't apply.
			if (account?.is_active === false) {
				logger.info(
					"Skipping post — account deactivated after tier downgrade",
					{
						postId: post.id,
						accountId: account.id,
					},
				);
				continue;
			}

			// #OWASP-A04: Enforce subscription tier limits at publish time
			// Prevents free-tier users from publishing unlimited scheduled posts
			try {
				const tierCheck = await checkTierLimit(post.user_id);
				if (!tierCheck.allowed) {
					logger.info("Skipping post — user exceeded tier daily post limit", {
						postId: post.id,
						userId: post.user_id,
						tier: tierCheck.tier,
						used: tierCheck.used,
						limit: tierCheck.limit,
					});
					await db()
						.from("posts")
						.update({
							status: "failed",
							error_message: `Daily post limit exceeded (${tierCheck.used}/${tierCheck.limit} for ${tierCheck.tier} tier). Upgrade your plan to publish more.`,
							updated_at: new Date().toISOString(),
						})
						.eq("id", post.id)
						.eq("status", "scheduled");
					stats.failed++;
					continue;
				}
			} catch (tierErr) {
				const tierErrorMessage = String(tierErr);
				logger.warn("[scheduled-posts] Tier check failed, skipping publish", {
					postId: post.id,
					userId: post.user_id,
					error: tierErrorMessage,
				});
				stats.rateLimited++;
				stats.errors.push(
					`Post ${post.id}: tier check failed (${tierErrorMessage})`,
				);
				continue;
			}

			// Pre-flight: skip if token is expired and immediately flag the
			// account. Don't consume retry_count — it's not the post's fault.
			if (
				account?.token_expires_at &&
				new Date(account.token_expires_at) < new Date()
			) {
				await db()
					.from("accounts")
					.update({
						status: "needs_reauth",
						needs_reauth: true,
						is_active: false,
						updated_at: new Date().toISOString(),
					})
					.eq("id", account.id);

				logger.warn("Skipping post — token expired, awaiting refresh", {
					postId: post.id,
					accountId: account.id,
					expiredAt: account.token_expires_at,
				});
				continue;
			}

			if (
				!account?.threads_access_token_encrypted ||
				!account?.threads_user_id
			) {
				logger.warn("Skipping post - no valid account", {
					postId: post.id,
				});
				stats.failed++;
				stats.errors.push(`Post ${post.id}: Account not properly configured`);

				await db()
					.from("posts")
					.update({
						status: "failed",
						error_message: "Account not properly configured for Threads",
						updated_at: new Date().toISOString(),
					})
					.eq("id", post.id);
				await db()
					.from("notifications")
					.insert({
						user_id: post.user_id,
						type: "post_failed",
						title: "Scheduled post failed",
						message:
							"Account not properly configured for Threads. Please reconnect your account.",
						read: false,
						data: { postId: post.id },
					});
				deliverNotification({
					userId: post.user_id,
					type: "post_failed",
					title: "Scheduled post failed",
					message: "Account not properly configured for Threads.",
					data: { postId: post.id },
				}).catch((err) =>
					logger.warn("[scheduled-posts] Notification delivery failed", {
						error: String(err),
					}),
				);

				continue;
			}

			// Detect scheduled thread chains (content joined with separator)
			const CHAIN_SEPARATOR = "\n---THREAD_CHAIN_SEPARATOR---\n";
			const isThreadChain = post.content?.includes(CHAIN_SEPARATOR);

			if (isThreadChain) {
				const chainPosts = post.content
					.split(CHAIN_SEPARATOR)
					.map((p: string) => p.trim())
					.filter((p: string) => p.length > 0);

				if (chainPosts.length < 2) {
					// Malformed chain — fall through to normal single-post logic
					logger.warn(
						"Scheduled thread chain has fewer than 2 posts, publishing as single",
						{
							postId: post.id,
						},
					);
				} else {
					// Validate each post in the chain
					const tooLong = chainPosts.find(
						(p: string) => Buffer.byteLength(p, "utf8") > 500,
					);
					if (tooLong) {
						stats.failed++;
						stats.errors.push(
							`Post ${post.id}: Thread chain post exceeds 500 bytes`,
						);
						await db()
							.from("posts")
							.update({
								status: "failed",
								error_message:
									"A post in the thread chain exceeds the 500 byte limit.",
								updated_at: new Date().toISOString(),
							})
							.eq("id", post.id);
						continue;
					}

					// #469: Rate limit read-only check for chain — verify enough quota before publishing.
					// Actual increment happens after successful chain publish.
					const chainRateStatus = await getRateLimitStatus(
						post.account_id ?? "",
					);
					if (chainRateStatus) {
						const neededSlots = chainPosts.length;
						if (
							chainRateStatus.hourlyRemaining < neededSlots ||
							chainRateStatus.dailyRemaining < neededSlots
						) {
							logger.info(
								"Skipping thread chain - insufficient rate limit quota",
								{
									postId: post.id,
									needed: neededSlots,
									hourlyRemaining: chainRateStatus.hourlyRemaining,
									dailyRemaining: chainRateStatus.dailyRemaining,
								},
							);
							stats.rateLimited++;
							continue;
						}
					}

					const chainGuard = await guardThreadsCronPublish(post, {
						chainLength: chainPosts.length,
					});
					if (!chainGuard.allowed) {
						logger.warn(
							"Scheduled thread chain blocked by outbound operator guard",
							{
								postId: post.id,
								reason: chainGuard.reason,
								code: chainGuard.code,
							},
						);
						stats.rateLimited++;
						stats.errors.push(`Post ${post.id}: ${chainGuard.code}`);
						continue;
					}

					// Claim the post atomically
					const chainClaimQuery = eqOrNull(
						db()
							.from("posts")
							.update({
								status: "publishing",
								updated_at: new Date().toISOString(),
							})
							.eq("id", post.id)
							.eq("status", "scheduled"),
						"approval_status",
						"approved",
					);
					const { data: chainClaimed, error: chainClaimError } =
						await chainClaimQuery.select("id").maybeSingle();

					if (chainClaimError || !chainClaimed) {
						continue;
					}

					const postIds: string[] = [];
					try {
						let replyToId: string | null = null;

						for (let ci = 0; ci < chainPosts.length; ci++) {
							const chainContent = chainPosts[ci];
							const chainPostData: PostData = {
								content: chainContent!,
								replyToId: replyToId || undefined,
								settings: {
									allowReplies: true,
									whoCanReply: "everyone",
								},
							};

							// Retry chain posts up to 3 times (propagation delay can vary)
							let result: Awaited<ReturnType<typeof postToThreads>> | null =
								null;
							for (let attempt = 0; attempt < 3; attempt++) {
								result = await postToThreads(
									account.threads_access_token_encrypted,
									account.threads_user_id,
									chainPostData,
								);
								if (result.success && result.threadId) break;
								// Only retry "resource does not exist" for post 2+ (propagation lag)
								if (
									ci > 0 &&
									result.error?.includes("does not exist") &&
									attempt < 2
								) {
									logger.info("Chain post propagation retry", {
										ci,
										attempt,
										postId: post.id,
									});
									await new Promise((resolve) => setTimeout(resolve, 5000));
									continue;
								}
								break;
							}

							if (!result?.success || !result?.threadId) {
								throw new Error(
									`Failed to publish thread post ${ci + 1}: ${result?.error || "Unknown error"}`,
								);
							}

							postIds.push(result.threadId);
							replyToId = result.threadId;

							// Wait for post to propagate before replying to it
							if (ci < chainPosts.length - 1) {
								await new Promise((resolve) => setTimeout(resolve, 5000));
							}
						}

						// Mark as published with first post's threadId
						// Atomic guard: only publish if not rejected between SELECT and now
						const chainPublishUpdate: PostUpdate = {
							status: "published",
							published_at: new Date().toISOString(),
							updated_at: new Date().toISOString(),
						};
						if (postIds[0] !== undefined) {
							chainPublishUpdate.threads_post_id = postIds[0];
						}
						if (chainPosts[0] !== undefined) {
							chainPublishUpdate.content = chainPosts[0];
						}
						const chainPublishQuery = eqOrNull(
							db()
								.from("posts")
								.update(chainPublishUpdate)
								.eq("id", post.id)
								.eq("status", "publishing"),
							"approval_status",
							"approved",
						);
						const { data: chainPublished } =
							await chainPublishQuery.select("id");

						if (!chainPublished || chainPublished.length === 0) {
							logger.warn(
								"Post was rejected or status changed before chain publish",
								{ postId: post.id },
							);
							continue;
						}

						// #469: Increment rate limit N times for N chain posts AFTER successful publish
						try {
							for (let ri = 0; ri < chainPosts.length; ri++) {
								await checkAndIncrementRateLimit(post.account_id ?? "");
							}
						} catch (rlErr) {
							logger.warn(
								"Rate limit increment failed after chain publish (non-fatal)",
								{
									postId: post.id,
									error: String(rlErr),
								},
							);
						}
						stats.published++;
						await recordThreadsCronPublishResult(post, {
							outcome: "success",
							message: "thread chain published",
							metadata: {
								chainLength: chainPosts.length,
								threadIds: postIds,
							},
						});
						logger.info("Scheduled thread chain published", {
							postId: post.id,
							chainLength: chainPosts.length,
							threadIds: postIds,
						});

						// Anti-detection: random delay between publishes (8-25s)
						await new Promise((resolve) =>
							setTimeout(resolve, 8000 + Math.random() * 17000),
						);
					} catch (chainError: unknown) {
						const errorMsg =
							chainError instanceof Error
								? chainError.message
								: String(chainError);
						stats.failed++;
						stats.errors.push(`Post ${post.id}: ${errorMsg}`);
						const failMeta =
							postIds.length > 0
								? `${errorMsg} | Partially published: ${postIds.length}/${chainPosts.length} posts`
								: errorMsg;
						// Store structured metadata for partial chain failures
						const existingMeta =
							(post.metadata as Record<string, unknown>) || {};
						const updatedMeta = {
							...existingMeta,
							...(postIds.length > 0
								? {
										partial_chain_failure: true,
										orphaned_thread_ids: postIds,
										published_count: postIds.length,
										total_chain_length: chainPosts.length,
									}
								: {}),
						};
						await db()
							.from("posts")
							.update({
								status: "failed",
								error_message: failMeta,
								metadata: updatedMeta,
								updated_at: new Date().toISOString(),
							})
							.eq("id", post.id);

						// Notify user of thread chain failure
						await db()
							.from("notifications")
							.insert({
								user_id: post.user_id,
								type: "post_failed",
								title: "Thread chain failed",
								message: `Failed to publish thread chain: ${errorMsg}`,
								read: false,
								data: { postId: post.id, error: errorMsg },
							});
						deliverNotification({
							userId: post.user_id,
							type: "post_failed",
							title: "Thread chain failed",
							message: `Failed to publish thread chain: ${errorMsg}`,
							data: { postId: post.id, error: errorMsg },
						}).catch((err) =>
							logger.warn("[scheduled-posts] Notification delivery failed", {
								error: String(err),
							}),
						);
						await recordThreadsCronPublishResult(post, {
							outcome: "failure",
							message: "thread chain failed",
							error: errorMsg,
							metadata: {
								chainLength: chainPosts.length,
								publishedCount: postIds.length,
							},
						});
					}
					continue;
				}
			}

			// Validate content before attempting to publish
			if (!post.content || post.content.trim().length === 0) {
				logger.warn("Skipping post - empty content", { postId: post.id });
				stats.failed++;
				stats.errors.push(`Post ${post.id}: Empty content`);
				await db()
					.from("posts")
					.update({
						status: "failed",
						error_message: "Post content is empty. Please edit and reschedule.",
						updated_at: new Date().toISOString(),
					})
					.eq("id", post.id);
				await db()
					.from("notifications")
					.insert({
						user_id: post.user_id,
						type: "post_failed",
						title: "Scheduled post failed",
						message: "Post content is empty. Please edit and reschedule.",
						read: false,
						data: { postId: post.id },
					});
				deliverNotification({
					userId: post.user_id,
					type: "post_failed",
					title: "Scheduled post failed",
					message: "Post content is empty. Please edit and reschedule.",
					data: { postId: post.id },
				}).catch((err) =>
					logger.warn("[scheduled-posts] Notification delivery failed", {
						error: String(err),
					}),
				);
				continue;
			}

			const contentBytes = Buffer.byteLength(post.content, "utf8");
			if (contentBytes > 500) {
				const tooLongMsg = `Content exceeds 500 byte limit (${contentBytes} bytes). Please edit and reschedule.`;
				logger.warn("Skipping post - content exceeds 500 byte limit", {
					postId: post.id,
					length: contentBytes,
				});
				stats.failed++;
				stats.errors.push(`Post ${post.id}: Content exceeds 500 byte limit`);
				await db()
					.from("posts")
					.update({
						status: "failed",
						error_message: tooLongMsg,
						updated_at: new Date().toISOString(),
					})
					.eq("id", post.id);
				await db()
					.from("notifications")
					.insert({
						user_id: post.user_id,
						type: "post_failed",
						title: "Scheduled post failed",
						message: tooLongMsg,
						read: false,
						data: { postId: post.id },
					});
				deliverNotification({
					userId: post.user_id,
					type: "post_failed",
					title: "Scheduled post failed",
					message: tooLongMsg,
					data: { postId: post.id },
				}).catch((err) =>
					logger.warn("[scheduled-posts] Notification delivery failed", {
						error: String(err),
					}),
				);
				continue;
			}

			// #469: Check rate limits read-only BEFORE publish (don't consume quota yet).
			// Quota is incremented AFTER successful publish to avoid wasting quota on failures.
			const rateStatus = await getRateLimitStatus(post.account_id ?? "");
			if (
				rateStatus &&
				(rateStatus.hourlyRemaining <= 0 || rateStatus.dailyRemaining <= 0)
			) {
				const reason =
					rateStatus.hourlyRemaining <= 0
						? "Hourly limit reached"
						: "Daily limit reached";
				logger.info("Skipping post - rate limited", {
					postId: post.id,
					reason,
				});
				stats.rateLimited++;
				// #476: Notify user that their post was rate-limited and will retry
				try {
					const { createNotification } = await import(
						"../../createNotification.js"
					);
					await createNotification({
						userId: post.user_id,
						type: "post_rate_limited",
						title: "Post delayed — rate limit",
						message: `Your scheduled post was temporarily delayed due to platform rate limits. It will be retried automatically.`,
						data: { postId: post.id, reason },
					});
				} catch {
					// Non-critical — don't block retry
				}
				// Don't mark as failed - it will be retried next minute
				continue;
			}

			const outboundGuard = await guardThreadsCronPublish(post, {});
			if (!outboundGuard.allowed) {
				logger.warn(
					"Scheduled Threads publish blocked by outbound operator guard",
					{
						postId: post.id,
						reason: outboundGuard.reason,
						code: outboundGuard.code,
					},
				);
				stats.rateLimited++;
				stats.errors.push(`Post ${post.id}: ${outboundGuard.code}`);
				continue;
			}

			// Atomically claim this post by transitioning status from 'scheduled' to 'publishing'.
			// If another cron instance already claimed it, 0 rows are returned and we skip.
			const claimQuery = eqOrNull(
				db()
					.from("posts")
					.update({
						status: "publishing",
						updated_at: new Date().toISOString(),
					})
					.eq("id", post.id)
					.eq("status", "scheduled"),
				"approval_status",
				"approved",
			);
			const { data: claimedPost, error: claimError } = await claimQuery
				.select("id")
				.maybeSingle();

			if (claimError || !claimedPost) {
				logger.info("Post already claimed by another instance, skipping", {
					postId: post.id,
				});
				continue;
			}

			// Extract advanced features from metadata
			const metadata = (post.metadata as Record<string, unknown>) || {};

			// Convert mediaUrls (string[]) to media ({type, url}[]) for canonical postToThreads
			let mediaUrls: string[] = post.media_urls || [];

			// Resolve media library UUIDs to actual URLs if media_urls contains UUIDs instead of URLs
			// bulkScheduleGroups stores mediaIds in media_urls column as raw UUIDs
			if (mediaUrls.length > 0 && !mediaUrls[0]?.startsWith("http")) {
				const { resolveMediaUrls } = await import(
					"../../handlers/posts/shared.js"
				);
				const { urls } = await resolveMediaUrls(mediaUrls, post.user_id);
				if (urls.length > 0) {
					mediaUrls = urls;
					await db()
						.from("posts")
						.update({ media_urls: urls })
						.eq("id", post.id);
				} else {
					logger.warn(
						"Media UUID resolution returned no URLs — publishing without media",
						{ postId: post.id, ids: mediaUrls },
					);
					mediaUrls = [];
				}
			}

			// #482: Check if media URLs are still accessible before publishing
			if (mediaUrls.length > 0) {
				const mediaError = await checkMediaUrlAccessible(mediaUrls);
				if (mediaError) {
					stats.failed++;
					stats.errors.push(`Post ${post.id}: ${mediaError}`);
					await db()
						.from("posts")
						.update({
							status: "failed",
							error_message: mediaError,
							updated_at: new Date().toISOString(),
						})
						.eq("id", post.id);
					await db()
						.from("notifications")
						.insert({
							user_id: post.user_id,
							type: "post_failed",
							title: "Scheduled post failed — media expired",
							message: mediaError,
							read: false,
							data: { postId: post.id },
						});
					deliverNotification({
						userId: post.user_id,
						type: "post_failed",
						title: "Scheduled post failed — media expired",
						message: mediaError,
						data: { postId: post.id },
					}).catch((err) =>
						logger.warn("[scheduled-posts] Notification delivery failed", {
							error: String(err),
						}),
					);
					continue;
				}
			}

			const media = mediaUrls.map((url: string) => ({
				type: (!url.includes(".mp4") && !url.includes(".mov")
					? "image"
					: "video") as "image" | "video",
				url,
			}));
			const preflight = await runPublishPreflight(
				{
					platform: "threads",
					accountId: post.account_id,
					content: post.content || "",
					media,
					topics: post.hashtags || [],
					pollAttachment:
						(metadata.pollAttachment as
							| import("../../publishPreflight.js").PreflightInput["pollAttachment"]
							| undefined) || undefined,
					gifAttachment: metadata.gifAttachment,
					textAttachment:
						(metadata.textAttachment as
							| import("../../publishPreflight.js").PreflightInput["textAttachment"]
							| undefined) || undefined,
					linkUrl:
						typeof metadata.linkUrl === "string" ? metadata.linkUrl : undefined,
					topicTag:
						typeof metadata.topicTag === "string"
							? metadata.topicTag
							: undefined,
					crossreshareToIg:
						typeof metadata.crossreshareToIg === "boolean"
							? metadata.crossreshareToIg
							: undefined,
					replyToId:
						typeof metadata.replyToId === "string"
							? metadata.replyToId
							: undefined,
				},
				{
					account: {
						found: !!account,
						isActive: account?.is_active,
						needsReauth: account?.needs_reauth,
						status: account?.status,
						tokenExpiresAt: account?.token_expires_at,
						hasAccessToken: !!account?.threads_access_token_encrypted,
						hasPlatformUserId: !!account?.threads_user_id,
					},
					checkMediaUrls: true,
				},
			);
			if (!preflight.ok) {
				const message =
					preflight.issues.find((issue) => issue.severity === "error")
						?.message || "Scheduled Threads post failed preflight.";
				stats.failed++;
				stats.errors.push(`Post ${post.id}: ${message}`);
				await db()
					.from("posts")
					.update({
						status: "failed",
						error_message: message,
						updated_at: new Date().toISOString(),
					})
					.eq("id", post.id)
					.eq("status", "publishing");
				await safeInsertNotification(
					{
						user_id: post.user_id,
						type: "post_failed",
						title: "Scheduled post failed preflight",
						message,
						read: false,
						data: {
							postId: post.id,
							platform: "threads",
							preflight,
						} as unknown as Json,
					},
					{ postId: post.id, platform: "threads", accountId: account?.id },
				);
				deliverNotification({
					userId: post.user_id,
					type: "post_failed",
					title: "Scheduled post failed preflight",
					message,
					data: { postId: post.id },
				}).catch((err) =>
					logger.warn("[scheduled-posts] Notification delivery failed", {
						error: String(err),
					}),
				);
				continue;
			}

			// Text spoilers: only from metadata (manually set). No auto-detect.
			const autoDetectedSpoilers: Array<{
				entity_type: "SPOILER";
				offset: number;
				length: number;
			}> | null = null;

			// Attempt to publish
			const postData: PostData = {
				content: post.content,
				media,
				topics: post.hashtags || [],
				quotePostId: post.quoted_post_id || undefined,
				locationId: post.location_id || undefined,
				// Advanced features from metadata
				// biome-ignore lint/suspicious/noExplicitAny: Threads API publish options require any for optional fields
				pollAttachment: (metadata.pollAttachment || undefined) as any,
				// biome-ignore lint/suspicious/noExplicitAny: Threads API publish options require any for optional fields
				isSpoiler: (metadata.isSpoiler || undefined) as any,
				textSpoilers: (metadata.textSpoilers ||
					autoDetectedSpoilers ||
					// biome-ignore lint/suspicious/noExplicitAny: Threads API publish options require any for optional fields
					undefined) as any,
				allowlistedCountryCodes:
					// biome-ignore lint/suspicious/noExplicitAny: Threads API publish options require any for optional fields
					(metadata.allowlistedCountryCodes || undefined) as any,
				// biome-ignore lint/suspicious/noExplicitAny: Threads API publish options require any for optional fields
				linkUrl: (metadata.linkUrl || undefined) as any,
				gifAttachment: metadata.gifAttachment as PostData["gifAttachment"],
				textAttachment: metadata.textAttachment as PostData["textAttachment"],
				// Cross-share to Instagram Stories
				crossreshareToIg: metadata.crossreshareToIg ? true : undefined,
				crossreshareToIgDarkMode: metadata.crossreshareToIgDarkMode
					? true
					: undefined,
				settings: (metadata.settings || {
					allowReplies: true,
					whoCanReply: "everyone",
					// biome-ignore lint/suspicious/noExplicitAny: Threads API publish options require any for optional fields
				}) as any,
			};

			const result = await postToThreads(
				account.threads_access_token_encrypted,
				account.threads_user_id,
				postData,
			);

			if (result.success && result.threadId) {
				// Fetch the actual permalink from Threads API
				let permalink: string | null = null;
				try {
					const token = decrypt(account.threads_access_token_encrypted);
					const postInfoUrl = `https://graph.threads.net/v1.0/${result.threadId}?fields=id,permalink`;
					const postInfoResponse = await withRetry(
						() =>
							fetch(postInfoUrl, {
								headers: { Authorization: `Bearer ${token}` },
								signal: AbortSignal.timeout(10000),
							}),
						{ label: `scheduledPostPermalink:${result.threadId}` },
					);
					const postInfoData = await postInfoResponse.json();
					if (postInfoData.permalink) {
						permalink = postInfoData.permalink;
					}
				} catch (e) {
					logger.warn("Failed to fetch permalink", { error: String(e) });
				}

				// Atomic guard: only publish if not rejected between SELECT and now
				const updatePayload: Record<string, unknown> = {
					status: "published",
					threads_post_id: result.threadId,
					permalink: permalink,
					published_at: new Date().toISOString(),
					updated_at: new Date().toISOString(),
				};
				const publishGuardQuery = eqOrNull(
					db()
						.from("posts")
						.update(updatePayload as never)
						.eq("id", post.id)
						.eq("status", "publishing"),
					"approval_status",
					"approved",
				);
				const { data: publishGuardResult, error: guardError } =
					await publishGuardQuery.select("id");

				if (guardError) {
					logger.error("Publish guard update failed", {
						postId: post.id,
						error: guardError.message,
					});
				}

				if (!publishGuardResult || publishGuardResult.length === 0) {
					logger.warn("Post was rejected or status changed before publish", {
						postId: post.id,
					});
					continue;
				}

				await safeInsertNotification(
					{
						user_id: post.user_id,
						type: "post_published",
						title: "Scheduled post published",
						message: `Your scheduled post to @${account.username} has been published.`,
						read: false,
						data: {
							postId: post.id,
							threadId: result.threadId,
							permalink,
						},
					},
					{ postId: post.id, platform: "threads", accountId: account.id },
				);

				// #469: Increment rate limit counter AFTER successful publish
				// (avoids consuming quota on failed API calls)
				try {
					await checkAndIncrementRateLimit(post.account_id ?? "");
				} catch (rlErr) {
					// Non-fatal: post already published, rate limit is best-effort
					logger.warn("Rate limit increment failed after publish (non-fatal)", {
						postId: post.id,
						error: String(rlErr),
					});
				}
				stats.published++;
				await recordThreadsCronPublishResult(post, {
					outcome: "success",
					message: "published",
					metadata: { threadId: result.threadId },
				});
				logger.info("Published post", {
					postId: post.id,
					threadId: result.threadId,
				});

				// Anti-detection: random delay between publishes (8-25s)
				// Prevents clockwork API call patterns that flag automation
				await new Promise((resolve) =>
					setTimeout(resolve, 8000 + Math.random() * 17000),
				);

				// Cross-post: queue adapted version for Instagram if enabled
				await handleCrossPost(post, "threads");

				// Schedule engagement syncs at 1h, 6h, 24h (fire-and-forget)
				import("../../qstashSchedule.js").then(({ schedulePostPublishSyncs }) =>
					schedulePostPublishSyncs(
						post.id,
						account.id,
						post.user_id,
						"threads",
						"cron",
					),
				);

				// Give scheduled Threads publishes the same precise +15min reply-harvest
				// path as autoposted content when the account belongs to an enabled group.
				import("../../qstashSchedule.js")
					.then(async ({ dispatchReplyHarvest }) => {
						const { data: group } = await db()
							.from("account_groups")
							.select("id")
							.eq("user_id", post.user_id)
							.contains("account_ids", [account.id])
							.maybeSingle();
						if (!group?.id) return;

						const { data: groupConfig } = await db()
							.from("auto_post_group_config")
							.select("workspace_id, enable_auto_reply")
							.eq("group_id", group.id)
							.maybeSingle();
						if (!groupConfig?.workspace_id || !groupConfig.enable_auto_reply)
							return;

						await dispatchReplyHarvest({
							queueItemId: post.id,
							workspaceId: groupConfig.workspace_id,
							groupId: group.id,
							ownerId: post.user_id,
							accountId: account.id,
							postId: post.id,
							sourceTable: "posts",
						});
					})
					.catch((err: unknown) =>
						logger.warn("Scheduled Threads reply-harvest scheduling failed", {
							postId: post.id,
							error: String(err),
						}),
					);
			} else {
				const errorMsg = result.error || "Unknown publishing error";
				const currentRetryCount =
					((post as Record<string, unknown>).retry_count as number) || 0;

				// Token/OAuth errors: attempt one inline refresh before failing.
				const { isDefinitiveOAuthError } = await import("../../retryUtils.js");
				const isTokenError = isDefinitiveOAuthError(errorMsg);

				if (isTokenError) {
					logger.warn(
						"Token error during publish — attempting inline refresh",
						{
							postId: post.id,
							accountId: account.id,
							error: errorMsg,
						},
					);

					let refreshed = false;
					let refreshFailureError: string | null = null;
					try {
						const currentToken = decrypt(
							account.threads_access_token_encrypted ?? "",
						);
						const { refreshThreadsToken } = await import(
							"../../tokenRefresh.js"
						);
						const refreshResult = await refreshThreadsToken(currentToken);
						const refreshData = refreshResult.data;

						if (refreshResult.ok && refreshData.access_token) {
							const { encrypt } = await import("../../encryption.js");
							const newEncryptedToken = encrypt(
								refreshData.access_token as string,
							);
							const expiresIn = refreshData.expires_in || 5184000;

							await db()
								.from("accounts")
								.update({
									threads_access_token_encrypted: newEncryptedToken,
									token_expires_at: new Date(
										Date.now() + expiresIn * 1000,
									).toISOString(),
									updated_at: new Date().toISOString(),
								})
								.eq("id", account.id);

							// Retry the publish with the new token
							const retryResult = await postToThreads(
								newEncryptedToken,
								account.threads_user_id,
								postData,
							);

							if (retryResult.success && retryResult.threadId) {
								refreshed = true;
								// Mark as published
								const refreshPublishQuery = eqOrNull(
									db()
										.from("posts")
										.update({
											status: "published",
											threads_post_id: retryResult.threadId,
											published_at: new Date().toISOString(),
											updated_at: new Date().toISOString(),
										})
										.eq("id", post.id)
										.eq("status", "publishing"),
									"approval_status",
									"approved",
								);
								await refreshPublishQuery;

								await safeInsertNotification(
									{
										user_id: post.user_id,
										type: "post_published",
										title: "Scheduled post published",
										message: `Your scheduled post to @${account.username} has been published (after token refresh).`,
										read: false,
										data: { postId: post.id, threadId: retryResult.threadId },
									},
									{
										postId: post.id,
										platform: "threads",
										accountId: account.id,
									},
								);

								stats.published++;
								await recordThreadsCronPublishResult(post, {
									outcome: "success",
									message: "published after inline token refresh",
									metadata: { threadId: retryResult.threadId },
								});
								logger.info("Published after inline token refresh", {
									postId: post.id,
									threadId: retryResult.threadId,
								});
							}
						} else {
							refreshFailureError = String(
								refreshData?.error?.message ||
									refreshData?.error ||
									"Token refresh returned no access token",
							);
						}
					} catch (refreshErr) {
						refreshFailureError =
							refreshErr instanceof Error
								? refreshErr.message
								: String(refreshErr);
						logger.error("Inline token refresh failed", {
							postId: post.id,
							accountId: account.id,
							error: refreshFailureError,
						});
					}

					if (!refreshed) {
						const refreshWasDefinitive = isDefinitiveOAuthError(
							refreshFailureError || errorMsg,
						);
						if (!refreshWasDefinitive && currentRetryCount < 3) {
							await db()
								.from("posts")
								.update({
									status: "scheduled",
									scheduled_for: new Date(
										Date.now() + 15 * 60 * 1000,
									).toISOString(),
									retry_count: currentRetryCount + 1,
									error_message: null,
									updated_at: new Date().toISOString(),
								})
								.eq("id", post.id);

							stats.retried++;
							stats.errors.push(
								`Post ${post.id}: transient token refresh failure`,
							);
							await recordThreadsCronPublishResult(post, {
								outcome: "failure",
								message: "rescheduled after transient token refresh failure",
								error: refreshFailureError || errorMsg,
								metadata: { retryCount: currentRetryCount + 1 },
							});
							logger.warn(
								"Post rescheduled after transient token refresh failure",
								{
									postId: post.id,
									accountId: account.id,
									error: refreshFailureError,
								},
							);
							continue;
						}

						// Token refresh failed — flag account + deactivate
						await db()
							.from("accounts")
							.update({
								status: "needs_reauth",
								needs_reauth: true,
								is_active: false,
								updated_at: new Date().toISOString(),
							})
							.eq("id", account.id);

						await db()
							.from("posts")
							.update({
								status: "failed",
								error_message:
									"Account token expired. Please reconnect your account in Settings.",
								updated_at: new Date().toISOString(),
							})
							.eq("id", post.id);

						deliverNotification({
							userId: post.user_id,
							type: "token_reauth_needed",
							title: "Threads account needs reconnection",
							message: `Your scheduled post couldn't publish because the access token expired. Please reconnect your account in Settings.`,
							data: { postId: post.id, accountId: account.id },
						}).catch((err) =>
							logger.warn("[scheduled-posts] Notification delivery failed", {
								error: String(err),
							}),
						);

						stats.failed++;
						stats.errors.push(
							`Post ${post.id}: Token expired — account needs reconnection`,
						);
						await recordThreadsCronPublishResult(post, {
							outcome: "failure",
							message: "token refresh failed",
							error: refreshFailureError || errorMsg,
						});
						logger.error("Post failed — token expired, account flagged", {
							postId: post.id,
							accountId: account.id,
						});
					}
					continue;
				}

				// Auto-reschedule on transient errors (429, 5xx, timeouts) up to 3 times
				// Exponential backoff: 15min → 1h → 4h to avoid hammering Meta API
				if (isTransientError(errorMsg) && currentRetryCount < 3) {
					const backoffDelays = [15 * 60_000, 60 * 60_000, 4 * 60 * 60_000]; // 15m, 1h, 4h
					const delayMs = backoffDelays[currentRetryCount] || backoffDelays[2];
					await db()
						.from("posts")
						.update({
							status: "scheduled",
							scheduled_for: new Date(Date.now() + delayMs!).toISOString(),
							retry_count: currentRetryCount + 1,
							error_message: null,
							updated_at: new Date().toISOString(),
						})
						.eq("id", post.id);

					stats.retried++;
					await recordThreadsCronPublishResult(post, {
						outcome: "failure",
						message: "rescheduled after transient error",
						error: errorMsg,
						metadata: { retryCount: currentRetryCount + 1 },
					});
					logger.info("Auto-rescheduled post on transient error", {
						postId: post.id,
						retryCount: currentRetryCount + 1,
						error: errorMsg,
					});
				} else {
					// Permanent failure or retries exhausted
					await db()
						.from("posts")
						.update({
							status: "failed",
							error_message: errorMsg,
							updated_at: new Date().toISOString(),
						})
						.eq("id", post.id);

					await db()
						.from("notifications")
						.insert({
							user_id: post.user_id,
							type: "post_failed",
							title: "Scheduled post failed",
							message: `Failed to publish scheduled post: ${errorMsg}`,
							read: false,
							data: {
								postId: post.id,
								error: errorMsg,
							},
						});
					deliverNotification({
						userId: post.user_id,
						type: "post_failed",
						title: "Scheduled post failed",
						message: `Failed to publish scheduled post: ${errorMsg}`,
						data: { postId: post.id, error: errorMsg },
					}).catch((err) =>
						logger.warn("[scheduled-posts] Notification delivery failed", {
							error: String(err),
						}),
					);

					stats.failed++;
					stats.errors.push(`Post ${post.id}: ${errorMsg}`);
					await recordThreadsCronPublishResult(post, {
						outcome: "failure",
						message: "publish failed",
						error: errorMsg,
					});
					logger.error("Failed post", {
						postId: post.id,
						error: errorMsg,
					});
				}
			}

			// Rate limiting delay between posts to the SAME account
			await new Promise((resolve) => setTimeout(resolve, 2000));
		}
	}; // end processAccountPosts

	// Process accounts in parallel (up to MAX_CONCURRENT_ACCOUNTS), posts within each account sequentially
	const accountGroups = Array.from(postsByAccount.values());
	for (let i = 0; i < accountGroups.length; i += MAX_CONCURRENT_ACCOUNTS) {
		const batch = accountGroups.slice(i, i + MAX_CONCURRENT_ACCOUNTS);
		await Promise.all(batch.map(processAccountPosts));
	}
}
