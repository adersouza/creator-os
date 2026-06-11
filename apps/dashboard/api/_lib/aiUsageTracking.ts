import { trackAICost } from "./aiCostTracker.js";

export type AIKeySource = "user" | "env_fallback";

export type TokenUsage = {
	promptTokens: number;
	completionTokens: number;
	thinkingTokens?: number | undefined;
};

export function getGeminiUsage(response: unknown): TokenUsage | null {
	const usage = (
		response as {
			usageMetadata?:
				| {
						promptTokenCount?: number | undefined;
						candidatesTokenCount?: number | undefined;
						thoughtsTokenCount?: number | undefined;
				  }
				| undefined;
		}
	).usageMetadata;
	if (!usage) return null;
	return {
		promptTokens: usage.promptTokenCount ?? 0,
		completionTokens: usage.candidatesTokenCount ?? 0,
		thinkingTokens: usage.thoughtsTokenCount ?? 0,
	};
}

export function trackAIUsage(
	userId: string,
	usage: TokenUsage | null,
	model: string,
	feature: string,
	keySource?: AIKeySource | undefined,
): void {
	if (!usage) return;
	trackAICost(
		userId,
		usage.promptTokens,
		usage.completionTokens,
		model,
		feature,
		keySource,
		usage.thinkingTokens ?? 0,
	).catch(() => {});
}

export function trackGeminiResponseCost(
	userId: string,
	response: unknown,
	model: string,
	feature: string,
	keySource?: AIKeySource | undefined,
): void {
	trackAIUsage(userId, getGeminiUsage(response), model, feature, keySource);
}
