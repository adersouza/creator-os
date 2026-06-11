/**
 * Ergonomic type aliases for Supabase database tables.
 *
 * Instead of: Database['public']['Tables']['posts']['Row']
 * Use:        PostRow
 *
 * Generated from types/supabase.ts — update when schema changes.
 */

import type { Database } from "./supabase.js";

// ─── Helper types ───────────────────────────────────────────────────────────

type Tables = Database["public"]["Tables"];
type Row<T extends keyof Tables> = Tables[T]["Row"];
type Insert<T extends keyof Tables> = Tables[T]["Insert"];
type Update<T extends keyof Tables> = Tables[T]["Update"];

// Re-export Database for convenience
export type { Database };

// ─── Core ───────────────────────────────────────────────────────────────────

export type ProfileRow = Row<"profiles">;
export type ProfileInsert = Insert<"profiles">;
export type ProfileUpdate = Update<"profiles">;

export type AccountRow = Row<"accounts">;
export type AccountInsert = Insert<"accounts">;
export type AccountUpdate = Update<"accounts">;

export type InstagramAccountRow = Row<"instagram_accounts">;
export type InstagramAccountInsert = Insert<"instagram_accounts">;
export type InstagramAccountUpdate = Update<"instagram_accounts">;

export type PostRow = Row<"posts">;
export type PostInsert = Insert<"posts">;
export type PostUpdate = Update<"posts">;

export type AccountGroupRow = Row<"account_groups">;
export type AccountGroupInsert = Insert<"account_groups">;
export type AccountGroupUpdate = Update<"account_groups">;

export type AccountDailySummaryRow = Row<"account_daily_summary">;
export type AccountHealthSnapshotRow = Row<"account_health_snapshots">;
export type AccountMetricsHistoryRow = Row<"account_metrics_history">;

// ─── Workspaces & Teams ─────────────────────────────────────────────────────

export type WorkspaceRow = Row<"workspaces">;
export type WorkspaceInsert = Insert<"workspaces">;
export type WorkspaceUpdate = Update<"workspaces">;

export type WorkspaceMemberRow = Row<"workspace_members">;
export type WorkspaceMemberInsert = Insert<"workspace_members">;
export type WorkspaceMemberUpdate = Update<"workspace_members">;

export type WorkspaceInviteRow = Row<"workspace_invites">;
export type WorkspaceActivityRow = Row<"workspace_activity">;

export type AgencyBrandingRow = Row<"agency_branding">;
export type AgencyBrandingInsert = Insert<"agency_branding">;
export type AgencyBrandingUpdate = Update<"agency_branding">;

// ─── Auto-Poster ────────────────────────────────────────────────────────────

export type AutoPostConfigRow = Row<"auto_post_config">;
export type AutoPostConfigInsert = Insert<"auto_post_config">;
export type AutoPostConfigUpdate = Update<"auto_post_config">;

export type AutoPostQueueRow = Row<"auto_post_queue">;
export type AutoPostQueueInsert = Insert<"auto_post_queue">;
export type AutoPostQueueUpdate = Update<"auto_post_queue">;

export type AutoPostActivityRow = Row<"auto_post_activity">;
export type AutoPostStateRow = Row<"auto_post_state">;
export type AutoPostStateInsert = Insert<"auto_post_state">;
export type AutoPostStateUpdate = Update<"auto_post_state">;
export type AutoPostGroupConfigRow = Row<"auto_post_group_config">;
export type AutoPostGroupConfigInsert = Insert<"auto_post_group_config">;
export type AutoPostGroupConfigUpdate = Update<"auto_post_group_config">;
export type AutoPostGroupStateRow = Row<"auto_post_group_state">;
export type AutoPostAccountOverrideRow = Row<"auto_post_account_overrides">;
export type AutoPostEngagementSnapshotRow =
	Row<"auto_post_engagement_snapshots">;

export type AutoCrossReplyRow = Row<"auto_cross_replies">;
export type AutoSelfReplyRow = Row<"auto_self_replies">;
export type AutoReplyLogRow = Row<"auto_reply_logs">;
export type AutoReplyQueueRow = Row<"auto_reply_queue">;
export type AutoReplyRuleRow = Row<"auto_reply_rules">;

// ─── Competitors ────────────────────────────────────────────────────────────

export type CompetitorRow = Row<"competitors">;
export type CompetitorInsert = Insert<"competitors">;
export type CompetitorUpdate = Update<"competitors">;

export type CompetitorSnapshotRow = Row<"competitor_snapshots">;
export type CompetitorAlertRow = Row<"competitor_alerts">;
export type CompetitorTopPostRow = Row<"competitor_top_posts">;
export type CompetitorMetricsHistoryRow = Row<"competitor_metrics_history">;
export type SavedCompetitorPostRow = Row<"saved_competitor_posts">;

// ─── Replies & Mentions ─────────────────────────────────────────────────────

export type PostReplyRow = Row<"post_replies">;
export type PostReplyInsert = Insert<"post_replies">;
export type PostReplyUpdate = Update<"post_replies">;

export type SentReplyRow = Row<"sent_replies">;
export type SentReplyInsert = Insert<"sent_replies">;

export type MentionRow = Row<"mentions">;
export type NotificationRow = Row<"notifications">;
export type NotificationInsert = Insert<"notifications">;

// ─── Instagram-Specific ─────────────────────────────────────────────────────

export type IgCommentRow = Row<"ig_comments">;
export type IgMentionRow = Row<"ig_mentions">;
export type IgDmTemplateRow = Row<"ig_dm_templates">;
export type IgAutoResponderRow = Row<"ig_auto_responders">;
export type IgPendingContainerRow = Row<"ig_pending_containers">;
export type IgWebhookEventRow = Row<"ig_webhook_events">;
export type IgStoryInsightRow = Row<"ig_story_insights">;
export type IgHashtagTrackingRow = Row<"ig_hashtag_tracking">;
export type IgRateLimitRow = Row<"ig_rate_limit_tracking">;
export type IgEndpointRateLimitRow = Row<"ig_endpoint_rate_limits">;
export type IgCarouselInsightRow = Row<"ig_carousel_insights">;
export type IgCollabInviteRow = Row<"ig_collab_invites">;
export type IgDmAiRateLimitRow = Row<"ig_dm_ai_rate_limits">;
export type IgDmAiResponseRow = Row<"ig_dm_ai_responses">;

// ─── Threads Webhooks ───────────────────────────────────────────────────────

export type ThreadsWebhookEventRow = Row<"threads_webhook_events">;
export type RateLimitRow = Row<"rate_limit_tracking">;

// ─── Inbox ─────────────────────────────────────────────────────────────────

export type InboxAssignmentRow = Row<"inbox_assignments">;
export type InboxDmCacheRow = Row<"inbox_dm_cache">;

// ─── Analytics & Metrics ────────────────────────────────────────────────────

export type AccountAnalyticsRow = Row<"account_analytics">;
export type GroupAnalyticsRow = Row<"group_analytics">;
export type PostMetricHistoryRow = Row<"post_metric_history">;
export type PostSuccessSignalRow = Row<"post_success_signals">;
export type AudienceDemographicsRow = Row<"audience_demographics">;
export type ViralScoreCalibrationRow = Row<"viral_score_calibration">;

export type DemographicsSnapshotRow = Row<"audience_demographics">;

// ─── Cron & System ──────────────────────────────────────────────────────────

export type CronRunRow = Row<"cron_runs">;
export type CronLockRow = Row<"cron_locks">;
export type SyncJobRow = Row<"sync_jobs">;

export type DataExportJobRow = Row<"data_export_jobs">;
export type DataExportJobInsert = Insert<"data_export_jobs">;
export type DataExportJobUpdate = Update<"data_export_jobs">;

// ─── AI & Content ───────────────────────────────────────────────────────────

export type AiFeedbackRow = Row<"ai_feedback">;
export type AiFeedbackInsert = Insert<"ai_feedback">;

export type InspirationIdeaRow = Row<"inspiration_ideas">;
export type InspirationConfigRow = Row<"inspiration_config">;
export type CopilotMemoryRow = Row<"copilot_memory">;
export type PostReflectionRow = Row<"post_reflections">;
export type PostTemplateRow = Row<"post_templates">;
export type PostTemplateInsert = Insert<"post_templates">;
export type PostTemplateUpdate = Update<"post_templates">;

// ─── Link Pages ─────────────────────────────────────────────────────────────

export type LinkPageRow = Row<"link_pages">;
export type LinkPageInsert = Insert<"link_pages">;
export type LinkPageUpdate = Update<"link_pages">;

export type LinkItemRow = Row<"link_items">;
export type LinkItemInsert = Insert<"link_items">;
export type LinkItemUpdate = Update<"link_items">;

export type LinkClickRow = Row<"link_clicks">;

// ─── Smart Links ───────────────────────────────────────────────────────────

export type SmartLinkRow = Row<"smart_links">;
export type SmartLinkInsert = Insert<"smart_links">;
export type SmartLinkUpdate = Update<"smart_links">;

export type SmartLinkClickRow = Row<"smart_link_clicks">;
export type SmartLinkClickInsert = Insert<"smart_link_clicks">;

export type SmartLinkConversionRow = Row<"smart_link_conversions">;
export type SmartLinkConversionInsert = Insert<"smart_link_conversions">;

// ─── Influencer Collabs ───────────────────────────────────────────────────

export type InfluencerCollabRow = Row<"influencer_collabs">;
export type InfluencerCollabInsert = Insert<"influencer_collabs">;
export type InfluencerCollabPostRow = Row<"influencer_collab_posts">;

// ─── Settings & Preferences ────────────────────────────────────────────────

export type UserSettingRow = Row<"user_settings">;
export type UserPreferenceRow = Row<"user_preferences">;
export type CrossPostSettingRow = Row<"cross_post_settings">;

// ─── Trends & Discovery ────────────────────────────────────────────────────

export type TrendPostRow = Row<"trend_posts">;
export type TrendKeywordRow = Row<"trend_keywords">;
export type TrendSnapshotRow = Row<"trend_snapshots">;
export type TrendDiscoveryRow = Row<"trend_discoveries">;
export type TrendingTopicConfigRow = Row<"trending_topic_config">;
export type TrendForecastRow = Row<"trend_forecasts">;

// ─── Agent ─────────────────────────────────────────────────────────────────

export type AgentActionRow = Row<"agent_actions">;
export type AgentApprovalRow = Row<"agent_approvals">;
export type AgentNoteRow = Row<"agent_notes">;
export type AgentNoteInsert = Insert<"agent_notes">;

// ─── Media ──────────────────────────────────────────────────────────────────

export type MediaRow = Row<"media">;
export type MediaInsert = Insert<"media">;
export type MediaFolderRow = Row<"media_folders">;

// ─── Misc ───────────────────────────────────────────────────────────────────

export type FavoriteRow = Row<"favorites">;
export type FavoriteInsert = Insert<"favorites">;

export type CreatorEventRow = Row<"creator_events">;
export type AnomalyAlertRow = Row<"anomaly_alerts">;
export type ListeningAlertRow = Row<"listening_alerts">;
export type StyleBibleRow = Row<"style_bibles">;
export type FeatureUsageRow = Row<"feature_usage">;

// ─── Security & API ───────────────────────────────────────────────────────

export type ApiKeyRow = Row<"api_keys">;
export type ApiUsageRow = Row<"api_usage">;
export type AuditLogRow = Row<"audit_logs">;
export type AiConfigRow = Row<"ai_config">;

// ─── Billing & Referrals ──────────────────────────────────────────────────

export type StripeProcessedEventRow = Row<"stripe_processed_events">;
export type ReferralCodeRow = Row<"referral_codes">;
export type ReferralRow = Row<"referrals">;
export type RevenueSnapshotRow = Row<"revenue_snapshots">;

// ─── Notifications & Webhooks ─────────────────────────────────────────────

export type PushSubscriptionRow = Row<"push_subscriptions">;
export type WebhookDeliveryRow = Row<"webhook_deliveries">;
export type WebhookSubscriptionRow = Row<"webhook_subscriptions">;
export type WatchdogAlertRow = Row<"watchdog_alerts">;

// ─── Crisis & Anomaly ─────────────────────────────────────────────────────

export type CrisisEventRow = Row<"crisis_events">;
export type QuickWinRow = Row<"quick_wins">;
export type RecommendationBaselineRow = Row<"recommendation_baselines">;
export type RecommendationDismissalRow = Row<"recommendation_dismissals">;

// ─── Links & Domains ──────────────────────────────────────────────────────

export type CreatorLinkRow = Row<"creator_links">;
export type UnifiedLinkRow = Row<"unified_links">;
export type DomainVerificationRow = Row<"domain_verifications">;
export type LinkBenchmarkRow = Row<"link_benchmarks">;

// ─── Content ──────────────────────────────────────────────────────────────

export type DraftFolderRow = Row<"draft_folders">;
export type ListeningResultRow = Row<"listening_results">;
