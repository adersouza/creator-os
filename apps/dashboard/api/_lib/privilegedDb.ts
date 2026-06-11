import type { SupabaseClient } from "@supabase/supabase-js";
import { getSupabase, getSupabaseAny, type TypedSupabaseClient } from "./supabase.js";

export const PRIVILEGED_DB_REASONS = {
	reliabilityTelemetry: "reliability_telemetry",
	reportGeneration: "report_generation",
	reportDelivery: "report_delivery",
	publishQueue: "publish_queue",
	publishExecution: "publish_execution",
	tokenDecryption: "token_decryption",
	tokenRefresh: "token_refresh",
	accountSync: "account_sync",
	analyticsSync: "analytics_sync",
	analyticsPipeline: "analytics_pipeline",
	analyticsPostprocess: "analytics_postprocess",
	analyticsReadAggregation: "analytics_read_aggregation",
	cohortAggregation: "cohort_aggregation",
	accountHealthSignals: "account_health_signals",
	metaHealthCheck: "meta_health_check",
	metaUsageTelemetry: "meta_usage_telemetry",
	syncProgress: "sync_progress",
	schedulerWorker: "scheduler_worker",
	cronOrchestration: "cron_orchestration",
	cronWebhookProcessing: "cron_webhook_processing",
	queueFill: "queue_fill",
	qstashFailure: "qstash_failure",
	autoReplyWorker: "auto_reply_worker",
	accountStateEvaluator: "account_state_evaluator",
	autoposterDoctor: "autoposter_doctor",
	autoposterWatchdog: "autoposter_watchdog",
	subscriptionManagement: "subscription_management",
	referralManagement: "referral_management",
	mfaBackupRecovery: "mfa_backup_recovery",
	mediaLibrary: "media_library",
	mediaRefresh: "media_refresh",
	mediaProxy: "media_proxy",
	dataExportWorker: "data_export_worker",
	metaDataDeletionCallback: "meta_data_deletion_callback",
	metaDeletionStatus: "meta_deletion_status",
	metaDeletionProcessor: "meta_deletion_processor",
	metaDeauthorizeCallback: "meta_deauthorize_callback",
	metaWebhookIngestion: "meta_webhook_ingestion",
	metaWebhookSubscription: "meta_webhook_subscription",
	oauthCallback: "oauth_callback",
	stripeWebhook: "stripe_webhook",
	hostedMcpAuth: "hosted_mcp_auth",
	operatorControlPlane: "operator_control_plane",
	operatorAudit: "operator_audit",
	publicApiKeyAuth: "public_api_key_auth",
	publicLinkPage: "public_link_page",
	publicLinkDomain: "public_link_domain",
	publicLinkRedirect: "public_link_redirect",
	publicLinkConversion: "public_link_conversion",
	publicSharedReport: "public_shared_report",
	publicSitemap: "public_sitemap",
	accountDisconnectAuth: "account_disconnect_auth",
	trendSearchTokenLookup: "trend_search_token_lookup",
} as const;

export type PrivilegedDbReason =
	(typeof PRIVILEGED_DB_REASONS)[keyof typeof PRIVILEGED_DB_REASONS];
// biome-ignore lint/suspicious/noExplicitAny: explicit service-role escape hatch for deep Supabase typing
type LoosePrivilegedSupabaseClient = SupabaseClient<any>;

function markPrivilegedDbUse(_reason: PrivilegedDbReason): void {
	// The reason is intentionally required at every call site so static checks
	// and reviews can distinguish privileged server-owned work from user CRUD.
}

export function getPrivilegedSupabase(
	reason: PrivilegedDbReason,
): TypedSupabaseClient {
	markPrivilegedDbUse(reason);
	return getSupabase();
}

export function getPrivilegedSupabaseAny(
	reason: PrivilegedDbReason,
): LoosePrivilegedSupabaseClient {
	markPrivilegedDbUse(reason);
	return getSupabaseAny();
}
