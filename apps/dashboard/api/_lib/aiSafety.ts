/**
 * Server-side safety clamps for AI API parameters.
 *
 * Prevents client-side manipulation of maxTokens / temperature
 * from inflating API costs or producing unexpected behavior.
 */

/** Hard ceiling — no single generation should exceed this */
const MAX_OUTPUT_TOKENS = 4096;
const DEFAULT_OUTPUT_TOKENS = 1024;
const MIN_OUTPUT_TOKENS = 1;

const MAX_TEMPERATURE = 2.0;
const MIN_TEMPERATURE = 0;
const DEFAULT_TEMPERATURE = 0.7;

/**
 * Clamp maxTokens to a safe server-enforced range.
 * Rejects non-numeric / NaN values and returns the default.
 */
export function clampMaxTokens(input: unknown): number {
	if (input == null || input === "") return DEFAULT_OUTPUT_TOKENS;
	if (typeof input === "object") return DEFAULT_OUTPUT_TOKENS;
	const n = Number(input);
	if (!Number.isFinite(n)) return DEFAULT_OUTPUT_TOKENS;
	if (n <= 0) return MIN_OUTPUT_TOKENS;
	return Math.min(n, MAX_OUTPUT_TOKENS);
}

/**
 * Clamp temperature to the Gemini-supported range [0, 2.0].
 */
export function clampTemperature(
	input: unknown,
	fallback: number = DEFAULT_TEMPERATURE,
): number {
	if (input == null) return fallback;
	const n = Number(input);
	if (!Number.isFinite(n)) return fallback;
	return Math.max(MIN_TEMPERATURE, Math.min(n, MAX_TEMPERATURE));
}
