/**
 * GDPR Account Deletion — DELETE /api/user/delete
 * Permanently deletes all user data and the auth account.
 * Requires { confirmEmail: string } matching the user's email.
 *
 * Core cascade logic lives in deletionCascade.ts (shared with Meta-initiated deletion).
 * Cascade now handles: Postgres (67+ tables), Stripe customer, Supabase Storage, Redis keys.
 * This handler adds user-initiated-only extras: email confirm, IG webhook unsub, Meta token revocation.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logAudit } from "../../auditLog.js";
import { logger } from "../../logger.js";
import { requireStepUp, withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getSupabase } from "../../supabase.js";
import { cascadeDeleteUserData, deleteAuthUser } from "./deletionCascade.js";

export default withAuth(async (req, res, user) => {
	if (req.method !== "DELETE") return apiError(res, 405, "Method not allowed");

	// Deletion is permanent. If the user has MFA enrolled, force a fresh TOTP
	// challenge before the cascade runs — an AAL1 session alone (password)
	// shouldn't be enough to nuke an account.
	const stepUp = await requireStepUp(req, res, user.id);
	if (stepUp) return stepUp;

	// Rate limit account deletion: 3 requests/hour per user
	const rl = await checkRateLimit({
		key: `user-delete:${user.id}`,
		limit: 3,
		windowSeconds: 3600,
		failMode: "closed",
	});
	if (!rl.allowed) {
		return apiError(
			res,
			429,
			"Too many requests. Please wait before retrying.",
		);
	}

	const { confirmEmail } = req.body || {};
	if (!confirmEmail || confirmEmail !== user.email) {
		return apiError(res, 400, "Email confirmation does not match", {
			code: "EMAIL_MISMATCH",
		});
	}

	const supabase = getSupabase();
	const userId = user.id;

	try {
		// Log audit BEFORE deletion
		await logAudit(userId, "user.account_deletion", {
			metadata: { email: user.email, initiated_at: new Date().toISOString() },
			req,
		});

		// Unsubscribe IG accounts from webhooks (before token revocation)
		try {
			const { decrypt } = await import("../../encryption.js");
			const { data: igAccts } = await supabase
				.from("instagram_accounts")
				.select(
					"id, login_type, instagram_user_id, instagram_access_token_encrypted, facebook_page_id, facebook_page_access_token_encrypted",
				)
				.eq("user_id", userId);

			if (igAccts) {
				for (const ig of igAccts) {
					try {
						if (
							ig.login_type === "facebook" &&
							ig.facebook_page_id &&
							ig.facebook_page_access_token_encrypted
						) {
							const pageToken = decrypt(
								ig.facebook_page_access_token_encrypted,
							);
							await fetch(
								`https://graph.facebook.com/v25.0/${ig.facebook_page_id}/subscribed_apps?access_token=${pageToken}`,
								{ method: "DELETE", signal: AbortSignal.timeout(10000) },
							);
						} else if (
							ig.instagram_user_id &&
							ig.instagram_access_token_encrypted
						) {
							const igToken = decrypt(ig.instagram_access_token_encrypted);
							await fetch(
								`https://graph.instagram.com/${ig.instagram_user_id}/subscribed_apps?access_token=${igToken}`,
								{ method: "DELETE", signal: AbortSignal.timeout(10000) },
							);
						}
					} catch (err) {
						logger.debug(
							"[user/delete] IG webhook unsubscribe failed (non-blocking)",
							{
								accountId: ig.id,
								error: String(err),
							},
						);
					}
				}
			}
		} catch (_err) {
			logger.warn(
				"[user/delete] IG webhook unsubscription failed (non-blocking)",
				{ userId },
			);
		}

		// Attempt to revoke Meta tokens. Threads + Instagram are stored in
		// separate tables with separate encrypted-token columns. The previous
		// implementation queried nonexistent columns (`access_token`, `platform`)
		// on `accounts` and silently skipped revocation entirely.
		try {
			const { decrypt } = await import("../../encryption.js");

			const { data: threadsAccounts } = (await supabase
				.from("accounts")
				.select("threads_access_token_encrypted, threads_user_id")
				.eq("user_id", userId)) as unknown as {
				data: Array<{
					threads_access_token_encrypted: string | null;
					threads_user_id: string | null;
				}> | null;
			};

			for (const account of threadsAccounts ?? []) {
				if (!account.threads_access_token_encrypted) continue;
				try {
					const token = decrypt(account.threads_access_token_encrypted);
					await fetch(
						`https://graph.threads.net/v1.0/me/permissions?access_token=${encodeURIComponent(token)}`,
						{
							method: "DELETE",
							signal: AbortSignal.timeout(15000),
							redirect: "manual",
						},
					);
				} catch (err) {
					logger.debug(
						"[user/delete] Failed to revoke Threads permissions",
						{ error: String(err) },
					);
				}
			}

			const { data: igAccounts } = (await supabase
				.from("instagram_accounts")
				.select("instagram_access_token_encrypted")
				.eq("user_id", userId)) as unknown as {
				data: Array<{
					instagram_access_token_encrypted: string | null;
				}> | null;
			};

			for (const account of igAccounts ?? []) {
				if (!account.instagram_access_token_encrypted) continue;
				try {
					const token = decrypt(account.instagram_access_token_encrypted);
					await fetch(
						`https://graph.facebook.com/v25.0/me/permissions?access_token=${encodeURIComponent(token)}`,
						{
							method: "DELETE",
							signal: AbortSignal.timeout(15000),
							redirect: "manual",
						},
					);
				} catch (err) {
					logger.debug(
						"[user/delete] Failed to revoke IG permissions",
						{ error: String(err) },
					);
				}
			}
		} catch (_err) {
			logger.warn("[user/delete] Token revocation failed (non-blocking)", {
				userId,
			});
		}

		// ── Core cascade (shared with Meta-initiated deletion) ──
		await cascadeDeleteUserData(userId);

		// ── Delete auth user ──
		try {
			await deleteAuthUser(userId);
		} catch (_err) {
			return apiError(
				res,
				500,
				"Data deleted but auth account removal failed. Contact support.",
			);
		}

		return apiSuccess(res, {
			deleted: true,
			message: "Account permanently deleted",
		});
	} catch (error) {
		logger.error("[user/delete] Failed", { userId, error: String(error) });
		return apiError(res, 500, "Account deletion failed");
	}
});
