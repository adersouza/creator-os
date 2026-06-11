// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { logger } from "../logger.js";
import { withRetry } from "../retryUtils.js";

const EMBED_TIMEOUT_MS = 8_000;

export function cosineSimilarity(a: number[], b: number[]): number {
	if (a.length !== b.length || a.length === 0) return 0;
	let dot = 0;
	let normA = 0;
	let normB = 0;
	for (let i = 0; i < a.length; i++) {
		dot += a[i]! * b[i]!;
		normA += a[i]! * a[i]!;
		normB += b[i]! * b[i]!;
	}
	const denom = Math.sqrt(normA) * Math.sqrt(normB);
	return denom === 0 ? 0 : dot / denom;
}

export async function getOpenAIEmbedding(text: string): Promise<number[] | null> {
	const apiKey = process.env.OPENAI_API_KEY;
	if (!apiKey || !text.trim()) return null;

	try {
		const response = await withRetry(() =>
			fetch("https://api.openai.com/v1/embeddings", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${apiKey}`,
				},
				signal: AbortSignal.timeout(EMBED_TIMEOUT_MS),
				body: JSON.stringify({
					model: "text-embedding-3-small",
					input: text.slice(0, 8_000),
				}),
			}),
		);

		if (!response.ok) {
			logger.warn("[embeddings] OpenAI embedding request failed", {
				status: response.status,
			});
			return null;
		}

		const data = await response.json();
		const embedding = data?.data?.[0]?.embedding;
		return Array.isArray(embedding) ? embedding.map(Number) : null;
	} catch (error) {
		logger.warn("[embeddings] OpenAI embedding call failed", {
			error: error instanceof Error ? error.message : String(error),
		});
		return null;
	}
}
