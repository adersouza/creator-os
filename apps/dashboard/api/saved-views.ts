/**
 * Saved Views — personal-scope named filter presets for the Analytics page.
 *
 *   GET  /api/saved-views               list current user's views
 *   POST /api/saved-views               create { name, filters, scope? }
 *   DELETE /api/saved-views?id=UUID     delete one
 *
 * Rate-limited. Filters are opaque JSONB — the frontend owns the shape, this
 * endpoint just round-trips it.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { Json } from "../types/supabase.js";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import type { DbContext } from "./_lib/dbContext.js";
import { withAuthDb } from "./_lib/middleware.js";
import { enforceRouteRateLimit } from "./_lib/routeRateLimit.js";

const MAX_NAME_LEN = 80;
const MAX_FILTERS_BYTES = 8_000;
const VALID_SCOPES = new Set(["analytics"]);

interface SavedViewRow {
	id: string;
	user_id: string;
	name: string;
	scope: string;
	filters: Record<string, unknown>;
	created_at: string;
	updated_at: string;
}

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context) => {
		const { user } = context;
		const isWrite = req.method === "POST" || req.method === "DELETE";
		const allowed = await enforceRouteRateLimit(res, {
			key: `saved-views-${isWrite ? "write" : "read"}:${user.id}`,
			limit: 60,
			windowSeconds: 60,
			failMode: isWrite ? "closed" : "open",
			message: "Rate limit exceeded",
		});
		if (!allowed) return;

		switch (req.method) {
			case "GET":
				return listViews(req, res, context);
			case "POST":
				return createView(req, res, context);
			case "DELETE":
				return deleteView(req, res, context);
			default:
				res.setHeader("Allow", "GET, POST, DELETE");
				return apiError(res, 405, "Method not allowed");
		}
	},
);

async function listViews(
	req: VercelRequest,
	res: VercelResponse,
	context: DbContext,
) {
	const { user, userDb } = context;
	const scope =
		typeof req.query.scope === "string" && VALID_SCOPES.has(req.query.scope)
			? (req.query.scope as string)
			: "analytics";

	const { data, error } = await userDb
		.from("saved_views")
		.select("id, user_id, name, scope, filters, created_at, updated_at")
		.eq("user_id", user.id)
		.eq("scope", scope)
		.order("updated_at", { ascending: false })
		.limit(50);

	if (error) {
		return apiError(res, 500, "Failed to fetch saved views", {
			details: error.message,
		});
	}
	return apiSuccess(res, { views: (data ?? []) as SavedViewRow[] });
}

async function createView(
	req: VercelRequest,
	res: VercelResponse,
	context: DbContext,
) {
	const { user, userDb } = context;
	const body = (req.body ?? {}) as {
		name?: unknown | undefined;
		filters?: unknown | undefined;
		scope?: unknown | undefined;
	};

	const name = typeof body.name === "string" ? body.name.trim() : "";
	if (!name || name.length > MAX_NAME_LEN) {
		return apiError(
			res,
			400,
			`name is required (1–${MAX_NAME_LEN} chars)`,
		);
	}

	const filters = body.filters;
	if (
		filters === null ||
		typeof filters !== "object" ||
		Array.isArray(filters)
	) {
		return apiError(res, 400, "filters must be a JSON object");
	}
	const filtersStr = JSON.stringify(filters);
	if (filtersStr.length > MAX_FILTERS_BYTES) {
		return apiError(res, 400, "filters payload too large");
	}

	const scope =
		typeof body.scope === "string" && VALID_SCOPES.has(body.scope)
			? (body.scope as string)
			: "analytics";

	const { data, error } = await userDb
		.from("saved_views")
		.insert({
			user_id: user.id,
			name,
			filters: filters as Json,
			scope,
		})
		.select("id, user_id, name, scope, filters, created_at, updated_at")
		.single();

	if (error) {
		return apiError(res, 500, "Failed to create saved view", {
			details: error.message,
		});
	}
	return apiSuccess(res, { view: data as SavedViewRow });
}

async function deleteView(
	req: VercelRequest,
	res: VercelResponse,
	context: DbContext,
) {
	const { user, userDb } = context;
	const id = typeof req.query.id === "string" ? req.query.id : "";
	if (!id) return apiError(res, 400, "id query param is required");

	const { error } = await userDb
		.from("saved_views")
		.delete()
		.eq("user_id", user.id)
		.eq("id", id);

	if (error) {
		return apiError(res, 500, "Failed to delete saved view", {
			details: error.message,
		});
	}
	return apiSuccess(res, { deleted: id });
}
