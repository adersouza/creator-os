// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Import handler — CSV bulk import of posts.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { sanitizeHtml } from "../../sanitize.js";
import { ImportPostsSchema, parseBodyOrError } from "../../validation.js";
import {
	db,
	extractHashtags,
	normalizePostMediaType,
	type PostInsertData,
} from "./shared.js";

export async function handleImportPosts(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = parseBodyOrError(res, ImportPostsSchema, req.body);
	if (!parsed) return;

	const { posts: importRows, accountId: frontendAccountId } = parsed;

	// Resolve account_id: use provided accountId, or fall back to user's first account
	let resolvedAccountId: string | null = null;
	if (frontendAccountId && frontendAccountId !== "ALL") {
		const { data: ownedAccount, error: accountError } = await db()
			.from("accounts")
			.select("id")
			.eq("id", frontendAccountId)
			.eq("user_id", userId)
			.maybeSingle();
		if (accountError) {
			logger.error("Bulk import account verification error", {
				error: String(accountError),
			});
			return apiError(res, 500, "Failed to verify account");
		}
		if (!ownedAccount) return apiError(res, 404, "Account not found");
		resolvedAccountId = ownedAccount.id;
	} else {
		const { data: firstAccount } = await db()
			.from("accounts")
			.select("id")
			.eq("user_id", userId)
			.limit(1)
			.maybeSingle();
		resolvedAccountId = firstAccount?.id || null;
	}

	const imported: PostInsertData[] = [];
	const errors: { row: number; message: string }[] = [];

	for (let i = 0; i < importRows.length; i++) {
		const row = importRows[i];
		const platform = row!.platform || "threads";

		// Validate scheduled_for date if provided
		let scheduledFor: string | null = null;
		if (row!.scheduled_for) {
			const d = new Date(row!.scheduled_for);
			if (Number.isNaN(d.getTime())) {
				errors.push({
					row: i + 1,
					message: "Invalid date format for scheduled_for",
				});
				continue;
			}
			scheduledFor = d.toISOString();
		}

		const status = scheduledFor ? "scheduled" : "draft";
		const mediaUrls = row!.media_url ? [row!.media_url] : [];

		const insertData: PostInsertData = {
			user_id: userId,
			content: sanitizeHtml(row!.content.trim()),
			status,
			platform,
			media_urls: mediaUrls,
			media_type: normalizePostMediaType(
				mediaUrls.length > 0 ? "IMAGE" : "TEXT",
			),
			scheduled_for: scheduledFor,
		};

		// Assign account based on platform
		if (platform === "instagram") {
			// Try to find user's first instagram account
			const { data: igAccount } = await db()
				.from("instagram_accounts")
				.select("id")
				.eq("user_id", userId)
				.limit(1)
				.maybeSingle();
			insertData.instagram_account_id = igAccount?.id || null;
		} else {
			insertData.account_id = resolvedAccountId;
		}

		// Extract hashtags
		const hashtags = extractHashtags(row!.content);
		if (hashtags.length > 0) {
			insertData.hashtags = hashtags;
		}

		imported.push(insertData);
	}

	// Batch insert all valid posts
	if (imported.length > 0) {
		const { error: insertError } = await db().from("posts").insert(imported);

		if (insertError) {
			logger.error("Bulk import insert error", { error: String(insertError) });
			return apiError(
				res,
				500,
				"Failed to insert posts. Please check your data and try again.",
			);
		}
	}

	return apiSuccess(res, {
		imported: imported.length,
		errors,
	});
}
