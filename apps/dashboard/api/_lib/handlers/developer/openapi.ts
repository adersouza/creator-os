/**
 * OpenAPI Specification Endpoint
 * GET /api/openapi — Returns the OpenAPI 3.0 JSON spec
 * Requires API key with "read" scope.
 * Merged from api/openapi.ts
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { openApiSpec } from "../../openapi.js";
import { withApiKey } from "../../withApiKey.js";

export default withApiKey(async (req, res) => {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	res.setHeader("Content-Type", "application/json");
	return apiSuccess(res, openApiSpec as unknown as Record<string, unknown>);
}, "read");
