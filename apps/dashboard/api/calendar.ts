/**
 * Calendar API Route — portfolio matrix and command parsing.
 */

import { apiError } from "./_lib/apiResponse.js";
import { handleParseCommand } from "./_lib/handlers/calendar/parse-command.js";
import { handlePortfolio } from "./_lib/handlers/calendar/portfolio.js";
import { withAuth } from "./_lib/middleware.js";

export default withAuth(async (req, res, user) => {
	const action = req.query.action as string | undefined;

	switch (action) {
		case "portfolio":
			return handlePortfolio(req, res, user.id);
		case "parse-command":
			return handleParseCommand(req, res, user.id);
		default:
			return apiError(res, 400, "Unknown calendar action");
	}
});
