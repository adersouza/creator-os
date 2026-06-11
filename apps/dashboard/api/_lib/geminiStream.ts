/**
 * Shared helper for streaming Gemini output over SSE.
 *
 * Write pattern:
 *   import { streamGemini } from "./geminiStream.js";
 *
 *   const stream = await streamGemini(res, {
 *     apiKey,
 *     model: "gemini-2.0-flash",
 *     prompt,
 *     maxOutputTokens: 800,
 *     temperature: 0.4,
 *   });
 *
 *   // stream.text is the accumulated sanitized text once streaming finishes.
 *   // stream.usage is the usageMetadata block (if Gemini returned one).
 *   // Caller can then `sendDone(res, { sections, aggregate: ... })` to emit
 *   // a final structured payload before closing the stream.
 *
 * The helper owns the SSE headers + chunk writes; callers own the prompt
 * construction, cost accounting, and any post-stream parsing.
 */

import { GoogleGenAI } from "@google/genai";
import type { VercelResponse } from "@vercel/node";
import { sanitizeAIOutput } from "./promptUtils.js";

const ALLOWED_ORIGIN =
	process.env.APP_URL ||
	(process.env.VERCEL_URL
		? `https://${process.env.VERCEL_URL}`
		: "https://juno33.com");

export interface GeminiStreamOptions {
	apiKey: string;
	model: string;
	prompt: string;
	maxOutputTokens: number;
	temperature: number;
	thinkingBudget?: number | undefined;
}

export interface GeminiStreamResult {
	text: string;
	usage?: {
        		promptTokenCount: number;
        		candidatesTokenCount: number;
        		thoughtsTokenCount?: number | undefined;
        	} | undefined;
}

export function writeSseHeaders(res: VercelResponse): void {
	res.writeHead(200, {
		"Content-Type": "text/event-stream",
		"Cache-Control": "no-cache, no-transform",
		Connection: "keep-alive",
		"Access-Control-Allow-Origin": ALLOWED_ORIGIN,
	});
}

/**
 * Send a single SSE event with a JSON payload.
 * Events come in two shapes:
 *   { text: "..." }     — incremental token chunk
 *   { done: true, ... } — terminal event with structured payload
 *   { error: "..." }    — error during streaming (terminal)
 */
export function sendSseEvent(
	res: VercelResponse,
	payload: Record<string, unknown>,
): void {
	res.write(`data: ${JSON.stringify(payload)}\n\n`);
}

export function sendDone(
	res: VercelResponse,
	payload: Record<string, unknown> = {},
): void {
	res.write(`data: ${JSON.stringify({ done: true, ...payload })}\n\n`);
	res.write("data: [DONE]\n\n");
	res.end();
}

export function sendError(res: VercelResponse, message: string): void {
	try {
		res.write(`data: ${JSON.stringify({ error: message })}\n\n`);
		res.write("data: [DONE]\n\n");
		res.end();
	} catch {
		// Stream may already be closed.
	}
}

/**
 * Stream tokens from Gemini to the SSE response. Each chunk is sanitized
 * and emitted as a `{text: ...}` event. Returns the accumulated text and
 * the usage metadata (if Gemini provides one — it only does for non-stream
 * calls, so callers generally have to estimate from character counts).
 */
export async function streamGemini(
	res: VercelResponse,
	options: GeminiStreamOptions,
): Promise<GeminiStreamResult> {
	const {
		apiKey,
		model,
		prompt,
		maxOutputTokens,
		temperature,
		thinkingBudget = 0,
	} = options;

	const genai = new GoogleGenAI({ apiKey });
	const stream = await genai.models.generateContentStream({
		model,
		contents: prompt,
		config: {
			maxOutputTokens,
			temperature,
			thinkingConfig: { thinkingBudget },
		},
	});

	const chunks: string[] = [];
	let lastUsage: GeminiStreamResult["usage"];

	for await (const chunk of stream) {
		const text = chunk.text;
		if (text) {
			const clean = sanitizeAIOutput(text);
			chunks.push(clean);
			sendSseEvent(res, { text: clean });
		}
		const usage = (
			chunk as unknown as {
				usageMetadata?: GeminiStreamResult["usage"] | undefined;
			}
		).usageMetadata;
		if (usage) lastUsage = usage;
	}

	return { text: chunks.join(""), usage: lastUsage };
}
