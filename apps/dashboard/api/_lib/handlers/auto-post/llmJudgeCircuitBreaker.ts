import { recordInfraEvent } from "../../infraTelemetry.js";
import { logger } from "../../logger.js";

const WINDOW_SECONDS = 60 * 60;
const SKIP_RATIO_THRESHOLD = 0.25;
const MIN_OBSERVATIONS = 4;

function scopeKey(workspaceId: string, groupId: string | undefined): string {
	return `${workspaceId}:${groupId ?? "workspace"}`;
}

function hourKey(): string {
	return new Date().toISOString().slice(0, 13);
}

function totalsKey(workspaceId: string, groupId: string | undefined): string {
	return `llm-judge:totals:${scopeKey(workspaceId, groupId)}:${hourKey()}`;
}

function breakerKey(workspaceId: string, groupId: string | undefined): string {
	return `llm-judge:circuit-open:${scopeKey(workspaceId, groupId)}`;
}

export async function isLLMJudgeCircuitOpen(
	workspaceId: string,
	groupId: string | undefined,
): Promise<boolean> {
	try {
		const { getRedis } = await import("../../redis.js");
		const redis = getRedis();
		return Boolean(await redis.get(breakerKey(workspaceId, groupId)));
	} catch (error) {
		logger.debug("[llmJudgeCircuitBreaker] Redis read failed", {
			workspaceId,
			groupId,
			error: error instanceof Error ? error.message : String(error),
		});
		return false;
	}
}

export async function recordLLMJudgeSkips(args: {
	workspaceId: string;
	groupId?: string | undefined;
	accountIds?: string[] | undefined;
	total: number;
	skipped: number;
	error: string;
}): Promise<void> {
	if (args.total <= 0 || args.skipped <= 0) return;

	await recordInfraEvent("llm_judge_skip_count", {
		workspace_id: args.workspaceId,
		group_id: args.groupId ?? null,
		skipped: args.skipped,
		total: args.total,
		error: args.error,
	});

	logger.warn("[pipelineFilters] LLM judge skipped candidates — failing open", {
		account_id:
			args.accountIds && args.accountIds.length === 1 ? args.accountIds[0] : null,
		account_ids: args.accountIds ?? [],
		post_id: null,
		error: args.error,
		workspaceId: args.workspaceId,
		groupId: args.groupId,
		skipped: args.skipped,
		total: args.total,
	});

	try {
		const { getRedis } = await import("../../redis.js");
		const redis = getRedis();
		const key = totalsKey(args.workspaceId, args.groupId);
		const total = await redis.hincrby(key, "total", args.total);
		const skipped = await redis.hincrby(key, "skipped", args.skipped);
		await redis.expire(key, WINDOW_SECONDS + 300);

		if (total >= MIN_OBSERVATIONS && skipped / total > SKIP_RATIO_THRESHOLD) {
			const breaker = breakerKey(args.workspaceId, args.groupId);
			await redis.set(
				breaker,
				JSON.stringify({
					opened_at: new Date().toISOString(),
					reason: "llm_judge_skip_rate",
					skipped,
					total,
					ratio: skipped / total,
					error: args.error,
				}),
			);
			logger.warn("[llmJudgeCircuitBreaker] Circuit opened", {
				workspaceId: args.workspaceId,
				groupId: args.groupId,
				skipped,
				total,
				ratio: skipped / total,
				manualClearKey: breaker,
			});
		}
	} catch (error) {
		logger.debug("[llmJudgeCircuitBreaker] Redis write failed", {
			workspaceId: args.workspaceId,
			groupId: args.groupId,
			error: error instanceof Error ? error.message : String(error),
		});
	}
}
