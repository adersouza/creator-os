/**
 * AI error types — extracted to break circular dep between
 * core.ts ↔ aiProxyClient.ts.
 */

/**
 * Structured error for AI generation failures.
 * Replaces the old pattern of returning "Error: ..." strings.
 */
export class AIGenerationError extends Error {
	/** Whether this error is worth retrying (rate limit, timeout, network) */
	readonly retryable: boolean;

	constructor(message: string, retryable = false) {
		super(message);
		this.name = "AIGenerationError";
		this.retryable = retryable;
	}
}
