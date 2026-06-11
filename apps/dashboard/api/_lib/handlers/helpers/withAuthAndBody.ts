/**
 * Middleware Wrappers for Auth + Validation
 *
 * Eliminates the repeated pattern:
 *   const user = await getAuthUserOrError(req, res);
 *   if (!user) return;
 *   const parsed = parseBodyOrError(res, SomeSchema, req.body);
 *   if (!parsed) return;
 *
 * Usage:
 *   import { withAuthAndBody, withAuthOnly, withAuthAndQuery } from "./helpers/withAuthAndBody.js";
 *
 *   export const handleCreate = withAuthAndBody(CreateSchema, async (user, body, req, res) => {
 *     // body is typed as z.infer<typeof CreateSchema>
 *   });
 *
 *   export const handleList = withAuthOnly(async (user, req, res) => { ... });
 *
 *   export const handleGet = withAuthAndQuery(GetSchema, async (user, query, req, res) => { ... });
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getAuthUserOrError } from "../../apiResponse.js";
import { parseBodyOrError, parseQueryOrError } from "../../validation.js";
import type { ZodSchema } from "../../zodCompat.js";

export interface AuthUser {
	id: string;
	email?: string | undefined;
}

/**
 * Auth + Zod body parsing wrapper.
 * Returns a handler function compatible with direct invocation from router files.
 */
export function withAuthAndBody<T>(
	schema: ZodSchema<T>,
	handler: (
		user: AuthUser,
		body: T,
		req: VercelRequest,
		res: VercelResponse,
	) => Promise<VercelResponse | undefined>,
) {
	return async (req: VercelRequest, res: VercelResponse) => {
		const user = await getAuthUserOrError(req, res);
		if (!user) return;

		const parsed = parseBodyOrError(res, schema, req.body);
		if (!parsed) return;

		return handler(user, parsed, req, res);
	};
}

/**
 * Auth-only wrapper (no body/query parsing).
 */
export function withAuthOnly(
	handler: (
		user: AuthUser,
		req: VercelRequest,
		res: VercelResponse,
	) => Promise<VercelResponse | undefined>,
) {
	return async (req: VercelRequest, res: VercelResponse) => {
		const user = await getAuthUserOrError(req, res);
		if (!user) return;

		return handler(user, req, res);
	};
}

/**
 * Auth + Zod query parsing wrapper (for GET handlers).
 */
export function withAuthAndQuery<T>(
	schema: ZodSchema<T>,
	handler: (
		user: AuthUser,
		query: T,
		req: VercelRequest,
		res: VercelResponse,
	) => Promise<VercelResponse | undefined>,
) {
	return async (req: VercelRequest, res: VercelResponse) => {
		const user = await getAuthUserOrError(req, res);
		if (!user) return;

		const parsed = parseQueryOrError(res, schema, req.query);
		if (!parsed) return;

		return handler(user, parsed, req, res);
	};
}
