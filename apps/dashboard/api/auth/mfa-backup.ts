// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * TOTP backup codes endpoint.
 *
 * POST /api/auth/mfa-backup?action=generate  — requires AAL2. Invalidates
 *   any existing codes and returns 10 freshly-generated plaintext codes.
 *   Plaintext is shown to the user exactly once; we only store hashes.
 *
 * POST /api/auth/mfa-backup?action=verify    — takes `{ code }`. Matches
 *   against the user's unused hashes, marks the matched row used, and
 *   deletes the verified TOTP factor via the admin API. With the factor
 *   gone, `nextLevel` drops to aal1 and the client can proceed without
 *   a TOTP challenge. The user should re-enroll at next opportunity.
 *
 * GET  /api/auth/mfa-backup?action=count     — returns unused code count
 *   for the Settings UI badge.
 *
 * Why server-side: Supabase TOTP does not support recovery codes natively;
 * there is no anon-key path to mark a session AAL2 without the original
 * authenticator. Deleting the factor (service role) is the sanctioned
 * workaround. The endpoint requires a valid AAL1 session so the backup
 * code alone can't unlock an account — the attacker would also need the
 * password (already proven when the AAL1 session was minted).
 */

import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { logger } from "../_lib/logger.js";
import { withAuth } from "../_lib/middleware.js";
import {
	getPrivilegedSupabase,
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { checkRateLimit } from "../_lib/rateLimiter.js";

const BACKUP_CODE_COUNT = 10;
const SCRYPT_KEYLEN = 32;
const SCRYPT_COST = { N: 16384, r: 8, p: 1, maxmem: 64 * 1024 * 1024 };

function decodeJwtClaims(token: string): { aal?: string | undefined } | null {
	try {
		const parts = token.split(".");
		if (parts.length !== 3) return null;
		const payload = Buffer.from(parts[1]!, "base64url").toString("utf8");
		return JSON.parse(payload);
	} catch {
		return null;
	}
}

// 12 hex chars in groups of 4 for readability — e.g. "a1b2-c3d4-e5f6".
// 48 bits of entropy; with scrypt-hashed storage + one-shot per code,
// brute-force is infeasible within session windows.
function generateCode(): string {
	const hex = randomBytes(6).toString("hex");
	return `${hex.slice(0, 4)}-${hex.slice(4, 8)}-${hex.slice(8, 12)}`;
}

function normalizeCode(input: string): string {
	return input.trim().toLowerCase().replace(/[\s-]/g, "");
}

function hashCode(normalized: string): { salt: string; digest: string } {
	const salt = randomBytes(16).toString("hex");
	const digest = scryptSync(
		normalized,
		salt,
		SCRYPT_KEYLEN,
		SCRYPT_COST,
	).toString("hex");
	return { salt, digest };
}

function formatStoredHash(salt: string, digest: string): string {
	return `scrypt$16384$8$1$${salt}$${digest}`;
}

function verifyHash(input: string, stored: string): boolean {
	const parts = stored.split("$");
	if (parts.length !== 6 || parts[0] !== "scrypt") return false;
	const salt = parts[4];
	const expected = parts[5];
		const derived = scryptSync(
			input,
			salt!,
			SCRYPT_KEYLEN,
			SCRYPT_COST,
	).toString("hex");
	if (expected!.length !== derived.length) return false;
	return timingSafeEqual(Buffer.from(expected!, "hex"), Buffer.from(derived, "hex"));
}

export default withAuth(async (req, res, user) => {
	const userId = user.id;
	const action = (req.query.action as string) || "";

	// Per-action rate limit. `generate` and `verify` are destructive/auth-adjacent
	// so they fail-closed on redis outage; `count` is read-only.
	const limits: Record<
		string,
		{ limit: number; windowSeconds: number; failMode: "open" | "closed" }
	> = {
		generate: { limit: 5, windowSeconds: 300, failMode: "closed" },
		verify: { limit: 10, windowSeconds: 60, failMode: "closed" },
		count: { limit: 60, windowSeconds: 60, failMode: "open" },
	};
	const l = limits[action] ?? {
		limit: 10,
		windowSeconds: 60,
		failMode: "closed" as const,
	};
	const rl = await checkRateLimit({
		key: `mfa-backup:${action || "unknown"}:${userId}`,
		limit: l.limit,
		windowSeconds: l.windowSeconds,
		failMode: l.failMode,
	});
	if (!rl.allowed) {
		if (rl.retryAfterSeconds) {
			res.setHeader("Retry-After", String(rl.retryAfterSeconds));
		}
		return apiError(
			res,
			429,
			rl.reason === "redis_unavailable"
				? "Service temporarily unavailable. Please try again shortly."
				: `Too many ${action} requests. Please wait a moment.`,
		);
	}

	if (action === "count") {
		if (req.method !== "GET" && req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}
		const { count, error } = await getPrivilegedSupabaseAny(
			PRIVILEGED_DB_REASONS.mfaBackupRecovery,
		)
			.from("recovery_codes")
			.select("id", { count: "exact", head: true })
			.eq("user_id", userId)
			.is("used_at", null);
		if (error) {
			logger.error("Backup code count failed", { error: error.message });
			return apiError(res, 500, "Failed to count backup codes");
		}
		return apiSuccess(res, { unused: count ?? 0 });
	}

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	if (action === "generate") {
		// AAL2 gate: generating fresh codes is a high-trust operation. The
		// Settings UI only calls this right after a successful TOTP verify,
		// so the session should already be aal2.
		const token = req.headers.authorization?.slice(7) ?? "";
		const claims = decodeJwtClaims(token);
		if ((claims?.aal ?? "aal1") !== "aal2") {
			return apiError(
				res,
				403,
				"AAL2 required. Verify your authenticator before regenerating backup codes.",
				{ code: "MFA_STEP_UP_REQUIRED" },
			);
		}

		const plain: string[] = [];
		const rows: Array<{ user_id: string; code_hash: string }> = [];
		for (let i = 0; i < BACKUP_CODE_COUNT; i++) {
			const code = generateCode();
			const { salt, digest } = hashCode(normalizeCode(code));
			plain.push(code);
			rows.push({ user_id: userId, code_hash: formatStoredHash(salt, digest) });
		}

		const supabase = getPrivilegedSupabaseAny(
			PRIVILEGED_DB_REASONS.mfaBackupRecovery,
		);
		const { error: deleteErr } = await supabase
			.from("recovery_codes")
			.delete()
			.eq("user_id", userId);
		if (deleteErr) {
			logger.error("Backup code delete failed", { error: deleteErr.message });
			return apiError(res, 500, "Failed to rotate backup codes");
		}

		const { error: insertErr } = await supabase
			.from("recovery_codes")
			.insert(rows);
		if (insertErr) {
			logger.error("Backup code insert failed", { error: insertErr.message });
			return apiError(res, 500, "Failed to generate backup codes");
		}

		return apiSuccess(res, { codes: plain, count: plain.length });
	}

	if (action === "verify") {
		const { code } = (req.body as { code?: unknown | undefined }) || {};
		if (typeof code !== "string" || code.trim().length === 0) {
			return apiError(res, 400, "Missing backup code");
		}
		const normalized = normalizeCode(code);
		if (!/^[0-9a-f]{12}$/.test(normalized)) {
			return apiError(res, 400, "Invalid backup code format");
		}

		const supabase = getPrivilegedSupabaseAny(
			PRIVILEGED_DB_REASONS.mfaBackupRecovery,
		);
		const { data: rows, error: listErr } = await supabase
			.from("recovery_codes")
			.select("id, code_hash")
			.eq("user_id", userId)
			.is("used_at", null);
		if (listErr) {
			logger.error("Backup code lookup failed", { error: listErr.message });
			return apiError(res, 500, "Failed to verify backup code");
		}
		const candidates = (rows ?? []) as Array<{ id: string; code_hash: string }>;
		if (candidates.length === 0) {
			return apiError(res, 401, "No backup codes available", {
				code: "NO_BACKUP_CODES",
			});
		}

		let matchId: string | null = null;
		for (const row of candidates) {
			if (verifyHash(normalized, row.code_hash)) {
				matchId = row.id;
				break;
			}
		}

		if (!matchId) {
			return apiError(res, 401, "Invalid backup code", { code: "BACKUP_CODE_INVALID" });
		}

		// Atomically mark used — belt-and-suspenders against concurrent tabs.
		const { error: markErr } = await supabase
			.from("recovery_codes")
			.update({ used_at: new Date().toISOString() })
			.eq("id", matchId)
			.is("used_at", null);
		if (markErr) {
			logger.error("Backup code mark-used failed", { error: markErr.message });
			return apiError(res, 500, "Failed to consume backup code");
		}

		// Delete the verified TOTP factor so the client's AAL1 session is
		// sufficient. The user should re-enroll — Settings will prompt on
		// next load because needsMfa becomes false but hasVerified is false.
		const admin = getPrivilegedSupabase(
			PRIVILEGED_DB_REASONS.mfaBackupRecovery,
		);
		const { data: factorsData } = await admin.auth.admin.mfa.listFactors({
			userId,
		});
		const verified = (factorsData?.factors ?? []).find(
			(f) => f.status === "verified",
		);
		if (verified) {
			const { error: deleteFactorErr } = await admin.auth.admin.mfa.deleteFactor({
				userId,
				id: verified.id,
			});
			if (deleteFactorErr) {
				logger.error("MFA factor delete failed", {
					error: deleteFactorErr.message,
				});
				return apiError(res, 500, "Failed to clear authenticator factor");
			}
		}

		const { count } = await supabase
			.from("recovery_codes")
			.select("id", { count: "exact", head: true })
			.eq("user_id", userId)
			.is("used_at", null);

		return apiSuccess(res, { ok: true, unusedRemaining: count ?? 0 });
	}

	return apiError(res, 400, `Unknown action: ${action}`);
});
