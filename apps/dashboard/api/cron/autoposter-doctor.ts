import type { SupabaseClient } from "@supabase/supabase-js";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	AlertLevel,
	alert,
	alertCronFailure,
	alertWorkspace,
} from "../_lib/alerting.js";
import { verifyCronAuth } from "../_lib/apiResponse.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { isPublishAttemptHealthRelevantFailure } from "../_lib/handlers/auto-post/accountHealth.js";
import { isAutoposterHardDisabled } from "../_lib/handlers/auto-post/killSwitch.js";
import { evaluateQueueProvenance } from "../_lib/handlers/auto-post/provenanceGate.js";
import { logger } from "../_lib/logger.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";

const JOB_NAME = "autoposter-doctor";
const MAX_SAMPLE_IDS = 10;

interface DoctorFinding {
	workspace_id: string;
	check_name: string;
	severity: "warn" | "error" | "critical";
	message: string;
	details: Record<string, unknown>;
}

interface QueueInvariantRow {
	id: string;
	workspace_id: string;
	group_id: string | null;
	account_id: string | null;
	threads_post_id?: string | null | undefined;
	claim_token?: string | null | undefined;
	claim_expires_at?: string | null | undefined;
	external_published_at?: string | null | undefined;
	finalize_error?: string | null | undefined;
	posted_at?: string | null | undefined;
}

interface PostInvariantRow {
	id: string;
	account_id: string | null;
	threads_post_id: string | null;
	cross_post_group_id?: string | null | undefined;
	metadata?: Record<string, unknown> | null | undefined;
	published_at?: string | null | undefined;
}

const db = () =>
	getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.autoposterDoctor);

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (!verifyCronAuth(req, res)) return;

	try {
		if (isAutoposterHardDisabled()) {
			return res
				.status(200)
				.json({ ok: true, skipped: true, reason: "hard_disabled" });
		}

		const supabase = db();
		const lockResult = await withCronLock(
			supabase as SupabaseClient,
			JOB_NAME,
			async () =>
				trackCronRun(supabase as SupabaseClient, JOB_NAME, async () => {
					const findings = await runAutoposterDoctor();
					const persisted = await persistDoctorFindings(findings);

					if (persisted > 0) {
						await alert(AlertLevel.WARN, "Autoposter doctor found invariants", {
							findings: persisted,
							job: JOB_NAME,
						});
					}

					return {
						itemsProcessed: findings.length,
						metadata: {
							findings: findings.length,
							persisted,
							checks: [
								"expired-publishing-lease",
								"stale-reconciliation",
								"published-without-post",
								"post-without-queue",
							"duplicate-published-fingerprint",
							"pending-missing-provenance",
							"published-missing-provenance",
							"failure-heavy-account-marked-healthy",
							"account-suppressed-too-long",
							"group-without-healthy-accounts",
						],
						},
					};
				}),
			120,
		);

		if ("skipped" in lockResult && lockResult.skipped) {
			return res.status(200).json({ ok: true, skipped: true });
		}

		return res.status(200).json({ ok: true, ...lockResult });
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		logger.error("[autoposter-doctor] Fatal error", { error: message });
		await alertCronFailure(JOB_NAME, message);
		return res.status(500).json({ ok: false, error: "Doctor failed" });
	}
}

export async function runAutoposterDoctor(): Promise<DoctorFinding[]> {
	const { data: configs, error } = await db()
		.from("auto_post_config")
		.select("workspace_id")
		.eq("is_enabled", true);

	if (error) throw error;
	const workspaceIds = [
		...new Set(
			((configs ?? []) as Array<{ workspace_id: string | null }>)
				.map((row) => row.workspace_id)
				.filter((id): id is string => Boolean(id)),
		),
	];
	if (workspaceIds.length === 0) return [];

	const findings: DoctorFinding[] = [];
	await Promise.all([
		checkExpiredPublishingLeases(workspaceIds, findings),
		checkStaleReconciliation(workspaceIds, findings),
		checkPublishedQueueWithoutPost(workspaceIds, findings),
		checkAutoposterPostsWithoutQueue(workspaceIds, findings),
		checkDuplicatePublishedFingerprints(workspaceIds, findings),
		checkPendingRowsMissingProvenance(workspaceIds, findings),
		checkPublishedRowsMissingProvenance(workspaceIds, findings),
		checkFailureHeavyAccountsMarkedHealthy(workspaceIds, findings),
		checkAccountsSuppressedTooLong(workspaceIds, findings),
		checkGroupsWithoutHealthyAccounts(workspaceIds, findings),
	]);
	return findings;
}

async function checkFailureHeavyAccountsMarkedHealthy(
	workspaceIds: string[],
	findings: DoctorFinding[],
): Promise<void> {
	const cutoff = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
	const { data: states, error } = await db()
		.from("account_autoposter_state")
		.select("account_id, workspace_id, group_id, status, account_health_score")
		.in("workspace_id", workspaceIds)
		.gte("account_health_score", 80)
		.in("status", ["active", "warming_limited", "warming_silent"])
		.limit(500);
	if (error) {
		logger.warn("[autoposter-doctor] account health state check failed", {
			error: String(error),
		});
		return;
	}
	const rows = (states ?? []) as Array<{
		account_id: string;
		workspace_id: string;
		group_id: string | null;
		status: string | null;
		account_health_score: number | null;
	}>;
	if (rows.length === 0) return;
	const accountIds = rows.map((row) => row.account_id);
	const { data: attempts, error: attemptsError } = await db()
		.from("publish_attempts")
		.select("account_id, result, error_code, error_message")
		.in("account_id", accountIds)
		.gte("started_at", cutoff)
		.in("result", [
			"dead_letter",
			"failed",
			"error",
			"requeued",
			"duplicate_fingerprint_blocked",
		])
		.limit(1000);
	if (attemptsError) {
		logger.warn("[autoposter-doctor] account health attempts check failed", {
			error: String(attemptsError),
		});
		return;
	}
	const failuresByAccount = new Map<string, number>();
	for (const attempt of (attempts ?? []) as Array<{
		account_id: string | null;
		result: string | null;
		error_code: string | null;
		error_message?: string | null;
	}>) {
		if (!attempt.account_id) continue;
		if (
			!isPublishAttemptHealthRelevantFailure({
				result: attempt.result,
				errorCode: attempt.error_code,
				errorMessage: attempt.error_message,
			})
		) {
			continue;
		}
		failuresByAccount.set(
			attempt.account_id,
			(failuresByAccount.get(attempt.account_id) ?? 0) + 1,
		);
	}
	const mismatched = rows.filter(
		(row) => (failuresByAccount.get(row.account_id) ?? 0) >= 3,
	);
	for (const [workspaceId, groupedRows] of groupByWorkspace(mismatched)) {
		findings.push({
			workspace_id: workspaceId,
			check_name: "autoposter-doctor:failure-heavy-account-marked-healthy",
			severity: "error",
			message: `${groupedRows.length} account(s) have repeated publish failures but remain high-health`,
			details: {
				count: groupedRows.length,
				sampleAccountIds: sampleAccountIds(groupedRows),
				sampleFailures: groupedRows.slice(0, 5).map((row) => ({
					accountId: row.account_id,
					failures: failuresByAccount.get(row.account_id) ?? 0,
					score: row.account_health_score,
				})),
			},
		});
	}
}

async function checkAccountsSuppressedTooLong(
	workspaceIds: string[],
	findings: DoctorFinding[],
): Promise<void> {
	const cutoff = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
	const { data, error } = await db()
		.from("account_autoposter_state")
		.select("account_id, workspace_id, group_id, status, updated_at")
		.in("workspace_id", workspaceIds)
		.in("status", ["suppressed", "shadowban_throttle"])
		.lt("updated_at", cutoff)
		.limit(250);
	if (error) {
		logger.warn("[autoposter-doctor] suppressed-too-long check failed", {
			error: String(error),
		});
		return;
	}
	const rows = (data ?? []) as Array<{
		account_id: string;
		workspace_id: string;
		group_id: string | null;
		status: string | null;
		updated_at: string | null;
	}>;
	for (const [workspaceId, groupedRows] of groupByWorkspace(rows)) {
		findings.push({
			workspace_id: workspaceId,
			check_name: "autoposter-doctor:account-suppressed-too-long",
			severity: "warn",
			message: `${groupedRows.length} account(s) have remained suppressed for over 7 days`,
			details: {
				count: groupedRows.length,
				sampleAccountIds: sampleAccountIds(groupedRows),
				oldestUpdatedAt: oldestIso(groupedRows, "updated_at"),
			},
		});
	}
}

async function checkGroupsWithoutHealthyAccounts(
	workspaceIds: string[],
	findings: DoctorFinding[],
): Promise<void> {
	const { data: groups, error } = await db()
		.from("auto_post_group_config")
		.select("workspace_id, group_id")
		.in("workspace_id", workspaceIds)
		.eq("enabled", true)
		.limit(500);
	if (error) {
		logger.warn("[autoposter-doctor] group health lookup failed", {
			error: String(error),
		});
		return;
	}
	const groupRows = (groups ?? []) as Array<{
		workspace_id: string;
		group_id: string;
	}>;
	if (groupRows.length === 0) return;
	const groupIds = groupRows.map((row) => row.group_id);
	const { data: states, error: statesError } = await db()
		.from("account_autoposter_state")
		.select("account_id, workspace_id, group_id, status, account_health_score")
		.in("workspace_id", workspaceIds)
		.in("group_id", groupIds)
		.limit(1000);
	if (statesError) {
		logger.warn("[autoposter-doctor] group health state lookup failed", {
			error: String(statesError),
		});
		return;
	}
	const healthyGroups = new Set(
		((states ?? []) as Array<{
			group_id: string | null;
			status: string | null;
			account_health_score: number | null;
		}>)
			.filter(
				(row) =>
					row.group_id &&
					row.status !== "inactive" &&
					row.status !== "suppressed" &&
					(row.account_health_score ?? 100) >= 60,
			)
			.map((row) => row.group_id as string),
	);
	const missing = groupRows.filter((row) => !healthyGroups.has(row.group_id));
	for (const [workspaceId, groupedRows] of groupByWorkspace(missing)) {
		findings.push({
			workspace_id: workspaceId,
			check_name: "autoposter-doctor:group-without-healthy-accounts",
			severity: "critical",
			message: `${groupedRows.length} enabled group(s) have no healthy eligible autoposter accounts`,
			details: {
				count: groupedRows.length,
				sampleGroupIds: groupedRows
					.map((row) => row.group_id)
					.slice(0, MAX_SAMPLE_IDS),
			},
		});
	}
}

async function checkPendingRowsMissingProvenance(
	workspaceIds: string[],
	findings: DoctorFinding[],
): Promise<void> {
	const { data, error } = await db()
		.from("auto_post_queue")
		.select(
			"id, workspace_id, group_id, account_id, source_type, source_competitor_id, content_fingerprint, publish_fingerprint, generation_id, source_id, metadata, provenance_status, provenance_error",
		)
		.in("workspace_id", workspaceIds)
		.in("status", ["pending", "queued"])
		.or("source_type.is.null,source_type.neq.manual")
		.limit(250);

	if (error) {
		logger.warn("[autoposter-doctor] pending provenance check failed", {
			error: String(error),
		});
		return;
	}

	const rows = ((data ?? []) as Array<
		QueueInvariantRow & {
			source_type?: string | null | undefined;
			source_competitor_id?: string | null | undefined;
			content_fingerprint?: string | null | undefined;
			publish_fingerprint?: string | null | undefined;
			generation_id?: string | null | undefined;
			source_id?: string | null | undefined;
			metadata?: unknown;
			provenance_status?: string | null | undefined;
			provenance_error?: string | null | undefined;
		}
	>).filter((row) => evaluateQueueProvenance(row).decision === "missing");

	for (const [workspaceId, groupedRows] of groupByWorkspace(rows)) {
		findings.push({
			workspace_id: workspaceId,
			check_name: "autoposter-doctor:pending-missing-provenance",
			severity: "error",
			message: `${groupedRows.length} pending/queued non-manual queue item(s) are missing provenance`,
			details: {
				count: groupedRows.length,
				sampleQueueItemIds: sampleIds(groupedRows),
				sampleErrors: groupedRows.slice(0, 5).map((row) => ({
					id: row.id,
					reasons: evaluateQueueProvenance(row).reasons,
				})),
			},
		});
	}
}

async function checkPublishedRowsMissingProvenance(
	workspaceIds: string[],
	findings: DoctorFinding[],
): Promise<void> {
	const cutoff = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
	const { data, error } = await db()
		.from("auto_post_queue")
		.select(
			"id, workspace_id, group_id, account_id, source_type, source_competitor_id, content_fingerprint, publish_fingerprint, generation_id, source_id, metadata, provenance_status, provenance_error, posted_at",
		)
		.in("workspace_id", workspaceIds)
		.eq("status", "published")
		.or("source_type.is.null,source_type.neq.manual")
		.gte("posted_at", cutoff)
		.limit(250);

	if (error) {
		logger.warn("[autoposter-doctor] published provenance check failed", {
			error: String(error),
		});
		return;
	}

	const rows = ((data ?? []) as Array<
		QueueInvariantRow & {
			source_type?: string | null | undefined;
			source_competitor_id?: string | null | undefined;
			content_fingerprint?: string | null | undefined;
			publish_fingerprint?: string | null | undefined;
			generation_id?: string | null | undefined;
			source_id?: string | null | undefined;
			metadata?: unknown;
			provenance_status?: string | null | undefined;
			provenance_error?: string | null | undefined;
		}
	>).filter((row) => evaluateQueueProvenance(row).decision === "missing");

	for (const [workspaceId, groupedRows] of groupByWorkspace(rows)) {
		findings.push({
			workspace_id: workspaceId,
			check_name: "autoposter-doctor:published-missing-provenance",
			severity: "critical",
			message: `${groupedRows.length} published non-manual queue item(s) are missing provenance`,
			details: {
				count: groupedRows.length,
				sampleQueueItemIds: sampleIds(groupedRows),
				sampleErrors: groupedRows.slice(0, 5).map((row) => ({
					id: row.id,
					reasons: evaluateQueueProvenance(row).reasons,
				})),
			},
		});
	}
}

async function checkExpiredPublishingLeases(
	workspaceIds: string[],
	findings: DoctorFinding[],
): Promise<void> {
	const { data, error } = await db()
		.from("auto_post_queue")
		.select(
			"id, workspace_id, group_id, account_id, claim_token, claim_expires_at",
		)
		.in("workspace_id", workspaceIds)
		.eq("status", "publishing")
		.lt("claim_expires_at", new Date().toISOString())
		.limit(100);

	if (error) {
		logger.warn("[autoposter-doctor] expired lease check failed", {
			error: String(error),
		});
		return;
	}

	const rows = (data ?? []) as QueueInvariantRow[];
	for (const [workspaceId, groupedRows] of groupByWorkspace(rows)) {
		findings.push({
			workspace_id: workspaceId,
			check_name: "autoposter-doctor:expired-publishing-lease",
			severity: "error",
			message: `${groupedRows.length} publishing queue item(s) have expired leases`,
			details: {
				count: groupedRows.length,
				sampleQueueItemIds: sampleIds(groupedRows),
				oldestClaimExpiresAt: oldestIso(groupedRows, "claim_expires_at"),
			},
		});
	}
}

async function checkStaleReconciliation(
	workspaceIds: string[],
	findings: DoctorFinding[],
): Promise<void> {
	const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
	const { data, error } = await db()
		.from("auto_post_queue")
		.select(
			"id, workspace_id, group_id, account_id, threads_post_id, external_published_at, finalize_error",
		)
		.in("workspace_id", workspaceIds)
		.in("status", [
			"needs_reconciliation",
			"external_published_local_finalize_failed",
		])
		.lt("external_published_at", cutoff)
		.limit(100);

	if (error) {
		logger.warn("[autoposter-doctor] stale reconciliation check failed", {
			error: String(error),
		});
		return;
	}

	const rows = (data ?? []) as QueueInvariantRow[];
	for (const [workspaceId, groupedRows] of groupByWorkspace(rows)) {
		findings.push({
			workspace_id: workspaceId,
			check_name: "autoposter-doctor:stale-reconciliation",
			severity: "critical",
			message: `${groupedRows.length} reconciliation queue item(s) are older than 24h`,
			details: {
				count: groupedRows.length,
				sampleQueueItemIds: sampleIds(groupedRows),
				sampleThreadsPostIds: groupedRows
					.map((row) => row.threads_post_id)
					.filter(Boolean)
					.slice(0, MAX_SAMPLE_IDS),
				oldestExternalPublishedAt: oldestIso(
					groupedRows,
					"external_published_at",
				),
				sampleFinalizeErrors: groupedRows
					.map((row) => row.finalize_error)
					.filter(Boolean)
					.slice(0, 3),
			},
		});
	}
}

async function checkPublishedQueueWithoutPost(
	workspaceIds: string[],
	findings: DoctorFinding[],
): Promise<void> {
	const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
	const { data, error } = await db()
		.from("auto_post_queue")
		.select("id, workspace_id, group_id, account_id, threads_post_id, posted_at")
		.in("workspace_id", workspaceIds)
		.eq("status", "published")
		.not("threads_post_id", "is", null)
		.gte("posted_at", sevenDaysAgo)
		.limit(250);

	if (error) {
		logger.warn("[autoposter-doctor] published without post check failed", {
			error: String(error),
		});
		return;
	}

	const queueRows = ((data ?? []) as QueueInvariantRow[]).filter(
		(row) => row.threads_post_id,
	);
	const threadsPostIds = [
		...new Set(queueRows.map((row) => row.threads_post_id).filter(Boolean)),
	] as string[];
	if (threadsPostIds.length === 0) return;

	const { data: posts, error: postsError } = await db()
		.from("posts")
		.select("threads_post_id")
		.in("threads_post_id", threadsPostIds);

	if (postsError) {
		logger.warn("[autoposter-doctor] posts lookup failed", {
			error: String(postsError),
		});
		return;
	}

	const existing = new Set(
		((posts ?? []) as Array<{ threads_post_id: string | null }>)
			.map((row) => row.threads_post_id)
			.filter(Boolean),
	);
	const missing = queueRows.filter(
		(row) => row.threads_post_id && !existing.has(row.threads_post_id),
	);

	for (const [workspaceId, groupedRows] of groupByWorkspace(missing)) {
		findings.push({
			workspace_id: workspaceId,
			check_name: "autoposter-doctor:published-without-post",
			severity: "critical",
			message: `${groupedRows.length} published queue item(s) have no posts row`,
			details: {
				count: groupedRows.length,
				sampleQueueItemIds: sampleIds(groupedRows),
				sampleThreadsPostIds: groupedRows
					.map((row) => row.threads_post_id)
					.filter(Boolean)
					.slice(0, MAX_SAMPLE_IDS),
			},
		});
	}
}

async function checkAutoposterPostsWithoutQueue(
	workspaceIds: string[],
	findings: DoctorFinding[],
): Promise<void> {
	const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
	const { data, error } = await db()
		.from("posts")
		.select(
			"id, account_id, threads_post_id, cross_post_group_id, metadata, published_at",
		)
		.in("source", ["auto-poster", "auto-poster-reconciled"])
		.not("threads_post_id", "is", null)
		.gte("published_at", sevenDaysAgo)
		.limit(250);

	if (error) {
		logger.warn("[autoposter-doctor] post without queue check failed", {
			error: String(error),
		});
		return;
	}

	const rows = (data ?? []) as PostInvariantRow[];
	const queueIds = rows
		.map((row) => row.metadata?.autoPostQueueId)
		.filter((id): id is string => typeof id === "string" && id.length > 0);
	if (queueIds.length === 0) return;

	const { data: queueRows, error: queueError } = await db()
		.from("auto_post_queue")
		.select("id, workspace_id")
		.in("id", queueIds);

	if (queueError) {
		logger.warn("[autoposter-doctor] queue lookup failed", {
			error: String(queueError),
		});
		return;
	}

	const existing = new Set(
		((queueRows ?? []) as Array<{ id: string }>).map((row) => row.id),
	);
	const missing = rows.filter((row) => {
		const queueId = row.metadata?.autoPostQueueId;
		return typeof queueId === "string" && !existing.has(queueId);
	});
	if (missing.length === 0) return;

	const groupIds = [
		...new Set(
			missing
				.map((row) => row.cross_post_group_id)
				.filter((id): id is string => Boolean(id)),
		),
	];
	const groupWorkspaceMap = await loadGroupWorkspaceMap(groupIds, workspaceIds);

	const byWorkspace = new Map<string, PostInvariantRow[]>();
	for (const row of missing) {
		const workspaceId = row.cross_post_group_id
			? groupWorkspaceMap.get(row.cross_post_group_id)
			: null;
		if (!workspaceId) continue;
		const rowsForWorkspace = byWorkspace.get(workspaceId) ?? [];
		rowsForWorkspace.push(row);
		byWorkspace.set(workspaceId, rowsForWorkspace);
	}

	for (const [workspaceId, groupedRows] of byWorkspace) {
		findings.push({
			workspace_id: workspaceId,
			check_name: "autoposter-doctor:post-without-queue",
			severity: "warn",
			message: `${groupedRows.length} autoposter post(s) reference missing queue rows`,
			details: {
				count: groupedRows.length,
				samplePostIds: groupedRows.map((row) => row.id).slice(0, MAX_SAMPLE_IDS),
				sampleQueueItemIds: groupedRows
					.map((row) => row.metadata?.autoPostQueueId)
					.filter(Boolean)
					.slice(0, MAX_SAMPLE_IDS),
			},
		});
	}
}

async function checkDuplicatePublishedFingerprints(
	workspaceIds: string[],
	findings: DoctorFinding[],
): Promise<void> {
	const cutoff = new Date(Date.now() - 72 * 60 * 60 * 1000).toISOString();
	const { data, error } = await db()
		.from("auto_post_queue")
		.select(
			"id, workspace_id, group_id, account_id, threads_post_id, posted_at, publish_fingerprint",
		)
		.in("workspace_id", workspaceIds)
		.eq("status", "published")
		.not("publish_fingerprint", "is", null)
		.gte("posted_at", cutoff)
		.limit(500);

	if (error) {
		logger.warn("[autoposter-doctor] duplicate fingerprint check failed", {
			error: String(error),
		});
		return;
	}

	const rows = (data ?? []) as Array<
		QueueInvariantRow & { publish_fingerprint?: string | null | undefined }
	>;
	const byFingerprint = new Map<string, typeof rows>();
	for (const row of rows) {
		if (!row.publish_fingerprint || !row.account_id) continue;
		const key = `${row.workspace_id}:${row.account_id}:${row.publish_fingerprint}`;
		const existing = byFingerprint.get(key) ?? [];
		existing.push(row);
		byFingerprint.set(key, existing);
	}

	const duplicates = Array.from(byFingerprint.values()).filter(
		(group) => group.length > 1,
	);
	const byWorkspace = new Map<string, typeof duplicates>();
	for (const group of duplicates) {
		const workspaceId = group[0]?.workspace_id;
		if (!workspaceId) continue;
		const workspaceGroups = byWorkspace.get(workspaceId) ?? [];
		workspaceGroups.push(group);
		byWorkspace.set(workspaceId, workspaceGroups);
	}

	for (const [workspaceId, duplicateGroups] of byWorkspace) {
		findings.push({
			workspace_id: workspaceId,
			check_name: "autoposter-doctor:duplicate-published-fingerprint",
			severity: "critical",
			message: `${duplicateGroups.length} duplicate published fingerprint group(s) found`,
			details: {
				count: duplicateGroups.length,
				sampleDuplicateGroups: duplicateGroups.slice(0, 5).map((group) => ({
					accountId: group[0]?.account_id ?? null,
					publishFingerprint: group[0]?.publish_fingerprint ?? null,
					queueItemIds: sampleIds(group),
					threadsPostIds: group
						.map((row) => row.threads_post_id)
						.filter(Boolean)
						.slice(0, MAX_SAMPLE_IDS),
				})),
			},
		});
	}
}

async function persistDoctorFindings(
	findings: DoctorFinding[],
): Promise<number> {
	if (findings.length === 0) return 0;

	const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
	const { data: recentAlerts } = await db()
		.from("watchdog_alerts")
		.select("workspace_id, check_name")
		.is("resolved_at", null)
		.gte("created_at", twoHoursAgo);

	const recentKeys = new Set(
		((recentAlerts ?? []) as Array<{
			workspace_id: string;
			check_name: string;
		}>).map((row) => `${row.workspace_id}:${row.check_name}`),
	);

	let persisted = 0;
	for (const finding of findings) {
		const key = `${finding.workspace_id}:${finding.check_name}`;
		if (recentKeys.has(key)) continue;
		const { error } = await db().from("watchdog_alerts").insert({
			workspace_id: finding.workspace_id,
			check_name: finding.check_name,
			severity: finding.severity,
			message: finding.message,
			details: finding.details,
		});
		if (error) {
			logger.warn("[autoposter-doctor] Failed to persist finding", {
				check: finding.check_name,
				workspaceId: finding.workspace_id,
				error: String(error),
			});
			continue;
		}
		await Promise.allSettled([
			recordWorkspaceActivity(finding),
			alertWorkspace(
				finding.workspace_id,
				finding.severity === "critical" ? AlertLevel.CRITICAL : AlertLevel.WARN,
				`Autoposter doctor: ${finding.message}`,
				{
					check: finding.check_name,
					count: Number(finding.details.count ?? 0),
				},
				{ mirrorToGlobal: finding.severity === "critical" },
			),
		]);
		persisted++;
	}
	return persisted;
}

async function recordWorkspaceActivity(finding: DoctorFinding): Promise<void> {
	const { error } = await db().from("workspace_activity").insert({
		workspace_id: finding.workspace_id,
		action_type: "autoposter_doctor_issue",
		action_details: {
			checkName: finding.check_name,
			severity: finding.severity,
			message: finding.message,
			...finding.details,
		},
	} as Record<string, unknown>);

	if (error) {
		logger.warn("[autoposter-doctor] Failed to record workspace activity", {
			workspaceId: finding.workspace_id,
			check: finding.check_name,
			error: String(error),
		});
	}
}

async function loadGroupWorkspaceMap(
	groupIds: string[],
	enabledWorkspaceIds: string[],
): Promise<Map<string, string>> {
	if (groupIds.length === 0) return new Map();
	const { data, error } = await db()
		.from("auto_post_group_config")
		.select("group_id, workspace_id")
		.in("group_id", groupIds)
		.in("workspace_id", enabledWorkspaceIds);
	if (error) {
		logger.warn("[autoposter-doctor] group workspace lookup failed", {
			error: String(error),
		});
		return new Map();
	}
	return new Map(
		((data ?? []) as Array<{ group_id: string; workspace_id: string }>).map(
			(row) => [row.group_id, row.workspace_id],
		),
	);
}

function groupByWorkspace<T extends { workspace_id: string | null }>(
	rows: T[],
): Map<string, T[]> {
	const grouped = new Map<string, T[]>();
	for (const row of rows) {
		if (!row.workspace_id) continue;
		const group = grouped.get(row.workspace_id) ?? [];
		group.push(row);
		grouped.set(row.workspace_id, group);
	}
	return grouped;
}

function sampleIds(rows: Array<{ id: string }>): string[] {
	return rows.map((row) => row.id).slice(0, MAX_SAMPLE_IDS);
}

function sampleAccountIds(rows: Array<{ account_id: string }>): string[] {
	return rows.map((row) => row.account_id).slice(0, MAX_SAMPLE_IDS);
}

function oldestIso<T>(rows: T[], key: keyof T): string | null {
	const values: string[] = [];
	for (const row of rows) {
		const value = row[key];
		if (typeof value === "string") values.push(value);
	}
	return values.sort()[0] ?? null;
}
