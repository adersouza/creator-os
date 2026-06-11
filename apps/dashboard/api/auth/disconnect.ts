/**
 * Per-account disconnect endpoint.
 *
 * POST /api/auth/disconnect
 * Body: { accountId: string, platform: "threads" | "instagram" }
 *
 * Steps:
 *   1. Verify caller owns the account.
 *   2. Decrypt the stored token.
 *   3. Call Meta's `DELETE /me/permissions` so the user's grant is revoked
 *      at Meta as well — not just removed from our DB.
 *   4. Null out the encrypted-token column and mark the account inactive.
 *
 * Failures at the Meta-revoke step are logged but do not block local
 * cleanup: the user's intent is "disconnect", so we always finish the
 * DB-side teardown.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { createDbContext } from "../_lib/dbContext.js";
import { decrypt } from "../_lib/encryption.js";
import { logger } from "../_lib/logger.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import {
	enforceRouteRateLimit,
	getClientIp,
} from "../_lib/routeRateLimit.js";
import { z, zEnum } from "../_lib/zodCompat.js";

const Body = z.object({
	accountId: z.string().min(1),
	platform: zEnum(["threads", "instagram"]),
});

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

	const ipAllowed = await enforceRouteRateLimit(res, {
		key: `auth-ip:disconnect:ip:${getClientIp(req)}:minute`,
		limit: 5,
		windowSeconds: 60,
		failMode: "closed",
		message: "Too many auth requests. Try again shortly.",
	});
	if (!ipAllowed) return;

	const authHeader = req.headers.authorization;
	if (!authHeader?.startsWith("Bearer ")) {
		return apiError(res, 401, "Missing or invalid authorization header");
	}
	const token = authHeader.slice("Bearer ".length);

	const {
		data: { user },
		error: authErr,
	} = await getPrivilegedSupabase(
		PRIVILEGED_DB_REASONS.accountDisconnectAuth,
	).auth.getUser(token);
	if (authErr || !user) return apiError(res, 401, "Invalid or expired token");

	const parsed = Body.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			parsed.error.issues[0]?.message || "Invalid input",
		);
	}
	const { accountId, platform } = parsed.data;

	const { userDb } = createDbContext(req, {
		id: user.id,
		email: user.email ?? undefined,
	});
	// The table and encrypted-token column are selected from the validated
	// platform enum above; generated Supabase types cannot narrow that dynamic pair.
	// biome-ignore lint/suspicious/noExplicitAny: validated dynamic account table/column pair
	const db = userDb as any;
	const table = platform === "threads" ? "accounts" : "instagram_accounts";
	const tokenField =
		platform === "threads"
			? "threads_access_token_encrypted"
			: "instagram_access_token_encrypted";
	const revokeHost =
		platform === "threads" ? "graph.threads.net/v1.0" : "graph.facebook.com/v25.0";

	// 1. Ownership check + token fetch
	const { data: row, error: readErr } = await db
		.from(table)
		.select(`id, user_id, ${tokenField}`)
		.eq("id", accountId)
		.eq("user_id", user.id)
		.maybeSingle();

	if (readErr) {
		logger.error("[auth/disconnect] failed to load account", {
			error: String(readErr),
		});
		return apiError(res, 500, "Failed to load account");
	}
	if (!row) return apiError(res, 404, "Account not found");

	const encryptedToken = (row as Record<string, unknown>)[tokenField] as
		| string
		| null;

	// 2. Best-effort Meta revoke
	if (encryptedToken) {
		try {
			const plaintext = decrypt(encryptedToken);
			await fetch(
				`https://${revokeHost}/me/permissions?access_token=${encodeURIComponent(plaintext)}`,
				{
					method: "DELETE",
					signal: AbortSignal.timeout(15000),
					redirect: "manual",
				},
			);
		} catch (err) {
			logger.warn("[auth/disconnect] Meta revoke failed (non-blocking)", {
				accountId,
				platform,
				error: String(err),
			});
		}
	}

	// 3. Local teardown — null token, mark inactive
	const updatePayload: Record<string, unknown> = {
		[tokenField]: null,
		is_active: false,
		status: "disconnected",
		updated_at: new Date().toISOString(),
	};

	const { error: updateErr } = await db
		.from(table)
		.update(updatePayload)
		.eq("id", accountId)
		.eq("user_id", user.id);

	if (updateErr) {
		logger.error("[auth/disconnect] failed to clear token", {
			accountId,
			platform,
			error: String(updateErr),
		});
		return apiError(res, 500, "Failed to disconnect account");
	}

	return apiSuccess(res, { disconnected: true });
}
