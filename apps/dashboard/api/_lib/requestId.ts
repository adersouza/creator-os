/**
 * Request ID Middleware
 *
 * Generates a UUID for each request, adds it to response headers,
 * and makes it available for structured logging.
 */

import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";

const REQUEST_ID_HEADER = "x-request-id";

/**
 * Generate a request ID from the incoming header or create a new one.
 * Adds the ID to the response headers.
 */
export function getOrCreateRequestId(
	req: VercelRequest,
	res: VercelResponse,
): string {
	const existing = req.headers[REQUEST_ID_HEADER];
	// #707: Validate incoming request ID format (UUID-like, max 64 chars)
	const isValid =
		typeof existing === "string" &&
		existing.length > 0 &&
		existing.length <= 64 &&
		/^[\w-]+$/.test(existing);
	const requestId = isValid ? existing : crypto.randomUUID();
	res.setHeader(REQUEST_ID_HEADER, requestId);
	return requestId;
}
