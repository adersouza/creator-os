/**
 * Collab Invite Refresh
 * Daily refresh of IG collaboration invites. Meta doesn't send collab
 * webhooks, so we cache API results.
 */

import type { Logger, TypedSupabaseClient } from "./shared.js";

export async function phaseCollabInviteRefresh(
	supabase: TypedSupabaseClient,
	_logger: Logger,
	startTime: number,
): Promise<{ refreshed: number; invites: number }> {
	const MAX_ACCOUNTS = 30;
	const MAX_PHASE_MS = 15_000;

	// Get active FB-login IG accounts (collabs require FB login)
	// biome-ignore lint/suspicious/noExplicitAny: login_type not in generated types
	const { data: accounts } = await (supabase as any)
		.from("instagram_accounts")
		.select(
			"id, user_id, instagram_user_id, instagram_access_token_encrypted, login_type",
		)
		.eq("is_active", true)
		.eq("login_type", "facebook")
		.or("needs_reauth.is.null,needs_reauth.eq.false")
		.limit(MAX_ACCOUNTS);

	if (!accounts || accounts.length === 0) {
		return { refreshed: 0, invites: 0 };
	}

	const { getCollaborationInvites } = await import("../../instagramApi.js");

	let totalRefreshed = 0;
	let totalInvites = 0;

	for (const account of accounts) {
		if (Date.now() - startTime > MAX_PHASE_MS) break;

		try {
			const result = await getCollaborationInvites(
				account.instagram_access_token_encrypted as string,
				account.instagram_user_id as string,
				account.login_type || "facebook",
			);

			if (result.success && (result.invites?.length ?? 0) > 0) {
				type CollabInviteRaw = {
					id?: string | undefined;
					caption?: string | undefined;
					media_type?: string | undefined;
					media_url?: string | undefined;
					permalink?: string | undefined;
					owner?: { id?: string | undefined; username?: string | undefined } | undefined;
				};
				const rows = (
					(result.invites || []) as unknown as CollabInviteRaw[]
				).map((inv) => ({
					id: inv.id,
					user_id: account.user_id,
					account_id: account.id,
					caption: inv.caption || null,
					media_type: inv.media_type || null,
					media_url: inv.media_url || null,
					permalink: inv.permalink || null,
					owner_id: inv.owner?.id || null,
					owner_username: inv.owner?.username || null,
					status: "pending",
					discovered_at: new Date().toISOString(),
				}));

				// biome-ignore lint/suspicious/noExplicitAny: ig_collab_invites not in generated types yet
				await (supabase as any)
					.from("ig_collab_invites")
					.upsert(rows, { onConflict: "id" });

				totalInvites += rows.length;
			}
			totalRefreshed++;
		} catch (err) {
			_logger.warn("[collab-refresh] Failed for account", {
				accountId: account.id,
				error: String(err),
			});
		}
	}

	return { refreshed: totalRefreshed, invites: totalInvites };
}
