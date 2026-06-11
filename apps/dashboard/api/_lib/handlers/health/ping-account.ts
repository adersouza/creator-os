import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, methodNotAllowed } from "../../apiResponse.js";
import { pingAccountHealth } from "../../accountHealthSignals.js";
import { withAuth } from "../../middleware.js";

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") return methodNotAllowed(res);
		const body =
			typeof req.body === "object" && req.body !== null
				? (req.body as { accountId?: unknown | undefined; platform?: unknown | undefined })
				: {};
		const accountId = typeof body.accountId === "string" ? body.accountId : "";
		if (!accountId) return apiError(res, 400, "accountId is required");
		const platform =
			body.platform === "instagram" || body.platform === "threads"
				? body.platform
				: undefined;
		const result = await pingAccountHealth({
			userId: user.id,
			accountId,
			platform,
		});
		return apiSuccess(res, result);
	},
);
