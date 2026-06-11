/**
 * Cross-posting logic for scheduled post publishing.
 * After a post is published on one platform, optionally queues an adapted version
 * for the other platform (Threads <-> Instagram).
 */

import { logger } from "../../logger.js";
import { getRateLimitStatus } from "./rateLimit.js";
import type { CrossPostRecord } from "./shared.js";
import { db } from "./shared.js";

function trigramSimilarity(a: string, b: string): number {
	const normalize = (value: string) =>
		value
			.toLowerCase()
			.replace(/[^a-z0-9 ]/g, "")
			.replace(/\s+/g, " ")
			.trim();
	const trigrams = (value: string): Set<string> => {
		const normalized = normalize(value);
		const set = new Set<string>();
		for (let i = 0; i < normalized.length - 2; i++) {
			set.add(normalized.slice(i, i + 3));
		}
		return set;
	};

	const aTri = trigrams(a);
	const bTri = trigrams(b);
	if (aTri.size === 0 || bTri.size === 0) return 0;

	let overlap = 0;
	for (const tri of aTri) {
		if (bTri.has(tri)) overlap++;
	}
	return overlap / Math.max(aTri.size, bTri.size);
}

/**
 * After a post is successfully published, check if cross-posting is enabled
 * for the workspace and queue an adapted version for the other platform.
 */
export async function handleCrossPost(
	post: CrossPostRecord,
	sourcePlatform: "threads" | "instagram",
): Promise<void> {
	try {
		// Get workspace_id from workspace_members table
		const { data: membership } = await db()
			.from("workspace_members")
			.select("workspace_id")
			.eq("user_id", post.user_id)
			.limit(1)
			.maybeSingle();

		if (!membership?.workspace_id) return;

		// Check cross-post settings
		const { data: settings } = await db()
			.from("cross_post_settings")
			.select("*")
			.eq("workspace_id", membership.workspace_id)
			.eq("enabled", true)
			.maybeSingle();

		if (!settings) return;

		logger.info("Cross-posting", { sourcePlatform, postId: post.id });

		// Skip if this post was itself a cross-post (prevent infinite loops)
		const metadata = (post.metadata as Record<string, unknown>) || {};
		if (metadata.is_cross_post) {
			logger.info("Skipping cross-post - already a cross-post", {
				postId: post.id,
			});
			return;
		}

		const content = post.content || "";
		if (!content.trim()) return;

		// #434: Adapt content for cross-platform compatibility
		let adaptedContent = content;
		try {
			if (sourcePlatform === "threads") {
				// Threads -> Instagram: use repurposeToInstagramCaption
				const { repurposeToInstagramCaption } = await import(
					"../../../../services/aiService.js"
				);
				const parts = await repurposeToInstagramCaption(content);
				adaptedContent = parts
					.map(
						(p: { content?: string | undefined; text?: string | undefined }) =>
							p.content || p.text || "",
					)
					.join("\n\n")
					.trim();
			} else {
				// Instagram -> Threads: use repurposeForThreads (strips hashtags, shortens)
				const { repurposeForThreads } = await import(
					"../../../../services/aiService.js"
				);
				const parts = await repurposeForThreads(content);
				adaptedContent = parts
					.map(
						(p: { content?: string | undefined; text?: string | undefined }) =>
							p.content || p.text || "",
					)
					.join("\n\n")
					.trim();
			}
		} catch (aiErr) {
			// Fail closed: reusing near-identical content across platforms hurts originality.
			logger.warn("AI adaptation failed, skipping cross-post", {
				error: String(aiErr),
				postId: post.id,
				sourcePlatform,
			});
			return;
		}

		if (!adaptedContent.trim()) return;
		const similarity = trigramSimilarity(content, adaptedContent);
		if (similarity > 0.88) {
			logger.info("Skipping cross-post - adaptation too similar to source", {
				postId: post.id,
				sourcePlatform,
				similarity: similarity.toFixed(2),
			});
			return;
		}

		// #432: Cross-post timing -- configurable delay after source publish.
		// Uses settings.delay_minutes from cross_post_settings table (default 30 min).
		const crossPostDelayMinutes = settings.delay_minutes ?? 30;
		const delayMs = crossPostDelayMinutes * 60 * 1000;
		const scheduledFor = new Date(Date.now() + delayMs).toISOString();
		const targetPlatform =
			sourcePlatform === "threads" ? "instagram" : "threads";
		// #528: Use approval_status field (not status) for approval workflow consistency
		const needsApproval = !settings.auto_approve;

		// Determine the target account
		let targetAccountId: string | null = null;

		if (targetPlatform === "instagram") {
			// Find an IG account belonging to this user
			const { data: igAccounts } = await db()
				.from("instagram_accounts")
				.select("id")
				.eq("user_id", post.user_id)
				.limit(1);

			targetAccountId = igAccounts?.[0]?.id || null;
		} else {
			// Find a Threads account belonging to this user
			const { data: thAccounts } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", post.user_id)
				.limit(1);

			targetAccountId = thAccounts?.[0]?.id || null;
		}

		if (!targetAccountId) {
			logger.info("No target account found for cross-post", {
				targetPlatform,
				userId: post.user_id,
			});
			return;
		}

		// Pre-check rate limit (read-only) before creating the cross-post.
		// The actual increment happens AFTER the INSERT succeeds to avoid
		// wasting rate limit quota if the INSERT fails.
		try {
			if (targetPlatform === "instagram") {
				// Read-only IG rate limit check (Instagram allows 100 posts/24h).
				// `ig_rate_limit_tracking` exists in supabase types as itself —
				// the prior `as "posts"` cast was a phantom-column-class bypass
				// that hid any future divergence between the typed `posts` row
				// and `ig_rate_limit_tracking`. The real table is small enough
				// that a typed query is fine.
				const { data: igRateData, error: igRateError } = await db()
					.from("ig_rate_limit_tracking")
					.select("daily_count")
					.eq("account_id", targetAccountId)
					.maybeSingle();
				const igDailyCount = igRateData?.daily_count ?? 0;
				if (!igRateError && igRateData && igDailyCount >= 100) {
					logger.warn(
						"[cross-post] IG rate limit exceeded, skipping cross-post",
						{
							targetAccountId,
							dailyCount: igDailyCount,
						},
					);
					return;
				}
			} else {
				// Read-only Threads rate limit check
				const rateStatus = await getRateLimitStatus(targetAccountId);
				if (
					rateStatus &&
					(rateStatus.hourlyRemaining <= 0 || rateStatus.dailyRemaining <= 0)
				) {
					logger.warn(
						"[cross-post] Threads rate limit exceeded, skipping cross-post",
						{
							targetAccountId,
							hourlyRemaining: rateStatus.hourlyRemaining,
							dailyRemaining: rateStatus.dailyRemaining,
						},
					);
					return;
				}
			}
		} catch (rlErr) {
			logger.warn(
				"[cross-post] Rate limit check exception, skipping cross-post (fail-closed)",
				{
					targetPlatform,
					targetAccountId,
					error: String(rlErr),
				},
			);
			return;
		}

		// #428: Validate media format compatibility for cross-platform
		const crossPostMediaUrls = post.media_urls || [];
		if (crossPostMediaUrls.length > 0 && targetPlatform === "instagram") {
			// IG rejects PNG for single image posts -- warn but don't block (Meta auto-converts some)
			const hasPng = crossPostMediaUrls.some((url: string) =>
				/\.png(\?|$)/i.test(url),
			);
			if (hasPng) {
				logger.warn("[cross-post] PNG media detected for IG -- may fail", {
					postId: post.id,
				});
			}
		}

		// Create the cross-posted post
		// When approval is needed, create as draft (not scheduled) so it doesn't auto-publish
		const crossPost: Record<string, unknown> = {
			user_id: post.user_id,
			content: adaptedContent,
			platform: targetPlatform,
			status: needsApproval ? "draft" : "scheduled",
			...(needsApproval ? { approval_status: "pending" } : {}),
			scheduled_for: scheduledFor,
			media_urls: crossPostMediaUrls,
			media_type: post.media_type || null,
			metadata: {
				is_cross_post: true,
				source_post_id: post.id,
				source_platform: sourcePlatform,
				adaptation_style: settings.adaptation_style,
			},
		};

		if (targetPlatform === "threads") {
			crossPost.account_id = targetAccountId;
		} else {
			crossPost.instagram_account_id = targetAccountId;
		}

		const { error: insertErr } = await db()
			.from("posts")
			// biome-ignore lint/suspicious/noExplicitAny: Supabase insert payload shape mismatch with generated types
			.insert(crossPost as any);

		if (insertErr) {
			logger.error("Failed to create cross-post", { error: insertErr.message });
			return;
		}

		// No rate limit increment here -- the read-only pre-check above guards against
		// over-scheduling, and the actual increment happens in processScheduledPosts()
		// AFTER the cross-post is successfully published. Incrementing here
		// AND at publish time would double-count, leaking quota for every cross-post.

		logger.info("Cross-post created", {
			sourcePlatform,
			targetPlatform,
			status: crossPost.status,
			scheduledFor,
		});
	} catch (err) {
		// Cross-post failures should never block the main publishing flow
		logger.error("Cross-post error (non-fatal)", { error: String(err) });
	}
}
