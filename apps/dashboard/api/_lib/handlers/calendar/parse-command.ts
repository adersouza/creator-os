import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getUserAIConfig } from "../../aiConfig.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";

const fallbackIntent = {
	action: "unknown",
	post_filter: {},
	time_target: {},
	reasoning: "Could not parse command with the LLM.",
};

export async function handleParseCommand(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");
	const { text, context } = req.body ?? {};
	if (!text || typeof text !== "string") return apiError(res, 400, "text is required");

	const aiConfig = await getUserAIConfig(userId);
	if (!aiConfig?.apiKey) {
		return apiError(res, 503, "No AI key is configured for command parsing.");
	}

	const prompt = `Parse this calendar scheduling command into JSON.

Command: ${JSON.stringify(text)}
Context: ${JSON.stringify(context ?? {})}

Allowed actions: move_to_weekday, relative_offset, time_of_day, spread_evenly, fill_gaps, unknown.
Return only JSON:
{"action":"...","post_filter":{"weekday":"monday|...","account":"@handle|null"},"time_target":{"weekday":"monday|...","amount":number,"unit":"hours|days|null","time_of_day":"morning|afternoon|evening|null"},"reasoning":"short human explanation"}`;

	try {
		const modelId = aiConfig.model || "gemini-2.5-flash";
		const response = await generateWithProvider(prompt, {
			provider: aiConfig.provider,
			apiKey: aiConfig.apiKey,
			baseUrl: aiConfig.baseUrl,
			model: modelId,
			keySource: aiConfig.source,
			ideaCount: 1,
			useStructuredOutput: true,
			structuredOutputSchema: {
				type: "OBJECT",
				properties: {
					action: { type: "STRING" },
					post_filter: { type: "OBJECT" },
					time_target: { type: "OBJECT" },
					reasoning: { type: "STRING" },
				},
				required: ["action", "post_filter", "time_target", "reasoning"],
			},
			actionLog: {
				userId,
				surface: "composer",
				actionType: "calendar_parse_command",
				inputText: text.slice(0, 2000),
				metadata: { provider: aiConfig.provider },
			},
		});
		const textOut = (response || "").trim();
		const json = textOut.match(/\{[\s\S]*\}/)?.[0];
		if (!json) return apiError(res, 502, fallbackIntent.reasoning);
		return apiSuccess(res, { intent: JSON.parse(json) });
	} catch (error) {
		return apiError(
			res,
			502,
			error instanceof Error ? error.message : "LLM parser failed.",
		);
	}
}
