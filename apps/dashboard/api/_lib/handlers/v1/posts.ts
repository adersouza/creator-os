// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Public API v1 — GET /api/v1/posts
 * List posts with metrics for the authenticated API key user.
 *
 * Pagination modes:
 *   1. Offset/limit: ?limit=50&offset=0  (capped at offset 10,000)
 *   2. Cursor-based: ?cursor=<id>&limit=50  (no offset cap, scales to any size)
 *
 * Query params: account_id, limit (max 100), offset, cursor, sort, order, status
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";
import { withApiKey } from "../../withApiKey.js";
import { verifyAnyAccountOwnership } from "../helpers/verifyOwnership.js";

interface AccountIdRow {
	id: string;
}

const POST_FIELDS =
	"id, account_id, instagram_account_id, platform, content, status, published_at, views_count, likes_count, replies_count, shares_count, viral_score, created_at";

export default withApiKey(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const db = getSupabase();
		const accountId = req.query.account_id as string;
		// #594: Validate account_id format (prevent injection via malformed IDs)
		if (
			accountId &&
			(typeof accountId !== "string" || accountId.length > 100)
		) {
			return apiError(res, 400, "Invalid account_id format");
		}
		const parsedLimit = parseInt(req.query.limit as string, 10);
		if (req.query.limit && Number.isNaN(parsedLimit))
			return apiError(res, 400, "Invalid limit");
		const limit = Math.min(100, Math.max(1, parsedLimit || 50));

		const cursor = req.query.cursor as string | undefined;
		const parsedOffset = parseInt(req.query.offset as string, 10);
		if (req.query.offset && Number.isNaN(parsedOffset))
			return apiError(res, 400, "Invalid offset");
		// #597: Cap offset to prevent DoS via large offset scans
		const offset = Math.min(10000, Math.max(0, parsedOffset || 0));

		const allowedSorts = [
			"created_at",
			"published_at",
			"views_count",
			"likes_count",
			"replies_count",
			"viral_score",
		];
		const sort = allowedSorts.includes(req.query.sort as string)
			? (req.query.sort as string)
			: "created_at";
		const order = (req.query.order as string) === "asc";

		const status = (req.query.status as string) || "published";

		// Verify account ownership
		if (accountId) {
			const owned = await verifyAnyAccountOwnership(res, accountId, user.id);
			if (!owned) return;
		}

		// Get user's account IDs for filtering (parallel)
		const [{ data: userAccounts }, { data: userIgAccounts }] =
			await Promise.all([
				db.from("accounts").select("id").eq("user_id", user.id),
				db.from("instagram_accounts").select("id").eq("user_id", user.id),
			]);

		const allAccountIds = [
			...(userAccounts || []).map((a: AccountIdRow) => a.id),
			...(userIgAccounts || []).map((a: AccountIdRow) => a.id),
		].filter((id) => !user.allowedAccountIds || user.allowedAccountIds.includes(id));

		if (!allAccountIds.length) {
			return apiSuccess(res, { posts: [], total: 0, hasMore: false });
		}

		const filterIds = accountId ? [accountId] : allAccountIds;
		const filterOrClause = `account_id.in.(${filterIds.join(",")}),instagram_account_id.in.(${filterIds.join(",")})`;

		// ====================================================================
		// Cursor-based pagination (no offset cap — scales to any result set)
		// ====================================================================
		if (cursor) {
			// Validate cursor format (must be a valid post ID, not injection)
			if (
				typeof cursor !== "string" ||
				cursor.length > 100 ||
				/[;'"\\]/.test(cursor)
			) {
				return apiError(res, 400, "Invalid cursor format");
			}

			// Fetch the cursor row to get its sort value
			const { data: cursorRow } = await db
				.from("posts")
				.select(
					"id, created_at, published_at, views_count, likes_count, replies_count, viral_score",
				)
				.eq("id", cursor)
				.eq("user_id", user.id)
				.maybeSingle();

			if (!cursorRow) {
				return apiError(
					res,
					400,
					"Invalid cursor — post not found or not owned",
				);
			}

			const cursorValue = cursorRow[sort as keyof typeof cursorRow];
			const comparator = order ? "gt" : "lt";

			// Query: fetch rows after the cursor in sort order
			let query = db
				.from("posts")
				.select(POST_FIELDS)
				.or(filterOrClause)
				.eq("user_id", user.id)
				[comparator](sort, cursorValue)
				.order(sort, { ascending: order })
				.limit(limit + 1); // Fetch 1 extra to detect hasMore

			if (status !== "all") {
				query = query.eq("status", status);
			}

			const { data: posts, error } = await query;
			if (error) {
				logger.error("[v1/posts] Cursor-based query failed", { error: String(error) });
				return apiError(res, 500, "Failed to load posts");
			}

			const items = posts || [];
			const hasMore = items.length > limit;
			const page = hasMore ? items.slice(0, limit) : items;
			const nextCursor =
				hasMore && page.length > 0 ? page[page.length - 1]!.id : null;

			return apiSuccess(res, {
				posts: page,
				hasMore,
				nextCursor,
			});
		}

		// ====================================================================
		// Offset-based pagination (legacy, capped at 10K)
		// ====================================================================
		let query = db
			.from("posts")
			.select(POST_FIELDS)
			.or(filterOrClause)
			.eq("user_id", user.id)
			.order(sort, { ascending: order })
			.range(offset, offset + limit - 1);

		if (status !== "all") {
			query = query.eq("status", status);
		}

		let countQuery = db
			.from("posts")
			.select("id", { count: "exact", head: true })
			.or(filterOrClause)
			.eq("user_id", user.id);

		if (status !== "all") {
			countQuery = countQuery.eq("status", status);
		}

		const [{ data: posts, error }, { count }] = await Promise.all([
			query,
			countQuery,
		]);

		if (error) {
			logger.error("[v1/posts] Offset-based query failed", { error: String(error) });
			return apiError(res, 500, "Failed to load posts");
		}

		return apiSuccess(res, {
			posts: posts || [],
			total: count || 0,
			hasMore: offset + limit < (count || 0),
		});
	},
	"read",
);
