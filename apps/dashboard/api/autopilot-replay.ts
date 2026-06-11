import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	getAuthUserOrError,
} from "./_lib/apiResponse.js";
import { logRun } from "./_lib/autopilotRunLogger.js";
import { withIdempotency } from "./_lib/idempotency.js";
import { logger } from "./_lib/logger.js";
import { getSupabaseAny } from "./_lib/supabase.js";
import { z } from "./_lib/zodCompat.js";

const ReplayStepSchema = z.object({
	runId: z.string().uuid(),
	stepId: z.string().uuid(),
});
type ReplayStepInput = {
	runId: string;
	stepId: string;
};

const SAFE_REPLAY_STEPS = new Set([
	"queue_select",
	"generate",
	"validate",
	"media_prep",
]);

function objectValue(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

function stringValue(value: unknown): string | undefined {
	return typeof value === "string" && value.length > 0 ? value : undefined;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const parsed = ReplayStepSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(res, 400, "Invalid replay request");
	}

	return withIdempotency(
		req,
		res,
		{
			userId: user.id,
			route: "autopilot-replay",
			action: "replay-step",
			enabled: true,
			requireKey: true,
			failClosed: true,
		},
		() => handleReplay(req, res, user.id, parsed.data),
	);
}

async function handleReplay(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	input: ReplayStepInput,
) {
	void req;
	const db = getSupabaseAny();
	const { runId, stepId } = input;

	const { data: run, error: runError } = await db
		.from("autopilot_runs")
		.select("*")
		.eq("id", runId)
		.eq("user_id", userId)
		.maybeSingle();
	if (runError) return apiError(res, 500, "Could not load run");
	if (!run) return apiError(res, 404, "Run not found");

	const { data: step, error: stepError } = await db
		.from("autopilot_run_steps")
		.select("*")
		.eq("id", stepId)
		.eq("run_id", runId)
		.maybeSingle();
	if (stepError) return apiError(res, 500, "Could not load step");
	if (!step) return apiError(res, 404, "Step not found");
	if (!SAFE_REPLAY_STEPS.has(step.step_name)) {
		return apiError(res, 409, "This step is not safe to replay in v1");
	}

	if (run.run_type === "queue_fill") {
		return replayQueueFill(res, db, userId, run, step);
	}
	if (run.run_type === "publish" && step.step_name === "media_prep") {
		return replayMediaPrep(res, db, userId, run, step);
	}

	return apiError(res, 409, "Replay is not supported for this step yet");
}

async function replayQueueFill(
	res: VercelResponse,
	db: ReturnType<typeof getSupabaseAny>,
	userId: string,
	run: Record<string, unknown>,
	step: Record<string, unknown>,
) {
	const metadata = objectValue(run.metadata);
	const inputs = objectValue(step.inputs);
	const workspaceId =
		stringValue(inputs.workspaceId) ?? stringValue(metadata.workspaceId);
	const ownerId = stringValue(inputs.ownerId) ?? userId;
	const groupId = stringValue(inputs.groupId) ?? stringValue(metadata.groupId);

	if (!workspaceId) {
		return apiError(
			res,
			409,
			"Captured step inputs do not include workspaceId",
		);
	}

	const { enforceOutboundOperatorGuard } = await import(
		"./_lib/outboundOperatorGuard.js"
	);
	const outboundGuard = await enforceOutboundOperatorGuard({
		db,
		userId,
		actionName: "queue_fill_replay",
		riskLevel: "high",
		scope: {
			workspaceId,
			groupId: groupId ?? null,
		},
		payload: {
			runId: String(run.id),
			stepId: String(step.id),
			workspaceId,
			groupId: groupId ?? null,
		},
		idempotencyKey: `replay-queue-fill:${run.id}:${step.id}`,
		metadata: {
			parentRunId: String(run.id),
			replayedFromStep: step.step_name,
		},
	});
	if (!outboundGuard.allowed) {
		return apiError(res, 423, outboundGuard.reason, {
			code: outboundGuard.code,
		});
	}

	const replay = await logRun({
		db,
		userId,
		runType: "queue_fill",
		trigger: "replay",
		parentRunId: String(run.id),
		metadata: {
			replayedFromStepId: step.id,
			replayedFromStep: step.step_name,
			workspaceId,
			groupId: groupId ?? null,
		},
	});

	try {
		const selectStart = Date.now();
		const { data: config } = await db
			.from("auto_post_config")
			.select("*")
			.eq("workspace_id", workspaceId)
			.maybeSingle();
		await replay.logStep({
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
			await replay.finishRun("failed", { reason: "no_config" });
			return apiSuccess(res, { runId: replay.runId, status: "failed" });
		}

		const { checkAndFillQueueWithAI } = await import(
			"./_lib/handlers/auto-post/contentSelection.js"
		);
		const generateStart = Date.now();
		const result = await checkAndFillQueueWithAI(
			config,
			workspaceId,
			ownerId,
			groupId,
		);
		await replay.logStep({
			name: "generate",
			status: "success",
			inputs: { workspaceId, ownerId, groupId: groupId ?? null },
			outputs: result,
			durationMs: Date.now() - generateStart,
		});
		await replay.logStep({
			name: "validate",
			status: "success",
			inputs: {
				workspaceId,
				ownerId,
				groupId: groupId ?? null,
				filled: result.filled,
			},
			outputs: { accepted: result.count, reason: result.reason ?? null },
			durationMs: 0,
		});
		await replay.logStep({
			name: "insert",
			status: result.filled || result.count > 0 ? "success" : "skipped",
			inputs: { workspaceId, groupId: groupId ?? null },
			outputs: { inserted: result.count },
			durationMs: 0,
		});
		await replay.finishRun(
			result.filled || result.count > 0 ? "success" : "partial",
			result,
		);
		return apiSuccess(res, {
			runId: replay.runId,
			status: result.filled ? "success" : "partial",
		});
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		await replay.logStep({
			name: String(step.step_name),
			status: "failed",
			inputs,
			error: message,
			durationMs: 0,
		});
		await replay.finishRun("failed", { error: message });
		logger.error("[autopilot-replay] queue_fill replay failed", {
			error: message,
		});
		return apiError(res, 500, "Queue-fill replay failed");
	}
}

async function replayMediaPrep(
	res: VercelResponse,
	db: ReturnType<typeof getSupabaseAny>,
	userId: string,
	run: Record<string, unknown>,
	step: Record<string, unknown>,
) {
	const replay = await logRun({
		db,
		userId,
		runType: "publish",
		accountId: stringValue(run.account_id) ?? null,
		postId: stringValue(run.post_id) ?? null,
		trigger: "replay",
		parentRunId: String(run.id),
		metadata: {
			replayedFromStepId: step.id,
			replayedFromStep: step.step_name,
			note: "v1 media prep replay does not dispatch to Meta",
		},
	});
	await replay.logStep({
		name: "media_prep",
		status: "success",
		inputs: step.inputs ?? null,
		outputs: {
			...objectValue(step.outputs),
			replayed: true,
			dispatchSkipped: true,
		},
		durationMs: 0,
	});
	await replay.logStep({
		name: "dispatch",
		status: "skipped",
		inputs: { reason: "unsafe_v1" },
		outputs: { message: "Dispatch step replays would re-publish the post." },
		durationMs: 0,
	});
	await replay.finishRun("partial", {
		reason: "media_prep_replayed_dispatch_skipped",
	});
	return apiSuccess(res, { runId: replay.runId, status: "partial" });
}
