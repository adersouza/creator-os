/**
 * Inbox DM Repair Sync
 * Lightweight daily repair for missed DM webhooks.
 * Only processes accounts that haven't had webhook activity in 24h.
 */

import type { Logger, TypedSupabaseClient } from "./shared.js";

export async function phaseInboxRepair(
	supabase: TypedSupabaseClient,
	_logger: Logger,
	startTime: number,
): Promise<{ synced: number; messages: number }> {
	const MAX_ACCOUNTS = 50;
	const MAX_PHASE_MS = 30_000; // 30s budget for this phase

	// Find IG accounts with stale DM sync (>24h since last sync or never synced)
	const staleThreshold = new Date(
		Date.now() - 24 * 60 * 60 * 1000,
	).toISOString();

	// biome-ignore lint/suspicious/noExplicitAny: last_dm_sync_at not in generated Supabase types yet
	const { data: staleAccounts } = await (supabase as any)
		.from("instagram_accounts")
		.select(
			"id, user_id, instagram_user_id, instagram_access_token_encrypted, login_type, last_dm_sync_at",
		)
		.eq("is_active", true)
		.or("needs_reauth.is.null,needs_reauth.eq.false")
		.or(`last_dm_sync_at.is.null,last_dm_sync_at.lt.${staleThreshold}`)
		.limit(MAX_ACCOUNTS);

	if (!staleAccounts || staleAccounts.length === 0) {
		return { synced: 0, messages: 0 };
	}

	const { getConversations, getConversationMessages } = await import(
		"../../instagramApi.js"
	);

	let totalSynced = 0;
	let totalMessages = 0;

	for (const account of staleAccounts) {
		// Check time budget
		if (Date.now() - startTime > MAX_PHASE_MS) break;

		if (
			!account.instagram_access_token_encrypted ||
			!account.instagram_user_id
		) {
			continue;
		}

		try {
			const loginType = account.login_type || "instagram";

			// Fetch 1 page of conversations (lightweight repair)
			const convResult = await getConversations(
				account.instagram_access_token_encrypted,
				account.instagram_user_id,
				undefined,
				loginType,
			);

			if (!convResult.success || !convResult.conversations?.length) {
				// Update sync timestamp even if no conversations — avoids re-checking
				// biome-ignore lint/suspicious/noExplicitAny: Supabase type depth
				await (supabase as any)
					.from("instagram_accounts")
					.update({ last_dm_sync_at: new Date().toISOString() })
					.eq("id", account.id);
				continue;
			}

			// Upsert conversation summaries
			// biome-ignore lint/suspicious/noExplicitAny: Meta API conversation shape
			const cacheRows = convResult.conversations.map((conv: any) => {
				const participants = conv.participants?.data || [];
				const msgs = conv.messages?.data || [];
				const lastMsg = msgs[0];
				return {
					id: conv.id,
					user_id: account.user_id,
					account_id: account.id,
					participant_id: participants[0]?.id || "",
					participant_username: participants[0]?.username || "Unknown",
					last_message_text: lastMsg?.is_unsupported
						? "(Unsupported message type)"
						: lastMsg?.message || "(no messages)",
					last_message_at:
						conv.updated_time ||
						lastMsg?.created_time ||
						new Date().toISOString(),
					updated_at: new Date().toISOString(),
				};
			});

			// biome-ignore lint/suspicious/noExplicitAny: Supabase type depth
			await (supabase as any)
				.from("inbox_dm_cache")
				.upsert(cacheRows, { onConflict: "id" });

			// For conversations updated since last sync, fetch messages
			const lastSync = account.last_dm_sync_at
				? new Date(account.last_dm_sync_at).getTime()
				: 0;

			for (const conv of convResult.conversations) {
				if (Date.now() - startTime > MAX_PHASE_MS) break;

				const convUpdated = conv.updated_time
					? new Date(conv.updated_time).getTime()
					: Date.now();
				if (convUpdated <= lastSync) continue;

				const msgResult = await getConversationMessages(
					account.instagram_access_token_encrypted,
					conv.id,
					undefined,
					loginType,
				);

				if (msgResult.success && msgResult.messages?.length) {
					// biome-ignore lint/suspicious/noExplicitAny: Meta API message shape
					const msgRows = msgResult.messages.map((msg: any) => ({
						id: msg.id,
						conversation_id: conv.id,
						ig_account_id: account.id,
						user_id: account.user_id,
						sender_id: msg.from?.id || null,
						sender_username: msg.from?.username || msg.from?.name || null,
						message_text: msg.message || null,
						is_echo: msg.from?.id === account.instagram_user_id,
						created_at: msg.created_time || new Date().toISOString(),
					}));

					// biome-ignore lint/suspicious/noExplicitAny: Supabase type depth
					await (supabase as any)
						.from("inbox_dm_messages")
						.upsert(msgRows, { onConflict: "id" });
					totalMessages += msgRows.length;
				}
			}

			// Update sync timestamp
			// biome-ignore lint/suspicious/noExplicitAny: Supabase type depth
			await (supabase as any)
				.from("instagram_accounts")
				.update({ last_dm_sync_at: new Date().toISOString() })
				.eq("id", account.id);

			totalSynced++;
		} catch (err) {
			_logger.warn("[inbox-repair] Failed for account", {
				accountId: account.id,
				error: String(err),
			});
			// Continue with next account — don't fail the whole phase
		}
	}

	return { synced: totalSynced, messages: totalMessages };
}
