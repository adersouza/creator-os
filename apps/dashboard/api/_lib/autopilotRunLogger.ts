import type { SupabaseClient } from "@supabase/supabase-js";
import { logger } from "./logger.js";
import { getSupabaseAny } from "./supabase.js";

type RunType = "queue_fill" | "publish" | "sync" | "reply_chain" | "auto_unpost";
type RunStatus = "success" | "failed" | "partial" | "in_progress";
type StepStatus = "success" | "failed" | "skipped";

const MAX_JSON_BYTES = 32 * 1024;

export interface LogRunOptions {
	userId: string;
	runType: RunType;
	accountId?: string | null | undefined;
	postId?: string | null | undefined;
	trigger?: string | null | undefined;
	parentRunId?: string | null | undefined;
	metadata?: Record<string, unknown> | undefined;
	db?: SupabaseClient | undefined;
}

export interface LogStepOptions {
	name: string;
	status: StepStatus;
	inputs?: unknown | undefined;
	outputs?: unknown | undefined;
	error?: unknown | undefined;
	durationMs?: number | undefined;
	startedAt?: string | undefined;
	finishedAt?: string | null | undefined;
}

export interface AutopilotRunLogger {
	runId: string | null;
	logStep: (step: LogStepOptions) => Promise<void>;
	finishRun: (status: RunStatus, metadata?: Record<string, unknown>) => Promise<void>;
}

function safeJson(value: unknown): unknown {
	if (value == null) return value;
	try {
		const json = JSON.stringify(value);
		if (Buffer.byteLength(json, "utf8") <= MAX_JSON_BYTES) return value;
		return {
			truncated: true,
			original_bytes: Buffer.byteLength(json, "utf8"),
			preview: json.slice(0, MAX_JSON_BYTES),
		};
	} catch (error) {
		return {
			unserializable: true,
			error: error instanceof Error ? error.message : String(error),
		};
	}
}

function errorMessage(error: unknown): string | null {
	if (!error) return null;
	if (error instanceof Error) return error.message;
	if (typeof error === "string") return error;
	try {
		return JSON.stringify(error);
	} catch {
		return String(error);
	}
}

export async function logRun(opts: LogRunOptions): Promise<AutopilotRunLogger> {
	const db = opts.db ?? getSupabaseAny();
	let runId: string | null = null;
	let stepIndex = 0;

	try {
		const { data, error } = await db
			.from("autopilot_runs")
			.insert({
				user_id: opts.userId,
				run_type: opts.runType,
				account_id: opts.accountId ?? null,
				post_id: opts.postId ?? null,
				status: "in_progress",
				trigger: opts.trigger ?? null,
				parent_run_id: opts.parentRunId ?? null,
				metadata: opts.metadata ?? {},
			})
			.select("id")
			.maybeSingle();
		if (error) throw error;
		runId = data?.id ?? null;
	} catch (error) {
		logger.warn("[autopilotRunLogger] run insert skipped", {
			runType: opts.runType,
			error: errorMessage(error),
		});
	}

	return {
		runId,
		async logStep(step) {
			if (!runId) return;
			const index = stepIndex++;
			const startedAt = step.startedAt ?? new Date().toISOString();
			const finishedAt = step.finishedAt === undefined ? new Date().toISOString() : step.finishedAt;
			try {
				const { error } = await db.from("autopilot_run_steps").insert({
					run_id: runId,
					step_index: index,
					step_name: step.name,
					status: step.status,
					inputs: safeJson(step.inputs),
					outputs: safeJson(step.outputs),
					error_message: errorMessage(step.error),
					duration_ms: step.durationMs ?? null,
					started_at: startedAt,
					finished_at: finishedAt,
				});
				if (error) throw error;
			} catch (error) {
				logger.warn("[autopilotRunLogger] step insert skipped", {
					runId,
					step: step.name,
					error: errorMessage(error),
				});
			}
		},
		async finishRun(status, metadata) {
			if (!runId) return;
			try {
				const { error } = await db
					.from("autopilot_runs")
					.update({
						status,
						finished_at: new Date().toISOString(),
						...(metadata ? { metadata: safeJson(metadata) } : {}),
					})
					.eq("id", runId);
				if (error) throw error;
			} catch (error) {
				logger.warn("[autopilotRunLogger] run update skipped", {
					runId,
					status,
					error: errorMessage(error),
				});
			}
		},
	};
}
