/**
 * Deletion Cascade — shared core logic for GDPR user data deletion.
 *
 * Extracted from delete.ts so both user-initiated deletion (DELETE /api/user/delete)
 * and Meta-initiated deletion (POST /api/meta/data-deletion → process-deletion)
 * use the same cascade.
 *
 * Phase 1: Direct user_id tables (leaf → parent)
 * Phase 2: Threads account_id tables
 * Phase 3: Instagram account_id tables
 * Phase 4: Cascading via parent ID lookups
 * Phase 5: Parent tables (deleted last)
 */

import { createClient } from "@supabase/supabase-js";
import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";

// ============================================================================
// Table arrays — single source of truth for GDPR cascade
// ============================================================================

// Phase 1: Tables keyed by user_id (children first, parents last)
export const USER_ID_TABLES = [
	{ table: "api_usage", key: "user_id" },
	{ table: "audit_logs", key: "user_id" },
	{ table: "push_subscriptions", key: "user_id" },
	{ table: "post_metric_history", key: "user_id" },
	{ table: "anomaly_alerts", key: "user_id" },
	{ table: "ai_feedback", key: "user_id" },
	{ table: "notifications", key: "user_id" },
	{ table: "publish_attempts", key: "user_id" },
	{ table: "scheduled_posts", key: "user_id" },
	{ table: "sent_replies", key: "user_id" },
	{ table: "feature_usage", key: "user_id" },
	{ table: "milestones", key: "user_id" },
	{ table: "ai_style_guidelines", key: "user_id" },
	{ table: "audience_demographics", key: "user_id" },
	{ table: "account_analytics", key: "user_id" },
	{ table: "cross_post_settings", key: "user_id" },
	{ table: "domain_verifications", key: "user_id" },
	{ table: "ig_hashtag_tracking", key: "user_id" },
	{ table: "ig_dm_templates", key: "user_id" },
	{ table: "ig_auto_responders", key: "user_id" },
	{ table: "user_settings", key: "user_id" },
	{ table: "referral_codes", key: "user_id" },
	{ table: "trend_forecasts", key: "user_id" },
	// Round 12
	{ table: "account_daily_summary", key: "user_id" },
	{ table: "agency_branding", key: "user_id" },
	{ table: "api_keys", key: "user_id" },
	{ table: "competitor_alerts", key: "user_id" },
	{ table: "competitor_top_posts", key: "user_id" },
	{ table: "copilot_memory", key: "user_id" },
	{ table: "post_success_signals", key: "user_id" },
	{ table: "recommendation_dismissals", key: "user_id" },
	{ table: "smart_links", key: "user_id" },
	{ table: "trend_posts", key: "user_id" },
	{ table: "viral_score_calibration", key: "user_id" },
	{ table: "webhook_subscriptions", key: "user_id" },
	// Round 13
	{ table: "agent_actions", key: "user_id" },
	{ table: "draft_folders", key: "user_id" },
	{ table: "post_templates", key: "user_id" },
	{ table: "rss_feeds", key: "user_id" },
	{ table: "content_repurposing", key: "user_id" },
	{ table: "quick_wins", key: "user_id" },
	{ table: "inbox_dm_cache", key: "user_id" },
	{ table: "inbox_dm_messages", key: "user_id" },
	{ table: "trending_topic_config", key: "user_id" },
	{ table: "agent_approvals", key: "user_id" },
	{ table: "trend_discoveries", key: "user_id" },
	{ table: "data_export_jobs", key: "user_id" },
	// Round 14
	{ table: "agent_notes", key: "user_id" },
	{ table: "revenue_snapshots", key: "user_id" },
	{ table: "ai_config", key: "user_id" },
	{ table: "mentions", key: "user_id" },
	{ table: "favorites", key: "user_id" },
	// Round 15
	{ table: "account_health_snapshots", key: "user_id" },
	{ table: "competitor_metrics_history", key: "user_id" },
	// Round 16
	{ table: "auto_self_replies", key: "user_id" },
	{ table: "auto_cross_replies", key: "user_id" },
	// Round 17
	{ table: "ig_collab_invites", key: "user_id" },
	// Round 18 (chart annotations, tags, reports, SOV)
	{ table: "chart_annotations", key: "user_id" },
	{ table: "post_tags", key: "user_id" },
	{ table: "user_tag_palette", key: "user_id" },
	{ table: "report_schedules", key: "user_id" },
	{ table: "reports", key: "user_id" },
	{ table: "demographics_snapshots", key: "user_id" },
	{ table: "recovery_codes", key: "user_id" },
	{ table: "shared_reports", key: "user_id" },
	{ table: "share_of_voice_history", key: "user_id" },
	// Round 19 (dashboard morning brief)
	{ table: "overnight_briefs", key: "user_id" },
	// Round 20 (analytics saved views)
	{ table: "saved_views", key: "user_id" },
	// Round 21 (Inbox, Composer, Content Library, Settings, Calendar)
	{ table: "post_originality_signals", key: "user_id" },
	{ table: "autopilot_runs", key: "user_id" },
	{ table: "inbox_ai_suggestions", key: "user_id" },
	{ table: "post_variants", key: "user_id" },
	{ table: "post_channel_diffs", key: "user_id" },
	{ table: "voice_context_files", key: "user_id" },
	{ table: "ai_action_log", key: "user_id" },
	{ table: "content_collections", key: "user_id" },
	{ table: "user_webhooks", key: "user_id" },
	{ table: "portfolio_account_health", key: "user_id" },
	{ table: "calendar_reschedule_log", key: "user_id" },
	{ table: "saved_nl_queries", key: "user_id" },
	// Round 22 (Campaign Factory native-audio audit)
	{ table: "campaign_factory_audio_events", key: "user_id" },
	{ table: "campaign_factory_post_links", key: "user_id" },
	{ table: "proof_runs", key: "user_id" },
	{ table: "quarantined_assets", key: "user_id" },
	{ table: "operator_kill_switches", key: "user_id" },
	// Round 23 (Campaign scheduling manager)
	{ table: "campaign_schedule_batch_items", key: "user_id" },
	{ table: "campaign_schedule_batches", key: "user_id" },
	// Baseline replay user-data tables
	{ table: "media_folders", key: "user_id" },
	{ table: "queue_slots", key: "user_id" },
	{ table: "user_preferences", key: "user_id" },
	// Workspace tables
	{ table: "workspace_members", key: "user_id" },
] as const;

// Phase 2: Tables keyed by account_id (Threads accounts)
export const ACCOUNT_ID_TABLES = [
	"auto_reply_logs",
	"auto_reply_queue",
	"rate_limit_tracking",
	"ig_rate_limit_tracking",
	"ig_endpoint_rate_limits",
	"ig_webhook_events",
	"threads_webhook_events",
	"ig_pending_containers",
	"sync_jobs",
	"auto_post_activity",
	"competitor_snapshots",
	"creator_events",
	"saved_competitor_posts",
	"style_bibles",
] as const;

// Phase 3: Tables keyed by account_id (Instagram accounts)
export const IG_ACCOUNT_ID_TABLES = [
	"ig_dm_ai_rate_limits",
	"ig_dm_ai_responses",
	"ig_comments",
	"ig_mentions",
	"ig_story_insights",
] as const;

// Phase 5: Parent tables (deleted last)
export const PARENT_TABLES = [
	{ table: "link_pages", key: "user_id" },
	{ table: "competitor_posts", key: "user_id" },
	{ table: "competitors", key: "user_id" },
	{ table: "posts", key: "user_id" },
	{ table: "account_groups", key: "user_id" },
	{ table: "instagram_accounts", key: "user_id" },
	{ table: "teams", key: "user_id" },
	{ table: "accounts", key: "user_id" },
	{ table: "profiles", key: "id" },
] as const;

// Critical tables that MUST succeed for GDPR compliance — throw on failure
export const CRITICAL_DELETE_TABLES = new Set([
	"profiles",
	"accounts",
	"instagram_accounts",
	"posts",
	"account_groups",
	"listening_alerts",
	"unified_links",
	"workspaces",
	"post_reflections",
	"domain_verifications",
	"workspace_invites",
]);

// ============================================================================
// Safe delete helper
// ============================================================================

export async function safeDelete(
	supabase: ReturnType<typeof getSupabase>,
	table: string,
	key: string,
	value: string | string[],
): Promise<void> {
	try {
		// biome-ignore lint/suspicious/noExplicitAny: dynamic table/key from deletion list
		const sb = supabase as any;
		if (Array.isArray(value)) {
			if (value.length === 0) return;
			const { error } = await sb.from(table).delete().in(key, value);
			if (error) throw error;
		} else {
			const { error } = await sb.from(table).delete().eq(key, value);
			if (error) throw error;
		}
	} catch (err) {
		if (CRITICAL_DELETE_TABLES.has(table)) {
			logger.error(`[deletion] CRITICAL: Failed to delete from ${table}`, {
				key,
				error: String(err),
			});
			throw err;
		}
		logger.warn(`[deletion] Non-critical: Failed to delete from ${table}`, {
			key,
			error: String(err),
		});
	}
}

// ============================================================================
// Core cascade — Phases 1-5
// ============================================================================

/**
 * Cancel Stripe subscription and delete the customer record.
 * Non-blocking: logs on failure. Reads stripe_customer_id from profiles
 * BEFORE the Postgres cascade (which deletes profiles last).
 */
export async function purgeStripeCustomer(userId: string): Promise<void> {
	try {
		const supabase = getSupabase();
		const { data: profile } = (await supabase
			.from("profiles")
			.select("stripe_customer_id, stripe_subscription_id")
			.eq("id", userId)
			.maybeSingle()) as {
			data: {
				stripe_customer_id?: string | null | undefined;
				stripe_subscription_id?: string | null | undefined;
			} | null;
			error: unknown;
		};

		if (!profile?.stripe_customer_id && !profile?.stripe_subscription_id) return;

		const secretKey = process.env.STRIPE_SECRET_KEY;
		if (!secretKey) {
			logger.warn("[deletion] STRIPE_SECRET_KEY not set, skipping Stripe cleanup");
			return;
		}

		const { default: Stripe } = await import("stripe");
		const stripe = new Stripe(secretKey, {
			// @ts-expect-error — holding wire-format on clover to keep SDK majors no-op against prod; SDK only types LatestApiVersion (dahlia).
			apiVersion: "2026-02-25.clover",
		});

		if (profile.stripe_subscription_id) {
			try {
				await stripe.subscriptions.cancel(profile.stripe_subscription_id);
				logger.info("[deletion] Stripe subscription cancelled", { userId });
			} catch (err) {
				// Already cancelled / not found — fine.
				logger.debug("[deletion] Stripe subscription cancel no-op", {
					userId,
					error: String(err),
				});
			}
		}

		if (profile.stripe_customer_id) {
			try {
				await stripe.customers.del(profile.stripe_customer_id);
				logger.info("[deletion] Stripe customer deleted", { userId });
			} catch (err) {
				logger.warn("[deletion] Stripe customer deletion failed (non-blocking)", {
					userId,
					error: String(err),
				});
			}
		}
	} catch (err) {
		logger.warn("[deletion] Stripe cleanup failed (non-blocking)", {
			userId,
			error: String(err),
		});
	}
}

/**
 * Recursively list + remove all files in the `media` bucket under the user's
 * folder prefix. Supabase Storage is not FK-cascaded by Postgres deletion.
 */
export async function purgeUserStorage(userId: string): Promise<void> {
	try {
		const supabase = getSupabase();
		const prefixes = [userId]; // All user files live under `${userId}/...`
		let totalRemoved = 0;

		for (const prefix of prefixes) {
			// Storage list() is non-recursive; walk folders by paginating
			const stack: string[] = [prefix];
			while (stack.length > 0) {
				const path = stack.pop();
				if (path === undefined) break;
				const { data: entries, error } = await supabase.storage
					.from("media")
					.list(path, { limit: 1000 });
				if (error || !entries) continue;

				const files: string[] = [];
				for (const entry of entries) {
					// Supabase marks directories with id === null
					if (entry.id === null) {
						stack.push(`${path}/${entry.name}`);
					} else {
						files.push(`${path}/${entry.name}`);
					}
				}
				if (files.length > 0) {
					const { error: rmError } = await supabase.storage
						.from("media")
						.remove(files);
					if (rmError) {
						logger.warn("[deletion] Storage remove failed for batch", {
							userId,
							path,
							error: rmError.message,
						});
					} else {
						totalRemoved += files.length;
					}
				}
			}
		}

		if (totalRemoved > 0) {
			logger.info("[deletion] Storage purged", { userId, filesRemoved: totalRemoved });
		}
	} catch (err) {
		logger.warn("[deletion] Storage purge failed (non-blocking)", {
			userId,
			error: String(err),
		});
	}
}

/**
 * Delete user-scoped Upstash Redis keys. Uses explicit known prefixes plus
 * a SCAN-based sweep for any key containing the userId (catches unknown
 * prefixes without requiring exhaustive enumeration).
 */
export async function purgeUserRedisKeys(userId: string): Promise<void> {
	try {
		const { getRedis } = await import("../../redis.js");
		const redis = getRedis();

		// Known user-scoped prefixes (update if new ones are added).
		const knownPrefixes = [
			`sync-jobs:user:${userId}`,
			`drift:snooze:${userId}`,
		];
		for (const key of knownPrefixes) {
			try {
				await redis.del(key);
			} catch {
				// best-effort
			}
		}

		// SCAN sweep for any key containing the user id. Caps total work to avoid
		// runaway loops on huge key spaces.
		let cursor: string | number = 0;
		const matched: string[] = [];
		const scanCap = 50; // max iterations
		for (let i = 0; i < scanCap; i++) {
			const [next, keys] = (await redis.scan(cursor, {
				match: `*${userId}*`,
				count: 500,
			})) as [string | number, string[]];
			if (keys.length > 0) matched.push(...keys);
			cursor = next;
			if (cursor === 0 || cursor === "0") break;
		}

		if (matched.length > 0) {
			// Redis DEL accepts multiple keys; chunk to 500 per call.
			for (let i = 0; i < matched.length; i += 500) {
				const chunk = matched.slice(i, i + 500);
				try {
					await redis.del(...chunk);
				} catch (err) {
					logger.warn("[deletion] Redis del chunk failed", {
						userId,
						chunkSize: chunk.length,
						error: String(err),
					});
				}
			}
			logger.info("[deletion] Redis keys purged", {
				userId,
				keysRemoved: matched.length,
			});
		}
	} catch (err) {
		logger.warn("[deletion] Redis purge failed (non-blocking)", {
			userId,
			error: String(err),
		});
	}
}

/**
 * Cascade-delete all user data across 67+ tables, plus vendor cleanup:
 *   Postgres (CRITICAL) → Stripe customer → Supabase Storage → Upstash Redis.
 * Does NOT handle Meta token revocation or auth user deletion.
 * Those are caller responsibilities (user-initiated vs Meta-initiated differ).
 *
 * Vendor cleanup runs BEFORE Postgres cascade for Stripe (needs profile row),
 * AFTER cascade for Storage + Redis (no ordering requirement).
 * All vendor steps are non-blocking; Postgres cascade failures still throw.
 */
export async function cascadeDeleteUserData(userId: string): Promise<void> {
	// Vendor cleanup #1: Stripe — must run BEFORE profiles row is deleted.
	await purgeStripeCustomer(userId);

	const supabase = getSupabase();

	// ── Gather parent IDs for cascading deletes ──
	const { data: threadAccounts } = await supabase
		.from("accounts")
		.select("id")
		.eq("user_id", userId);
	const accountIds = (threadAccounts || []).map((a: { id: string }) => a.id);

	const { data: igAccounts } = await supabase
		.from("instagram_accounts")
		.select("id")
		.eq("user_id", userId);
	const igAccountIds = (igAccounts || []).map((a: { id: string }) => a.id);

	const { data: workspaces } = await supabase
		.from("workspaces")
		.select("id")
		.eq("owner_id", userId);
	const workspaceIds = (workspaces || []).map((w: { id: string }) => w.id);

	const { data: linkPages } = await supabase
		.from("link_pages")
		.select("id")
		.eq("user_id", userId);
	const linkPageIds = (linkPages || []).map((p: { id: string }) => p.id);

	const { data: groups } = await supabase
		.from("account_groups")
		.select("id")
		.eq("user_id", userId);
	const groupIds = (groups || []).map((g: { id: string }) => g.id);

	const { data: competitors } = await supabase
		.from("competitors")
		.select("id")
		.eq("user_id", userId);
	const competitorIds = (competitors || []).map((c: { id: string }) => c.id);

	// ── Pre-Phase 1: Delete children of Phase 1 tables ──

	// auto_post_engagement_snapshots → auto_post_queue (child before parent)
	const { data: queueItems } =
		workspaceIds.length > 0
			? // biome-ignore lint/suspicious/noExplicitAny: table not in generated types
				await (supabase as any)
					.from("auto_post_queue")
					.select("id")
					.in("workspace_id", workspaceIds)
			: { data: [] };
	const queueItemIds = (queueItems || []).map((q: { id: string }) => q.id);
	if (queueItemIds.length > 0) {
		await safeDelete(
			supabase,
			"auto_post_engagement_snapshots",
			"queue_item_id",
			queueItemIds,
		);
	}

	// ig_auto_response_log → ig_auto_responders (child before parent)
	const { data: autoResponders } = await supabase
		.from("ig_auto_responders")
		.select("id")
		.eq("user_id", userId);
	const autoResponderIds = (autoResponders || []).map(
		(r: { id: string }) => r.id,
	);
	if (autoResponderIds.length > 0) {
		await safeDelete(
			supabase,
			"ig_auto_response_log",
			"auto_responder_id",
			autoResponderIds,
		);
	}

	// webhook_deliveries → webhook_subscriptions (child before parent)
	const { data: webhookSubs } = await supabase
		.from("webhook_subscriptions")
		.select("id")
		.eq("user_id", userId);
	const webhookSubIds = (webhookSubs || []).map((w: { id: string }) => w.id);
	if (webhookSubIds.length > 0) {
		await safeDelete(
			supabase,
			"webhook_deliveries",
			"subscription_id",
			webhookSubIds,
		);
	}

	// ── Phase 1: Direct user_id tables ──
	for (const { table, key } of USER_ID_TABLES) {
		await safeDelete(supabase, table, key, userId);
	}

	// ── Phase 2: Account-keyed tables (Threads) ──
	for (const table of ACCOUNT_ID_TABLES) {
		await safeDelete(supabase, table, "account_id", accountIds);
	}

	// ── Phase 3: IG account-keyed tables ──
	for (const table of IG_ACCOUNT_ID_TABLES) {
		await safeDelete(supabase, table, "account_id", igAccountIds);
	}

	// ── Phase 4: Cascading deletes via parent IDs ──

	// listening_results → listening_alerts
	const { data: listeningAlerts } = await supabase
		.from("listening_alerts")
		.select("id")
		.eq("user_id", userId);
	const alertIds = (listeningAlerts || []).map((a: { id: string }) => a.id);
	if (alertIds.length > 0) {
		await safeDelete(supabase, "listening_results", "alert_id", alertIds);
	}
	await safeDelete(supabase, "listening_alerts", "user_id", userId);

	// smart_link_conversions / smart_link_clicks → unified_links
	const { data: unifiedLinks } = await supabase
		.from("unified_links")
		.select("id")
		.eq("user_id", userId);
	const unifiedLinkIds = (unifiedLinks || []).map((l: { id: string }) => l.id);
	if (unifiedLinkIds.length > 0) {
		await safeDelete(
			supabase,
			"smart_link_conversions",
			"link_id",
			unifiedLinkIds,
		);
		await safeDelete(supabase, "smart_link_clicks", "link_id", unifiedLinkIds);
	}
	await safeDelete(supabase, "unified_links", "user_id", userId);

	// Workspace-scoped tables
	if (workspaceIds.length > 0) {
		await safeDelete(
			supabase,
			"inbox_assignments",
			"workspace_id",
			workspaceIds,
		);
		await safeDelete(supabase, "creator_links", "workspace_id", workspaceIds);
		await safeDelete(
			supabase,
			"workspace_invites",
			"workspace_id",
			workspaceIds,
		);
		await safeDelete(supabase, "crisis_events", "workspace_id", workspaceIds);
		await safeDelete(
			supabase,
			"inspiration_config",
			"workspace_id",
			workspaceIds,
		);
		await safeDelete(
			supabase,
			"inspiration_ideas",
			"workspace_id",
			workspaceIds,
		);
		await safeDelete(supabase, "trend_keywords", "workspace_id", workspaceIds);
		await safeDelete(supabase, "trend_snapshots", "workspace_id", workspaceIds);
	}

	// link_benchmarks, link_clicks → link_items → link_pages
	if (linkPageIds.length > 0) {
		await safeDelete(supabase, "link_benchmarks", "page_id", linkPageIds);
		const { data: linkItems } = await supabase
			.from("link_items")
			.select("id")
			.in("page_id", linkPageIds);
		const linkItemIds = (linkItems || []).map((i: { id: string }) => i.id);
		await safeDelete(supabase, "link_clicks", "link_id", linkItemIds);
		await safeDelete(supabase, "link_items", "page_id", linkPageIds);
	}

	// competitor_posts → competitors
	await safeDelete(
		supabase,
		"competitor_posts",
		"competitor_id",
		competitorIds,
	);

	// group_analytics, auto_post_group_config/state/overrides → account_groups
	await safeDelete(supabase, "group_analytics", "group_id", groupIds);
	await safeDelete(
		supabase,
		"auto_post_account_overrides",
		"group_id",
		groupIds,
	);
	await safeDelete(supabase, "auto_post_group_config", "group_id", groupIds);
	await safeDelete(supabase, "auto_post_group_state", "group_id", groupIds);

	// publish_attempts, auto_post_queue, auto_post_config, auto_reply_rules → workspaces
	await safeDelete(supabase, "publish_attempts", "workspace_id", workspaceIds);
	await safeDelete(supabase, "auto_post_queue", "workspace_id", workspaceIds);
	await safeDelete(supabase, "auto_post_config", "workspace_id", workspaceIds);
	await safeDelete(supabase, "auto_reply_rules", "workspace_id", workspaceIds);
	await safeDelete(
		supabase,
		"workspace_activity",
		"workspace_id",
		workspaceIds,
	);
	await safeDelete(supabase, "workspaces", "owner_id", userId);

	// ig_carousel_insights, post_reflections → posts
	const { data: userPosts } = await supabase
		.from("posts")
		.select("id")
		.eq("user_id", userId);
	const postIds = (userPosts || []).map((p: { id: string }) => p.id);
	if (postIds.length > 0) {
		await safeDelete(supabase, "ig_carousel_insights", "post_id", postIds);
		await safeDelete(supabase, "post_reflections", "post_id", postIds);
	}

	// influencer_collab_posts → influencer_collabs
	const { data: collabs } = await supabase
		.from("influencer_collabs")
		.select("id")
		.eq("user_id", userId);
	const collabIds = (collabs || []).map((c: { id: string }) => c.id);
	if (collabIds.length > 0) {
		await safeDelete(
			supabase,
			"influencer_collab_posts",
			"collab_id",
			collabIds,
		);
	}
	await safeDelete(supabase, "influencer_collabs", "user_id", userId);

	// Referrals (both directions)
	await safeDelete(supabase, "referrals", "referrer_id", userId);
	await safeDelete(supabase, "referrals", "referred_id", userId);

	// ── Phase 5: Parent tables ──
	for (const { table, key } of PARENT_TABLES) {
		await safeDelete(supabase, table, key, userId);
	}

	// ── Vendor cleanup #2/#3: Storage + Redis (non-blocking, post-Postgres) ──
	await purgeUserStorage(userId);
	await purgeUserRedisKeys(userId);

	logger.info("[deletion] Cascade complete", { userId });
}

// ============================================================================
// Auth user deletion
// ============================================================================

/**
 * Delete the Supabase auth user. Call AFTER cascadeDeleteUserData.
 * Throws on failure so caller can handle.
 */
export async function deleteAuthUser(userId: string): Promise<void> {
	const supabaseAdmin = createClient(
		process.env.SUPABASE_URL || "",
		process.env.SUPABASE_SERVICE_ROLE_KEY ||
			process.env.SUPABASE_SERVICE_KEY ||
			"",
		{ auth: { autoRefreshToken: false, persistSession: false } },
	);
	const { error: authError } =
		await supabaseAdmin.auth.admin.deleteUser(userId);
	if (authError) {
		logger.error("[deletion] Failed to delete auth user", {
			userId,
			error: authError.message,
		});
		throw new Error(`Auth user deletion failed: ${authError.message}`);
	}
	logger.info("[deletion] Auth user deleted", { userId });
}
