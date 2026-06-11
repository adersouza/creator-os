import { createHash } from "node:crypto";
import { logger } from "./logger.js";
import { getSupabaseAny } from "./supabase.js";

type SupabaseAny = ReturnType<typeof getSupabaseAny>;

export type AIEvalSnapshotInput = {
	userId: string;
	workspaceId?: string | null;
	groupId?: string | null;
	accountId?: string | null;
	suiteName: string;
	caseId: string;
	category: string;
	prompt: string;
	provider: string;
	model: string;
	modelVersion?: string | null;
	parameters?: Record<string, unknown> | null;
	candidateOutputs: unknown[];
	filterResults?: unknown[] | null;
	judgeScores?: unknown[] | null;
	selectedOutput?: unknown;
	selectedOutputId?: string | null;
	insertedIds?: string[] | null;
	scheduledIds?: string[] | null;
	performanceSnapshot?: Record<string, unknown> | null;
	regressionScore?: number | null;
	passed: boolean;
	failures?: string[] | null;
	metadata?: Record<string, unknown> | null;
	capturedAt?: string | null;
};

export type AIEvalSnapshotResult =
	| { ok: true; id: string | null; promptHash: string }
	| { ok: false; error: string; promptHash: string };

export type DirectAIEvalSnapshotInput = {
	userId?: string | null;
	workspaceId?: string | null;
	groupId?: string | null;
	accountId?: string | null;
	surface: string;
	actionType: string;
	category?: string | null;
	prompt: string;
	output?: unknown;
	provider: string;
	model: string;
	modelVersion?: string | null;
	parameters?: Record<string, unknown> | null;
	filterResults?: unknown[] | null;
	judgeScores?: unknown[] | null;
	passed: boolean;
	failures?: string[] | null;
	metadata?: Record<string, unknown> | null;
};

export const AI_EVAL_DIRECT_GENERATIVE_SURFACES = [
	"copilot",
	"ai_alt_text",
	"ai_vision_score",
	"media_vision",
	"inspiration_idea",
	"trend_pipeline_generator",
] as const;

export const AI_EVAL_DOCUMENTED_NON_GENERATIVE_SURFACES = [
	"ai_image_generation",
	"embedding_similarity",
	"deterministic_policy_gate",
	"deterministic_publish_preflight",
] as const;

export function buildAIEvalSnapshotRow(
	input: AIEvalSnapshotInput,
): Record<string, unknown> {
	const promptHash = hashStableValue(input.prompt);
	return {
		user_id: input.userId,
		workspace_id: input.workspaceId ?? null,
		group_id: input.groupId ?? null,
		account_id: input.accountId ?? null,
		suite_name: input.suiteName,
		case_id: input.caseId,
		category: input.category,
		prompt: input.prompt,
		prompt_hash: promptHash,
		provider: input.provider,
		model: input.model,
		model_version: input.modelVersion ?? null,
		parameters: input.parameters ?? {},
		candidate_outputs: input.candidateOutputs,
		filter_results: input.filterResults ?? [],
		judge_scores: input.judgeScores ?? [],
		selected_output:
			typeof input.selectedOutput === "undefined" ? null : input.selectedOutput,
		selected_output_id: input.selectedOutputId ?? null,
		inserted_ids: input.insertedIds ?? [],
		scheduled_ids: input.scheduledIds ?? [],
		performance_snapshot: input.performanceSnapshot ?? {},
		regression_score: input.regressionScore ?? null,
		passed: input.passed,
		failures: input.failures ?? [],
		metadata: input.metadata ?? {},
		captured_at: input.capturedAt ?? new Date().toISOString(),
	};
}

export async function recordAIEvalSnapshot(
	input: AIEvalSnapshotInput,
	db: SupabaseAny = getSupabaseAny(),
): Promise<AIEvalSnapshotResult> {
	const row = buildAIEvalSnapshotRow(input);
	const promptHash = String(row.prompt_hash);
	try {
		const { data, error } = await db
			.from("ai_eval_snapshots")
			.insert(row)
			.select("id")
			.maybeSingle();
		if (error) {
			const message = error.message || "Failed to persist AI eval snapshot";
			logger.error("AI eval snapshot insert failed", {
				userId: input.userId,
				suiteName: input.suiteName,
				caseId: input.caseId,
				error: message,
			});
			return { ok: false, error: message, promptHash };
		}
		return { ok: true, id: typeof data?.id === "string" ? data.id : null, promptHash };
	} catch (err: unknown) {
		const message = err instanceof Error ? err.message : String(err);
		logger.error("AI eval snapshot insert threw", {
			userId: input.userId,
			suiteName: input.suiteName,
			caseId: input.caseId,
			error: message,
		});
		return { ok: false, error: message, promptHash };
	}
}

export async function recordDirectAIEvalSnapshot(
	input: DirectAIEvalSnapshotInput,
	db: SupabaseAny = getSupabaseAny(),
): Promise<AIEvalSnapshotResult> {
	const output = normalizeDirectOutput(input.output);
	return recordAIEvalSnapshot(
		{
			userId: input.userId || "platform",
			workspaceId: input.workspaceId ?? null,
			groupId: input.groupId ?? null,
			accountId: input.accountId ?? null,
			suiteName: `live:${input.surface}`,
			caseId: input.actionType,
			category: input.category || input.surface,
			prompt: redactEvalText(input.prompt),
			provider: input.provider,
			model: input.model,
			modelVersion: input.modelVersion ?? null,
			parameters: input.parameters ?? {},
			candidateOutputs: typeof output === "undefined" ? [] : [output],
			filterResults: input.filterResults ?? [],
			judgeScores: input.judgeScores ?? [],
			selectedOutput: output,
			selectedOutputId: typeof output === "undefined" ? null : `${input.actionType}:direct-output`,
			passed: input.passed,
			failures: input.failures ?? (input.passed ? [] : ["direct_provider_failed"]),
			metadata: {
				...(input.metadata ?? {}),
				actionType: input.actionType,
				surface: input.surface,
				source: "directProvider",
			},
		},
		db,
	);
}

export function hashStableValue(value: unknown): string {
	return createHash("sha256").update(JSON.stringify(stableValue(value))).digest("hex");
}

function normalizeDirectOutput(output: unknown): unknown {
	if (typeof output === "undefined") return undefined;
	if (typeof output === "string") return { text: redactEvalText(output) };
	if (!output || typeof output !== "object") return output;
	return truncateStableOutput(output);
}

function truncateStableOutput(value: unknown, depth = 0): unknown {
	if (depth > 4) return "[TRUNCATED]";
	if (typeof value === "string") return redactEvalText(value);
	if (Array.isArray(value)) return value.slice(0, 20).map((item) => truncateStableOutput(item, depth + 1));
	if (!value || typeof value !== "object") return value;

	const out: Record<string, unknown> = {};
	for (const [key, child] of Object.entries(value).slice(0, 40)) {
		out[key] = truncateStableOutput(child, depth + 1);
	}
	return out;
}

function redactEvalText(value: unknown): string {
	const text = typeof value === "string" ? value : JSON.stringify(value ?? "");
	return text
		.replace(/sk-[A-Za-z0-9_-]{16,}/g, "sk-[REDACTED]")
		.replace(/juno_ak_[A-Za-z0-9_-]+/g, "juno_ak_[REDACTED]")
		.replace(/Bearer\s+[A-Za-z0-9._-]+/g, "Bearer [REDACTED]")
		.replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, "[EMAIL]")
		.replace(/\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b/g, "[PHONE]")
		.slice(0, 4000);
}

function stableValue(value: unknown): unknown {
	if (Array.isArray(value)) return value.map(stableValue);
	if (!value || typeof value !== "object") return value;

	const out: Record<string, unknown> = {};
	for (const [key, child] of Object.entries(value).sort(([a], [b]) => a.localeCompare(b))) {
		out[key] = stableValue(child);
	}
	return out;
}
