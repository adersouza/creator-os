import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiSuccess,
	badRequest,
	methodNotAllowed,
} from "../../apiResponse.js";
import { cosineSimilarity, getOpenAIEmbedding } from "../../embeddings/cosine.js";
import { withAuth } from "../../middleware.js";
import { analyzeSentiment } from "../../sentiment.js";

export default withAuth(
	async (req: VercelRequest, res: VercelResponse) => {
		if (req.method !== "POST") return methodNotAllowed(res);

		const { composer_text, last_replies } = req.body || {};
		if (!composer_text || typeof composer_text !== "string") {
			return badRequest(res, "composer_text is required");
		}
		if (!Array.isArray(last_replies)) {
			return badRequest(res, "last_replies must be an array");
		}

		const replies = last_replies
			.map((reply) => (typeof reply === "string" ? reply.trim() : ""))
			.filter(Boolean)
			.slice(-3);
		const opposingReply = replies.at(-1) ?? null;
		if (!opposingReply) {
			return apiSuccess(res, {
				contradicts: false,
				similarity: 1,
				opposing_reply: null,
			});
		}

		const composerSentiment = normalizeSentiment(analyzeSentiment(composer_text));
		const replySentiment = normalizeSentiment(analyzeSentiment(opposingReply));
		const opposite =
			!!composerSentiment &&
			!!replySentiment &&
			composerSentiment !== replySentiment;

		const [composerEmbedding, replyEmbedding] = await Promise.all([
			getOpenAIEmbedding(composer_text),
			getOpenAIEmbedding(opposingReply),
		]);
		const similarity =
			composerEmbedding && replyEmbedding
				? cosineSimilarity(composerEmbedding, replyEmbedding)
				: 1;

		return apiSuccess(res, {
			contradicts: opposite && similarity < 0.3,
			similarity,
			opposing_reply: opposite ? opposingReply : null,
		});
	},
);

function normalizeSentiment(
	sentiment: ReturnType<typeof analyzeSentiment>,
): "positive" | "negative" | null {
	if (sentiment === "positive" || sentiment === "negative") return sentiment;
	return null;
}
