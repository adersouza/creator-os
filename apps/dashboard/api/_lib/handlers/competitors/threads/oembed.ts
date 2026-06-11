/**
 * Handler: POST /api/competitors?action=oembed
 *
 * Get oEmbed preview for a Threads URL.
 */

import { apiError, apiSuccess } from "../../../apiResponse.js";
import { withRetry } from "../../../retryUtils.js";
import { CompetitorOembedSchema } from "../../../validation.js";
import { withAuthAndBody } from "../../helpers/withAuthAndBody.js";

export const handleOembed = withAuthAndBody(
	CompetitorOembedSchema,
	async (_user, parsed, _req, res) => {
		const { url } = parsed;

		try {
			const response = await withRetry(
				() =>
					fetch(
						`https://www.threads.net/api/oembed?url=${encodeURIComponent(url)}`,
						{ signal: AbortSignal.timeout(10000) },
					),
				{ label: "competitorOembed" },
			);
			if (!response.ok) throw new Error("Failed to fetch oEmbed");
			const data = await response.json();
			return apiSuccess(res, { embed: data });
		} catch (_error: unknown) {
			return apiError(res, 500, "Failed to fetch oEmbed preview");
		}
	},
);
