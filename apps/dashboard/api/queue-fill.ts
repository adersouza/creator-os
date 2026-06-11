/**
 * QStash Queue Fill Endpoint
 *
 * Dispatched by trigger_queue_fill MCP tool or auto-post-worker cron.
 * Runs the full AI content generation pipeline for a single group.
 * Auth: QStash signature verification.
 *
 * POST /api/queue-fill
 * Body: { workspaceId, ownerId, groupId }
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alert, AlertLevel } from "./_lib/alerting.js";
import { withIdempotency } from "./_lib/idempotency.js";
import { logger } from "./_lib/logger.js";
import { verifyQStashSignature } from "./_lib/qstash.js";
import { z } from "./_lib/zodCompat.js";

const QueueFillBodySchema = z.object({
	workspaceId: z.string().min(1),
	ownerId: z.string().min(1),
	groupId: z.string().optional(),
	traceId: z.string().optional(),
	parentRunId: z.string().optional(),
});

export const config = { maxDuration: 120 };

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") {
		const { apiError } = await import("./_lib/apiResponse.js");
		return apiError(res, 405, "Method not allowed");
	}

	if (!(await verifyQStashSignature(req, res))) return;

	const parsed = QueueFillBodySchema.safeParse(req.body);
	if (!parsed.success) {
		return res
			.status(400)
			.json({ ok: false, skipped: true, reason: "invalid_body" });
	}
	const {
		workspaceId: requestedWorkspaceId,
		ownerId: requestedOwnerId,
		groupId,
		traceId,
		parentRunId,
	} = parsed.data;
	const queueFillKey = `queue-fill:${requestedWorkspaceId}:${groupId ?? "workspace"}:${traceId ?? parentRunId ?? "qstash"}`;
	req.headers["idempotency-key"] = queueFillKey;

	return withIdempotency(
		req,
		res,
		{
			userId: requestedOwnerId,
			route: "queue-fill",
			action: "fill",
			enabled: true,
			requireKey: true,
			failClosed: true,
		},
		async () => {
			try {
		// Re-derive ownership from database rows. QStash request bodies are hints.
		const { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } = await import(
			"./_lib/privilegedDb.js"
		);
		const { apiError } = await import("./_lib/apiResponse.js");
		const db = getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.queueFill);
		const { data: workspace, error: workspaceError } = await db
			.from("workspaces")
			.select("id, owner_id")
			.eq("id", requestedWorkspaceId)
			.maybeSingle();
		if (workspaceError || !workspace?.owner_id) {
			logger.warn("[queue-fill] Workspace not found", {
				workspaceId: requestedWorkspaceId,
				error: workspaceError ? String(workspaceError.message || workspaceError) : null,
			});
			return apiError(res, 404, "Workspace not found");
		}
		if (requestedOwnerId !== workspace.owner_id) {
			logger.warn("[queue-fill] Rejecting mismatched owner hint", {
				workspaceId: requestedWorkspaceId,
				bodyOwnerId: requestedOwnerId,
				rowOwnerId: workspace.owner_id,
			});
			return apiError(res, 403, "Queue fill owner mismatch");
		}

		if (groupId) {
			const { data: group, error: groupError } = await db
				.from("account_groups")
				.select("id, user_id")
				.eq("id", groupId)
				.maybeSingle();
			if (
				groupError ||
				!group ||
				group.user_id !== workspace.owner_id
			) {
				logger.warn("[queue-fill] Rejecting mismatched group hint", {
					workspaceId: requestedWorkspaceId,
					groupId,
					error: groupError ? String(groupError.message || groupError) : null,
				});
				await alert(AlertLevel.ERROR, "Queue fill rejected", {
					workspaceId: requestedWorkspaceId,
					groupId,
					reason: groupError
						? `group lookup failed: ${String(groupError.message || groupError)}`
						: !group
							? "group not found"
							: "group owner mismatch",
					action:
						"Queue will stay empty until queue-fill ownership validation succeeds.",
				});
				return apiError(res, 403, "Queue fill group mismatch");
			}
		}

		const workspaceId = workspace.id as string;
		const ownerId = workspace.owner_id as string;
		const { enforceOutboundOperatorGuard } = await import(
			"./_lib/outboundOperatorGuard.js"
		);
		const outboundGuard = await enforceOutboundOperatorGuard({
			db,
			req,
			userId: ownerId,
			actionName: "queue_fill",
			riskLevel: "high",
			scope: {
				workspaceId,
				groupId: groupId ?? null,
			},
			payload: {
				workspaceId,
				groupId: groupId ?? null,
				trigger: parentRunId ? "replay" : traceId?.startsWith("manual") ? "manual" : "cron",
			},
			idempotencyKey: queueFillKey,
			metadata: {
				traceId: traceId ?? null,
				parentRunId: parentRunId ?? null,
			},
		});
		if (!outboundGuard.allowed) {
			logger.warn("[queue-fill] Outbound queue fill blocked", {
				workspaceId,
				groupId,
				reason: outboundGuard.reason,
				code: outboundGuard.code,
			});
			return res.status(200).json({
				ok: true,
				skipped: true,
				reason: outboundGuard.code,
				message: outboundGuard.reason,
			});
		}
		const { logRun } = await import("./_lib/autopilotRunLogger.js");
		const runLogger = await logRun({
			db,
			userId: ownerId,
			runType: "queue_fill",
			trigger: parentRunId
				? "replay"
				: traceId?.startsWith("manual")
					? "manual"
					: "cron",
			parentRunId: parentRunId ?? null,
			metadata: {
				workspaceId,
				groupId: groupId ?? null,
				traceId: traceId ?? null,
			},
		});

		const selectStart = Date.now();
		const { data: config } = await db
			.from("auto_post_config")
			.select("*")
			.eq("workspace_id", workspaceId)
			.maybeSingle();
		await runLogger.logStep({
			name: "queue_select",
			status: config ? "success" : "failed",
			inputs: { workspaceId, ownerId, groupId: groupId ?? null },
			outputs: config
				? {
						workspaceId,
						isEnabled: config.is_enabled,
						enableAiQueueFill: config.enable_ai_queue_fill,
					}
				: null,
			error: config ? null : "No auto_post_config found for workspace",
			durationMs: Date.now() - selectStart,
		});

		if (!config) {
			logger.info("[queue-fill] No config found for workspace", {
				workspaceId,
			});
			await runLogger.finishRun("failed", {
				reason: "no_config",
				workspaceId,
				groupId: groupId ?? null,
			});
			return res.status(200).json({ ok: true, reason: "no_config" });
		}

		if (!config.is_enabled) {
			logger.info("[queue-fill] Auto-post disabled", { workspaceId });
			await runLogger.logStep({
				name: "generate",
				status: "skipped",
				inputs: { workspaceId, groupId: groupId ?? null },
				outputs: { reason: "disabled" },
				durationMs: 0,
			});
			await runLogger.finishRun("partial", {
				reason: "disabled",
				workspaceId,
				groupId: groupId ?? null,
			});
			return res.status(200).json({ ok: true, reason: "disabled" });
		}

		if (!config.enable_ai_queue_fill) {
			logger.info("[queue-fill] AI queue fill disabled", { workspaceId });
			await runLogger.logStep({
				name: "generate",
				status: "skipped",
				inputs: { workspaceId, groupId: groupId ?? null },
				outputs: { reason: "ai_fill_disabled" },
				durationMs: 0,
			});
			await runLogger.finishRun("partial", {
				reason: "ai_fill_disabled",
				workspaceId,
				groupId: groupId ?? null,
			});
			return res.status(200).json({ ok: true, reason: "ai_fill_disabled" });
		}

		const { checkAndFillQueueWithAI } = await import(
			"./_lib/handlers/auto-post/contentSelection.js"
		);

		const generateStart = Date.now();
		const result = await checkAndFillQueueWithAI(
			config,
			workspaceId,
			ownerId,
			groupId || undefined,
		);
		await runLogger.logStep({
			name: "generate",
			status: "success",
			inputs: {
				workspaceId,
				ownerId,
				groupId: groupId ?? null,
				config: {
					aiPostsPerFill: config.ai_posts_per_fill ?? null,
					schedulerVersion: config.scheduler_version ?? null,
				},
			},
			outputs: result,
			durationMs: Date.now() - generateStart,
		});
		await runLogger.logStep({
			name: "validate",
			status: result.reason ? "success" : "success",
			inputs: { filled: result.filled, count: result.count },
			outputs: { accepted: result.count, reason: result.reason ?? null },
			durationMs: 0,
		});
		await runLogger.logStep({
			name: "insert",
			status: result.filled || result.count > 0 ? "success" : "skipped",
			inputs: { workspaceId, groupId: groupId ?? null },
			outputs: { inserted: result.count },
			durationMs: 0,
		});
		await runLogger.finishRun(
			result.filled || result.count > 0 ? "success" : "partial",
			{
				workspaceId,
				groupId: groupId ?? null,
				...result,
			},
		);

		logger.info("[queue-fill] Complete", {
			workspaceId,
			groupId,
			filled: result.filled,
			count: result.count,
			reason: result.reason,
		});

		return res.status(200).json({ ok: true, ...result });
	} catch (err) {
		logger.error("[queue-fill] Error", {
			error: err instanceof Error ? err.message : String(err),
			workspaceId: requestedWorkspaceId,
			groupId,
		});
		import("./_lib/sentryServer.js")
			.then(({ captureServerException }) =>
				captureServerException(err, {
					cronJob: "queue-fill",
					workspaceId: requestedWorkspaceId,
					groupId,
				}),
			)
			.catch(() => {});
		const { apiError: apiErr } = await import("./_lib/apiResponse.js");
		return apiErr(res, 500, "Queue fill failed");
	}
		},
	);
}
