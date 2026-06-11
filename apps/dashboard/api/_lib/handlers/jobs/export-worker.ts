// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * GDPR Data Export Background Worker
 *
 * Dispatched by QStash from api/user/export.ts.
 * Queries all user data, uploads JSON to Supabase Storage, notifies user.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../../privilegedDb.js";
import { verifyQStashSignature } from "../../qstash.js";

// --- Explicit column lists (exclude encrypted tokens from GDPR export) ---

const ACCOUNTS_COLUMNS = [
	"id",
	"user_id",
	"username",
	"display_name",
	"avatar_url",
	"bio",
	"threads_user_id",
	"followers_count",
	"following_count",
	"posts_count",
	"is_active",
	"status",
	"needs_reauth",
	"token_expires_at",
	"last_synced_at",
	"last_sync_at",
	"last_sync_cursor",
	"last_webhook_reply_at",
	"webhook_replies_active",
	"last_milestone_celebrated",
	"group_id",
	"ai_config",
	"created_at",
	"updated_at",
	"posting_method",
	"sync_cohort",
	"cohort_updated_at",
	"baseline_followers_count",
	"baseline_following_count",
	"baseline_posts_count",
	"consecutive_refresh_failures",
].join(", ");

const INSTAGRAM_ACCOUNTS_COLUMNS = [
	"id",
	"user_id",
	"username",
	"display_name",
	"avatar_url",
	"instagram_user_id",
	"facebook_page_id",
	"facebook_page_name",
	"account_type",
	"login_type",
	"follower_count",
	"following_count",
	"media_count",
	"is_active",
	"status",
	"needs_reauth",
	"token_expires_at",
	"last_synced_at",
	"last_milestone_celebrated",
	"group_id",
	"ai_config",
	"created_at",
	"updated_at",
	"sync_cohort",
	"cohort_updated_at",
	"baseline_follower_count",
	"baseline_following_count",
	"baseline_media_count",
	"consecutive_refresh_failures",
].join(", ");

// --- Table lists (mirrored from original export.ts) ---

const TABLES_BY_USER_ID = [
	"posts",
	"account_analytics",
	"audience_demographics",
	"anomaly_alerts",
	"ai_feedback",
	"notifications",
	"auto_post_queue",
	"publish_attempts",
	"sent_replies",
	"scheduled_posts",
	"feature_usage",
	"milestones",
	"referral_codes",
	"link_pages",
	"post_metric_history",
	"ig_dm_templates",
	"ig_auto_responders",
	"user_settings",
	"account_groups",
	"workspace_members",
	"competitors",
	"listening_alerts",
	"trend_forecasts",
	"unified_links",
	"ig_hashtag_tracking",
	"copilot_memory",
	"saved_competitor_posts",
	"smart_links",
	"ai_style_guidelines",
	"cross_post_settings",
	"domain_verifications",
	"teams",
	"api_keys",
	"push_subscriptions",
	"webhook_subscriptions",
	"recommendation_dismissals",
	"post_success_signals",
	"viral_score_calibration",
	"account_daily_summary",
	"influencer_collabs",
	"api_usage",
	"audit_logs",
	// Round 13 GDPR audit
	"agent_actions",
	"draft_folders",
	"post_templates",
	"rss_feeds",
	"content_repurposing",
	"quick_wins",
	"inbox_dm_cache",
	"inbox_dm_messages",
	"trending_topic_config",
	"agent_approvals",
	"trend_discoveries",
	"group_analytics",
	// Round 14 GDPR audit
	"agent_notes",
	"revenue_snapshots",
	"ai_config",
	"mentions",
	"favorites",
	// Round 15 GDPR audit
	"account_health_snapshots",
	"competitor_metrics_history",
	// Round 16 GDPR audit
	"auto_self_replies",
	"auto_cross_replies",
	// Round 17 GDPR audit (local-first)
	"ig_collab_invites",
	// Round 18 GDPR audit (chart annotations, tags, reports, SOV)
	"chart_annotations",
	"post_tags",
	"user_tag_palette",
	"report_schedules",
	"reports",
	"demographics_snapshots",
	"recovery_codes",
	"shared_reports",
	"share_of_voice_history",
	// Round 19 GDPR audit (dashboard morning brief)
	"overnight_briefs",
	// Round 20 GDPR audit (analytics saved views)
	"saved_views",
	// Round 21 GDPR audit (Inbox, Composer, Content Library, Settings, Calendar)
	"post_originality_signals",
	"autopilot_runs",
	"inbox_ai_suggestions",
	"post_variants",
	"post_channel_diffs",
	"voice_context_files",
	"ai_action_log",
	"content_collections",
	"user_webhooks",
	"portfolio_account_health",
	"calendar_reschedule_log",
	"saved_nl_queries",
	// Round 22 GDPR audit (Campaign Factory native-audio audit)
	"campaign_factory_audio_events",
	"campaign_factory_post_links",
	"proof_runs",
	"quarantined_assets",
	"operator_kill_switches",
	// Round 23 GDPR audit (Campaign scheduling manager)
	"campaign_schedule_batch_items",
	"campaign_schedule_batches",
	// Baseline replay user-data tables
	"media_folders",
	"media",
	"queue_slots",
	"user_preferences",
	"workspace_activity",
] as const;

const TABLES_BY_ACCOUNT_ID = [
	"rate_limit_tracking",
	"ig_rate_limit_tracking",
	"ig_endpoint_rate_limits",
	"ig_pending_containers",
	"auto_reply_logs",
	"auto_reply_queue",
	"auto_post_activity",
	"sync_jobs",
	"creator_events",
	"ig_webhook_events",
	"threads_webhook_events",
	"style_bibles",
] as const;

const EXPORT_PAGE_SIZE = 5000;

async function fetchAllPages<T>(
	fetchPage: (
		from: number,
		to: number,
	) =>
		| PromiseLike<{
				data: T[] | null;
				error?: { message?: string | undefined } | null | undefined;
		  }>
		| {
				data: T[] | null;
				error?: { message?: string | undefined } | null | undefined;
		  },
): Promise<T[]> {
	const rows: T[] = [];

	for (let from = 0; ; from += EXPORT_PAGE_SIZE) {
		const to = from + EXPORT_PAGE_SIZE - 1;
		const { data, error } = await fetchPage(from, to);
		if (error) {
			throw new Error(error.message || "Failed to fetch export rows");
		}
		if (!data || data.length === 0) break;
		rows.push(...data);
		if (data.length < EXPORT_PAGE_SIZE) break;
	}

	return rows;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	// Verify QStash signature
	if (!req.headers["upstash-signature-verified"]) {
		if (!(await verifyQStashSignature(req, res))) return;
	}

	const { jobId, userId: hintedUserId } = req.body || {};
	if (!jobId) {
		return apiError(res, 400, "Missing jobId");
	}

	const supabase = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.dataExportWorker,
	);
	const { data: jobRow, error: jobError } = await supabase
		.from("data_export_jobs")
		.select("id, user_id")
		.eq("id", jobId)
		.maybeSingle();
	if (jobError || !jobRow?.user_id) {
		logger.warn("[export-worker] Export job not found or missing owner", {
			jobId,
			error: jobError ? String(jobError.message || jobError) : null,
		});
		return apiError(res, 404, "Export job not found");
	}
	const userId = jobRow.user_id as string;
	if (hintedUserId && hintedUserId !== userId) {
		logger.warn("[export-worker] Ignoring mismatched body userId", {
			jobId,
			bodyUserId: hintedUserId,
			rowUserId: userId,
		});
	}

	// Mark job as processing
	await supabase
		.from("data_export_jobs")
		.update({ status: "processing" })
		.eq("id", jobId);

	const exportData: Record<string, unknown> = {
		exported_at: new Date().toISOString(),
		user_id: userId,
	};

	try {
		// Fetch user profile
		const { data: profile } = await supabase
			.from("profiles")
			.select("*")
			.eq("id", userId)
			.maybeSingle();
		exportData.profile = profile;
		if (profile?.email) exportData.email = profile.email;

		// Fetch accounts with explicit column list (excludes encrypted tokens)
		const accountsData = await fetchAllPages((from, to) =>
			supabase
				.from("accounts")
				.select(ACCOUNTS_COLUMNS)
				.eq("user_id", userId)
				.range(from, to),
		);
		if (accountsData && accountsData.length > 0)
			exportData.accounts = accountsData;

		const igAccountsData = await fetchAllPages((from, to) =>
			supabase
				.from("instagram_accounts")
				.select(INSTAGRAM_ACCOUNTS_COLUMNS)
				.eq("user_id", userId)
				.range(from, to),
		);
		if (igAccountsData && igAccountsData.length > 0)
			exportData.instagram_accounts = igAccountsData;

		// Fetch remaining tables keyed by user_id
		for (const table of TABLES_BY_USER_ID) {
			const data = await fetchAllPages((from, to) =>
				supabase.from(table).select("*").eq("user_id", userId).range(from, to),
			);
			if (data && data.length > 0) exportData[table] = data;
		}

		// Get account IDs for account-linked tables
		const accountIds: string[] = (
			(exportData.accounts as Array<{ id: string }>) || []
		).map((a) => a.id);
		const igAccountIds: string[] = (
			(exportData.instagram_accounts as Array<{ id: string }>) || []
		).map((a) => a.id);

		// Threads account-linked tables
		if (accountIds.length > 0) {
			for (const table of TABLES_BY_ACCOUNT_ID) {
				const data = await fetchAllPages((from, to) =>
					supabase
						.from(table)
						.select("*")
						.in("account_id", accountIds)
						.range(from, to),
				);
				if (data && data.length > 0) exportData[table] = data;
			}
		}

		// IG account-linked tables
		if (igAccountIds.length > 0) {
			const igUserIds = (
				(exportData.instagram_accounts as Array<{
					instagram_user_id: string;
				}>) || []
			)
				.map((a) => a.instagram_user_id)
				.filter(Boolean);

			const igPostIds = (
				(exportData.posts as Array<{ platform: string; id: string }>) || []
			)
				.filter((p) => p.platform === "instagram")
				.map((p) => p.id);

			if (igPostIds.length > 0) {
				const igComments = await fetchAllPages((from, to) =>
					supabase
						.from("ig_comments")
						.select("*")
						.in("post_id", igPostIds)
						.range(from, to),
				);
				if (igComments && igComments.length > 0)
					exportData.ig_comments = igComments;
			}

			const igMentions = await fetchAllPages((from, to) =>
				supabase
					.from("ig_mentions")
					.select("*")
					.in("ig_account_id", igAccountIds)
					.range(from, to),
			);
			if (igMentions && igMentions.length > 0)
				exportData.ig_mentions = igMentions;

			if (igUserIds.length > 0) {
				const igStories = await fetchAllPages((from, to) =>
					supabase
						.from("ig_story_insights")
						.select("*")
						.in("ig_user_id", igUserIds)
						.range(from, to),
				);
				if (igStories && igStories.length > 0)
					exportData.ig_story_insights = igStories;
			}
		}

		// Workspace data
		const workspaces = await fetchAllPages((from, to) =>
			supabase
				.from("workspaces")
				.select("*")
				.eq("owner_id", userId)
				.range(from, to),
		);
		if (workspaces && workspaces.length > 0) {
			exportData.workspaces = workspaces;
			const wsIds = (workspaces as Array<{ id: string }>).map((w) => w.id);

			// Only export owner-scoped workspace configuration here.
			// Collaborative workspace tables can contain teammate PII or activity and
			// must be exported through a dedicated workspace export path, not a
			// single-user GDPR export.
			const wsTables = [
				"auto_post_config",
				"agency_branding",
				"inspiration_config",
				"inspiration_ideas",
				"style_bibles",
				"creator_links",
			];
			for (const table of wsTables) {
				const data = await fetchAllPages((from, to) =>
					supabase
						.from(table)
						.select("*")
						.in("workspace_id", wsIds)
						.range(from, to),
				);
				if (data && data.length > 0) exportData[table] = data;
			}
		}

		// Link page children
		const linkPageIds = (
			(exportData.link_pages as Array<{ id: string }>) || []
		).map((p) => p.id);
		if (linkPageIds.length > 0) {
			const linkBenchmarks = await fetchAllPages((from, to) =>
				supabase
					.from("link_benchmarks")
					.select("*")
					.in("page_id", linkPageIds)
					.range(from, to),
			);
			if (linkBenchmarks && linkBenchmarks.length > 0)
				exportData.link_benchmarks = linkBenchmarks;

			const linkItems = await fetchAllPages((from, to) =>
				supabase
					.from("link_items")
					.select("*")
					.in("page_id", linkPageIds)
					.range(from, to),
			);
			if (linkItems && linkItems.length > 0) {
				exportData.link_items = linkItems;
				const linkItemIds = (linkItems as Array<{ id: string }>).map(
					(i) => i.id,
				);
				const linkClicks = await fetchAllPages((from, to) =>
					supabase
						.from("link_clicks")
						.select("*")
						.in("link_id", linkItemIds)
						.range(from, to),
				);
				if (linkClicks && linkClicks.length > 0)
					exportData.link_clicks = linkClicks;
			}
		}

		// Competitor-linked tables
		const competitorIds = (
			(exportData.competitors as Array<{ id: string }>) || []
		).map((c) => c.id);
		if (competitorIds.length > 0) {
			for (const table of [
				"competitor_posts",
				"competitor_alerts",
				"competitor_snapshots",
				"competitor_top_posts",
			]) {
				const data = await fetchAllPages((from, to) =>
					supabase
						.from(table)
						.select("*")
						.in("competitor_id", competitorIds)
						.range(from, to),
				);
				if (data && data.length > 0) exportData[table] = data;
			}
		}

		// Group-linked tables
		const groupIds = (
			(exportData.account_groups as Array<{ id: string }>) || []
		).map((g) => g.id);
		if (groupIds.length > 0) {
			for (const table of [
				"group_analytics",
				"auto_post_account_overrides",
				"auto_post_group_config",
				"auto_post_group_state",
			]) {
				const data = await fetchAllPages((from, to) =>
					supabase
						.from(table)
						.select("*")
						.in("group_id", groupIds)
						.range(from, to),
				);
				if (data && data.length > 0) exportData[table] = data;
			}
		}

		// Listening results
		const alertIds = (
			(exportData.listening_alerts as Array<{ id: string }>) || []
		).map((a) => a.id);
		if (alertIds.length > 0) {
			const listeningResults = await fetchAllPages((from, to) =>
				supabase
					.from("listening_results")
					.select("*")
					.in("alert_id", alertIds)
					.range(from, to),
			);
			if (listeningResults && listeningResults.length > 0)
				exportData.listening_results = listeningResults;
		}

		// Post-linked tables
		const postIds = ((exportData.posts as Array<{ id: string }>) || []).map(
			(p) => p.id,
		);
		if (postIds.length > 0) {
			const postReflections = await fetchAllPages((from, to) =>
				supabase
					.from("post_reflections")
					.select("*")
					.in("post_id", postIds)
					.range(from, to),
			);
			if (postReflections && postReflections.length > 0)
				exportData.post_reflections = postReflections;

			const igPostIds = (
				(exportData.posts as Array<{ platform: string; id: string }>) || []
			)
				.filter((p) => p.platform === "instagram")
				.map((p) => p.id);
			if (igPostIds.length > 0) {
				const carouselInsights = await fetchAllPages((from, to) =>
					supabase
						.from("ig_carousel_insights")
						.select("*")
						.in("post_id", igPostIds)
						.range(from, to),
				);
				if (carouselInsights && carouselInsights.length > 0)
					exportData.ig_carousel_insights = carouselInsights;
			}
		}

		// Auto-post engagement snapshots
		const queueItemIds = (
			(exportData.auto_post_queue as Array<{ id: string }>) || []
		).map((q) => q.id);
		if (queueItemIds.length > 0) {
			const engSnapshots = await fetchAllPages((from, to) =>
				supabase
					.from("auto_post_engagement_snapshots")
					.select("*")
					.in("queue_item_id", queueItemIds)
					.range(from, to),
			);
			if (engSnapshots && engSnapshots.length > 0)
				exportData.auto_post_engagement_snapshots = engSnapshots;
		}

		// Influencer collab posts
		const collabIds = (
			(exportData.influencer_collabs as Array<{ id: string }>) || []
		).map((c) => c.id);
		if (collabIds.length > 0) {
			const collabPosts = await fetchAllPages((from, to) =>
				supabase
					.from("influencer_collab_posts")
					.select("*")
					.in("collab_id", collabIds)
					.range(from, to),
			);
			if (collabPosts && collabPosts.length > 0)
				exportData.influencer_collab_posts = collabPosts;
		}

		// Webhook deliveries
		const webhookSubIds = (
			(exportData.webhook_subscriptions as Array<{ id: string }>) || []
		).map((w) => w.id);
		if (webhookSubIds.length > 0) {
			const webhookDeliveries = await fetchAllPages((from, to) =>
				supabase
					.from("webhook_deliveries")
					.select("*")
					.in("subscription_id", webhookSubIds)
					.range(from, to),
			);
			if (webhookDeliveries && webhookDeliveries.length > 0)
				exportData.webhook_deliveries = webhookDeliveries;
		}

		// Smart link clicks/conversions
		const unifiedLinkIds = (
			(exportData.unified_links as Array<{ id: string }>) || []
		).map((l) => l.id);
		if (unifiedLinkIds.length > 0) {
			const slClicks = await fetchAllPages((from, to) =>
				supabase
					.from("smart_link_clicks")
					.select("*")
					.in("link_id", unifiedLinkIds)
					.range(from, to),
			);
			if (slClicks && slClicks.length > 0)
				exportData.smart_link_clicks = slClicks;

			const slConversions = await fetchAllPages((from, to) =>
				supabase
					.from("smart_link_conversions")
					.select("*")
					.in("link_id", unifiedLinkIds)
					.range(from, to),
			);
			if (slConversions && slConversions.length > 0)
				exportData.smart_link_conversions = slConversions;
		}

		// Referrals
		const referrals = await fetchAllPages((from, to) =>
			supabase
				.from("referrals")
				.select("*")
				.or(`referrer_id.eq.${userId},referred_id.eq.${userId}`)
				.range(from, to),
		);
		if (referrals && referrals.length > 0) exportData.referrals = referrals;

		// RSS entries (child of rss_feeds)
		const feedIds = ((exportData.rss_feeds as Array<{ id: string }>) || []).map(
			(f) => f.id,
		);
		if (feedIds.length > 0) {
			const rssEntries = await fetchAllPages((from, to) =>
				supabase
					.from("rss_entries")
					.select("*")
					.in("feed_id", feedIds)
					.range(from, to),
			);
			if (rssEntries && rssEntries.length > 0)
				exportData.rss_entries = rssEntries;
		}

		// Upload to Supabase Storage
		const dateStr = new Date().toISOString().split("T")[0]!;
		const filePath = `exports/${userId}/${jobId}-${dateStr}.json`;
		const jsonContent = JSON.stringify(exportData, null, 2);

		const { error: uploadErr } = await supabase.storage
			.from("exports")
			.upload(filePath, jsonContent, {
				contentType: "application/json",
				upsert: true,
			});

		if (uploadErr) {
			throw new Error(`Storage upload failed: ${uploadErr.message}`);
		}

		// Update job as complete
		const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
		await supabase
			.from("data_export_jobs")
			.update({
				status: "complete",
				file_path: filePath,
				completed_at: new Date().toISOString(),
				expires_at: expiresAt,
			})
			.eq("id", jobId);

		// Notify user
		try {
			const { createNotification } = await import(
				"../../createNotification.js"
			);
			await createNotification({
				userId,
				type: "data_export_ready",
				title: "Your data export is ready",
				message:
					"Your GDPR data export has been generated and is available for download for 24 hours.",
				data: { jobId, filePath },
			});
		} catch (notifErr) {
			logger.warn("[export-worker] Notification failed (non-blocking)", {
				error: String(notifErr),
			});
		}

		logger.info("[export-worker] Export complete", { jobId, userId, filePath });
		return apiSuccess(res, { jobId });
	} catch (error) {
		logger.error("[export-worker] Failed", {
			jobId,
			userId,
			error: String(error),
		});

		await supabase
			.from("data_export_jobs")
			.update({
				status: "failed",
				error_message: error instanceof Error ? error.message : String(error),
			})
			.eq("id", jobId);

		return apiError(res, 500, "Export failed");
	}
}
