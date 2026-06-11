/**
 * Comment Repair
 * Daily repair for missed IG comment webhooks. For each active IG account,
 * fetches comments on recent posts (7 days) and upserts into ig_comments.
 */

import type { Logger, TypedSupabaseClient } from "./shared.js";

export async function phaseCommentRepair(
	supabase: TypedSupabaseClient,
	_logger: Logger,
	startTime: number,
): Promise<{ accounts: number; comments: number }> {
	const MAX_ACCOUNTS = 30;
	const MAX_PHASE_MS = 15_000;
	const SEVEN_DAYS_AGO = new Date(
		Date.now() - 7 * 24 * 60 * 60 * 1000,
	).toISOString();

	// Get active IG accounts
	// biome-ignore lint/suspicious/noExplicitAny: login_type not in generated types
	const { data: accounts } = await (supabase as any)
		.from("instagram_accounts")
		.select("id, user_id, instagram_access_token_encrypted, login_type")
		.eq("is_active", true)
		.or("needs_reauth.is.null,needs_reauth.eq.false")
		.not("instagram_access_token_encrypted", "is", null)
		.limit(MAX_ACCOUNTS);

	if (!accounts || accounts.length === 0) {
		return { accounts: 0, comments: 0 };
	}

	const { getMediaComments } = await import("../../instagramApi.js");

	let totalAccounts = 0;
	let totalComments = 0;

	for (const account of accounts) {
		if (Date.now() - startTime > MAX_PHASE_MS) break;

		try {
			if (!account.instagram_access_token_encrypted) {
				_logger.warn("[comment-repair] Skipping account without token", {
					accountId: account.id,
				});
				continue;
			}

			// Get recent posts (7 days) that have IG post IDs
			const { data: posts } = await supabase
				.from("posts")
				.select("id, instagram_post_id")
				.eq("user_id", account.user_id)
				.eq("platform", "instagram")
				.not("instagram_post_id", "is", null)
				.gte("created_at", SEVEN_DAYS_AGO)
				.limit(20);

			if (!posts || posts.length === 0) continue;

			for (const post of posts) {
				if (Date.now() - startTime > MAX_PHASE_MS) break;

				const result = await getMediaComments(
					account.instagram_access_token_encrypted as string,
					post.instagram_post_id as string,
					undefined,
					account.login_type || "instagram",
				);

				if (result.success && (result.comments?.length ?? 0) > 0) {
					const rows = (result.comments || []).map((c) => ({
						comment_id: c.id,
						post_id: post.id,
						media_id: post.instagram_post_id,
						text: c.text || "",
						username: c.from?.username || c.username || "unknown",
						ig_user_id: c.from?.id || "",
						like_count: c.like_count || 0,
						parent_comment_id: c.parent_id || null,
						created_at: c.timestamp || new Date().toISOString(),
					}));

					// biome-ignore lint/suspicious/noExplicitAny: ig_comments new columns not in generated types yet
					await (supabase as any)
						.from("ig_comments")
						.upsert(rows, { onConflict: "comment_id" });

					totalComments += rows.length;
				}
			}
			totalAccounts++;
		} catch (err) {
			_logger.warn("[comment-repair] Failed for account", {
				accountId: account.id,
				error: String(err),
			});
		}
	}

	return { accounts: totalAccounts, comments: totalComments };
}
