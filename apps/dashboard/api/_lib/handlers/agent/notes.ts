/**
 * Agent Notes CRUD
 *
 * GET  /api/agent/notes  — list notes (?accountGroupId optional filter)
 * POST /api/agent/notes  — upsert or delete a note
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { withAuthDb } from "../../middleware.js";

type UserDb = DbContext["userDb"];

async function verifyOwnedGroup(
	userDb: UserDb,
	userId: string,
	accountGroupId: string,
): Promise<boolean> {
	const { data } = await userDb
		.from("account_groups")
		.select("id")
		.eq("id", accountGroupId)
		.eq("user_id", userId)
		.maybeSingle();
	return !!data;
}

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, { user, userDb }) => {
		const userId = user.id;

		if (req.method === "GET") {
			const accountGroupId = req.query.accountGroupId as string | undefined;
			if (
				accountGroupId &&
				!(await verifyOwnedGroup(userDb, userId, accountGroupId))
			) {
				return apiError(res, 404, "Account group not found");
			}

			let query = userDb
				.from("agent_notes")
				.select("*")
				.eq("user_id", userId)
				.order("updated_at", { ascending: false });

			if (accountGroupId) {
				query = query.eq("account_group_id", accountGroupId);
			}

			const { data, error } = await query;
			if (error)
				return apiError(res, 500, "Failed to fetch notes", {
					details: error.message,
				});

			return apiSuccess(res, { notes: data ?? [] });
		}

		if (req.method === "POST") {
			const { action, key, value, accountGroupId } = req.body ?? {};

			if (!action || !["upsert", "delete"].includes(action)) {
				return apiError(res, 400, "action must be 'upsert' or 'delete'");
			}
			if (!key || typeof key !== "string") {
				return apiError(res, 400, "key is required");
			}
			if (key.length > 200) {
				return apiError(res, 400, "key must be at most 200 characters");
			}
			if (
				accountGroupId &&
				(typeof accountGroupId !== "string" ||
					!(await verifyOwnedGroup(userDb, userId, accountGroupId)))
			) {
				return apiError(res, 404, "Account group not found");
			}

			if (action === "upsert") {
				if (value === undefined || value === null) {
					return apiError(res, 400, "value is required for upsert");
				}
				const valStr = String(value);
				if (valStr.length > 5000) {
					return apiError(res, 400, "value must be at most 5000 characters");
				}

				let findQuery = userDb
					.from("agent_notes")
					.select("id")
					.eq("user_id", userId)
					.eq("key", key);

				if (accountGroupId) {
					findQuery = findQuery.eq("account_group_id", accountGroupId);
				} else {
					findQuery = findQuery.is("account_group_id", null);
				}

				const { data: existing } = await findQuery.maybeSingle();

				if (existing) {
					const { error } = await userDb
						.from("agent_notes")
						.update({ value: valStr, updated_at: new Date().toISOString() })
						.eq("id", existing.id);

					if (error)
						return apiError(res, 500, "Failed to update note", {
							details: error.message,
						});
					return apiSuccess(res, { action: "updated", key });
				}

				const { error } = await userDb
					.from("agent_notes")
					.insert({
						user_id: userId,
						key,
						value: valStr,
						account_group_id: accountGroupId ?? null,
					});

				if (error)
					return apiError(res, 500, "Failed to create note", {
						details: error.message,
					});
				return apiSuccess(res, { action: "created", key });
			}

			// action === "delete"
			let delQuery = userDb
				.from("agent_notes")
				.delete()
				.eq("user_id", userId)
				.eq("key", key)
				.select("id");

			if (accountGroupId) {
				delQuery = delQuery.eq("account_group_id", accountGroupId);
			} else {
				delQuery = delQuery.is("account_group_id", null);
			}

			const { data, error } = await delQuery.maybeSingle();
			if (error)
				return apiError(res, 500, "Failed to delete note", {
					details: error.message,
				});
			if (!data) return apiError(res, 404, "Note not found");

			return apiSuccess(res, { action: "deleted", key });
		}

		return apiError(res, 405, "Method not allowed");
	},
);
