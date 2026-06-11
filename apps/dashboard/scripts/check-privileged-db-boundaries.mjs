#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();

const guardedFiles = [
	{
		file: "api/reliability.ts",
		reason: "reliabilityTelemetry",
	},
	{
		file: "api/reports.ts",
		reason: "reportGeneration",
	},
	{
		file: "api/_lib/handlers/reports/send.ts",
		reason: "reportDelivery",
	},
	{
		file: "api/cron/publish-worker.ts",
		reason: "publishExecution",
	},
	{
		file: "api/_lib/publishJobs.ts",
		reason: "publishQueue",
	},
	{
		file: "api/_lib/publishPost.ts",
		reason: "publishExecution",
	},
	{
		file: "api/_lib/tokenAccess.ts",
		reason: "tokenDecryption",
	},
	{
		file: "api/_lib/accountSync.ts",
		reason: "accountSync",
	},
	{
		file: "api/_lib/analyticsSync.ts",
		reason: "analyticsSync",
	},
	{
		file: "api/_lib/cron/token-refresh.ts",
		reason: "tokenRefresh",
	},
	{
		file: "api/_lib/accountHealthSignals.ts",
		reason: "accountHealthSignals",
	},
	{
		file: "api/cron/analytics-pipeline.ts",
		reason: "analyticsPipeline",
	},
	{
		file: "api/_lib/analytics/postProcess.ts",
		reason: "analyticsPostprocess",
	},
	{
		file: "api/analytics.ts",
		reason: "analyticsReadAggregation",
	},
	{
		file: "api/_lib/analytics/cohortAggregation.ts",
		reason: "cohortAggregation",
	},
	{
		file: "api/_lib/metaApiHealth.ts",
		reason: "metaHealthCheck",
	},
	{
		file: "api/_lib/syncProgress.ts",
		reason: "syncProgress",
	},
	{
		file: "api/_lib/threadsApi.ts",
		reason: "metaUsageTelemetry",
	},
	{
		file: "api/cron/scheduler.ts",
		reason: "schedulerWorker",
	},
	{
		file: "api/cron/daily-orchestrator.ts",
		reason: "cronOrchestration",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/cron/daily-orchestrator-late.ts",
		reason: "cronOrchestration",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/cron/six-hour-pipeline.ts",
		reason: "cronOrchestration",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/cron/sync-orchestrator.ts",
		reason: "cronOrchestration",
		helper: ["getPrivilegedSupabase", "getPrivilegedSupabaseAny"],
	},
	{
		file: "api/cron/webhook-processor.ts",
		reason: "cronWebhookProcessing",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/queue-fill.ts",
		reason: "queueFill",
	},
	{
		file: "api/qstash-failure.ts",
		reason: "qstashFailure",
	},
	{
		file: "api/auto-reply.ts",
		reason: "autoReplyWorker",
	},
	{
		file: "api/cron/account-state-evaluator.ts",
		reason: "accountStateEvaluator",
	},
	{
		file: "api/cron/autoposter-doctor.ts",
		reason: "autoposterDoctor",
	},
	{
		file: "api/cron/autoposter-watchdog.ts",
		reason: "autoposterWatchdog",
	},
	{
		file: "api/_lib/handlers/subscription/index.ts",
		reason: "subscriptionManagement",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/referrals.ts",
		reason: "referralManagement",
	},
	{
		file: "api/auth/apply-referral.ts",
		reason: "referralManagement",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/auth/mfa-backup.ts",
		reason: "mfaBackupRecovery",
		helper: ["getPrivilegedSupabase", "getPrivilegedSupabaseAny"],
	},
	{
		file: "api/_lib/handlers/media-sub/refresh.ts",
		reason: "mediaRefresh",
		helper: ["getPrivilegedSupabase", "getPrivilegedSupabaseAny"],
	},
	{
		file: "api/media/[id].ts",
		reason: "mediaProxy",
		helper: ["getPrivilegedSupabase", "getPrivilegedSupabaseAny"],
	},
	{
		file: "api/_lib/handlers/jobs/export-worker.ts",
		reason: "dataExportWorker",
	},
	{
		file: "api/meta/data-deletion.ts",
		reason: "metaDataDeletionCallback",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/check-deletion-status.ts",
		reason: "metaDeletionStatus",
	},
	{
		file: "api/meta/process-deletion.ts",
		reason: "metaDeletionProcessor",
	},
	{
		file: "api/meta/deauthorize.ts",
		reason: "metaDeauthorizeCallback",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/instagram/webhook.ts",
		reason: "metaWebhookIngestion",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/threads/webhook.ts",
		reason: "metaWebhookIngestion",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/instagram/webhook-subscribe.ts",
		reason: "metaWebhookSubscription",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/threads/webhook-subscribe.ts",
		reason: "metaWebhookSubscription",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/auth/instagram/callback.ts",
		reason: "oauthCallback",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/auth/instagram/fb-callback.ts",
		reason: "oauthCallback",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/auth/threads/callback.ts",
		reason: "oauthCallback",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/webhook.ts",
		reason: "stripeWebhook",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/mcp.ts",
		reason: "hostedMcpAuth",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/operator.ts",
		reason: "operatorControlPlane",
	},
	{
		file: "api/_lib/operatorAudit.ts",
		reason: "operatorAudit",
	},
	{
		file: "api/_lib/withApiKey.ts",
		reason: "publicApiKeyAuth",
		helper: ["getPrivilegedSupabase", "getPrivilegedSupabaseAny"],
	},
	{
		file: "api/link-page/[slug].ts",
		reason: "publicLinkPage",
		helper: ["getPrivilegedSupabase", "getPrivilegedSupabaseAny"],
	},
	{
		file: "api/link-page/domain.ts",
		reason: "publicLinkDomain",
	},
	{
		file: "api/go/[code].ts",
		reason: "publicLinkRedirect",
		helper: ["getPrivilegedSupabase", "getPrivilegedSupabaseAny"],
	},
	{
		file: "api/go/r/[redirectId].ts",
		reason: "publicLinkRedirect",
	},
	{
		file: "api/go/convert.ts",
		reason: "publicLinkConversion",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/shared-report.ts",
		reason: "publicSharedReport",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/sitemap.ts",
		reason: "publicSitemap",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/auth/disconnect.ts",
		reason: "accountDisconnectAuth",
		helper: "getPrivilegedSupabase",
	},
	{
		file: "api/trends.ts",
		reason: "trendSearchTokenLookup",
		helper: "getPrivilegedSupabase",
	},
];

const violations = [];

for (const { file, reason, helper = "getPrivilegedSupabaseAny" } of guardedFiles) {
	const source = readFileSync(join(root, file), "utf8");
	const requiredHelpers = Array.isArray(helper) ? helper : [helper];
	if (/getSupabaseAny\s*\(/.test(source)) {
		violations.push(`${file} must use getPrivilegedSupabaseAny() instead of direct getSupabaseAny()`);
	}
	if (/getSupabase\s*\(/.test(source)) {
		violations.push(`${file} must use getPrivilegedSupabase() instead of direct getSupabase()`);
	}
	if (/from\s+["'][^"']*supabase\.js["']/.test(source)) {
		violations.push(`${file} must not import the Supabase service-role helper directly`);
	}
	for (const requiredHelper of requiredHelpers) {
		if (!source.includes(requiredHelper)) {
			violations.push(`${file} must use the privileged DB helper ${requiredHelper}`);
		}
	}
	if (!source.includes(`PRIVILEGED_DB_REASONS.${reason}`)) {
		violations.push(`${file} must declare privileged DB reason PRIVILEGED_DB_REASONS.${reason}`);
	}
}

if (violations.length > 0) {
	console.error("ERROR: privileged DB boundary violation.");
	for (const violation of violations) console.error(`- ${violation}`);
	process.exit(1);
}
