// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Meta Data Deletion Callback
 * POST /api/meta/data-deletion
 *
 * Called by Meta when a user requests data deletion through their Meta settings.
 * Per Meta Platform Terms, must respond with a status check URL.
 *
 * Flow:
 *   1. Verify signed request (HMAC-SHA256)
 *   2. Clear tokens + mark accounts as deletion_requested
 *   3. Store request in data_deletion_requests (with confirmation_code)
 *   4. Dispatch QStash job to cascade-delete all user data
 *   5. Return verification URL for Meta
 */

import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { logger } from "../_lib/logger.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { enforceRouteRateLimit, getClientIp } from "../_lib/routeRateLimit.js";

const APP_BASE_URL =
	process.env.APP_URL ||
	(process.env.VERCEL_URL
		? `https://${process.env.VERCEL_URL}`
		: "https://juno33.com");

function parseSignedRequest(
	signedRequest: string,
	appSecret: string,
): Record<string, unknown> | null {
	try {
		const [sig, payload] = signedRequest.split(".");
		const expectedSig = crypto
			.createHmac("sha256", appSecret)
			.update(payload!)
			.digest("base64url");
		const sigBuf = Buffer.from(sig!, "utf-8");
		const expectedBuf = Buffer.from(expectedSig, "utf-8");
		if (
			sigBuf.length !== expectedBuf.length ||
			!crypto.timingSafeEqual(sigBuf, expectedBuf)
		)
			return null;
		return JSON.parse(Buffer.from(payload!, "base64url").toString("utf-8"));
	} catch {
		return null;
	}
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const allowed = await enforceRouteRateLimit(res, {
		key: `meta-deletion:${getClientIp(req)}`,
		limit: 10,
		windowSeconds: 60,
		failMode: "closed",
		message: "Too many requests",
	});
	if (!allowed) return;

	const appSecret = process.env.META_APP_SECRET;
	if (!appSecret) {
		logger.error("[meta/data-deletion] META_APP_SECRET not configured");
		return apiError(res, 500, "Server misconfigured");
	}

	const signedRequest = req.body?.signed_request;
	if (!signedRequest) {
		return apiError(res, 400, "Missing signed_request");
	}

	const data = parseSignedRequest(signedRequest, appSecret);
	if (!data?.user_id) {
		return apiError(res, 400, "Invalid signed_request");
	}

	const metaUserId = String(data.user_id);
	const confirmationCode = crypto.randomUUID();

	try {
		const supabase = getPrivilegedSupabase(
			PRIVILEGED_DB_REASONS.metaDataDeletionCallback,
		);

		// Clear tokens and mark accounts for deletion
		await supabase
			.from("accounts")
			.update({
				status: "deletion_requested",
				threads_access_token_encrypted: null as unknown as string,
			})
			.eq("threads_user_id", metaUserId);

		await supabase
			.from("instagram_accounts")
			.update({
				status: "deletion_requested",
				instagram_access_token_encrypted: null,
			})
			.eq("instagram_user_id", metaUserId);

		// Resolve our user_id from accounts or instagram_accounts
		let resolvedUserId: string | null = null;

		const { data: threadAcct } = await supabase
			.from("accounts")
			.select("user_id")
			.eq("threads_user_id", metaUserId)
			.limit(1)
			.maybeSingle();
		if (threadAcct?.user_id) {
			resolvedUserId = threadAcct.user_id;
		} else {
			const { data: igAcct } = await supabase
				.from("instagram_accounts")
				.select("user_id")
				.eq("instagram_user_id", metaUserId)
				.limit(1)
				.maybeSingle();
			if (igAcct?.user_id) {
				resolvedUserId = igAcct.user_id;
			}
		}

		// Store the deletion request with confirmation code
		// biome-ignore lint/suspicious/noExplicitAny: table not in generated types
		await (supabase as any).from("data_deletion_requests").insert({
			confirmation_code: confirmationCode,
			meta_user_id: metaUserId,
			user_id: resolvedUserId,
			status: resolvedUserId ? "pending" : "no_data_found",
		});

		// If we found a user, dispatch cascade deletion via QStash
		if (resolvedUserId) {
			try {
				const { Client } = await import("@upstash/qstash");
				const { RETRIES, getFailureCallbackUrl } = await import(
					"../_lib/qstashDefaults.js"
				);
				const qstash = new Client({
					token: process.env.QSTASH_TOKEN || "",
				});
				await qstash.publishJSON({
					url: `${APP_BASE_URL}/api/meta/process-deletion`,
					body: {
						confirmationCode,
						userId: resolvedUserId,
						metaUserId,
					},
					retries: RETRIES.CRITICAL,
					failureCallback: getFailureCallbackUrl(),
				});
			} catch (qErr) {
				logger.error("[meta/data-deletion] QStash dispatch failed", {
					metaUserId,
					error: String(qErr),
				});
				// Don't fail the Meta callback — request is stored, can be retried
			}
		}

		logger.info("[meta/data-deletion] Deletion requested", {
			metaUserId,
			confirmationCode,
			resolvedUserId,
		});
	} catch (err) {
		logger.error("[meta/data-deletion] Error processing", {
			error: String(err),
		});
	}

	// Meta requires a JSON response with a status check URL and confirmation code
	return apiSuccess(res, {
		url: `${APP_BASE_URL}/data-deletion?code=${confirmationCode}`,
		confirmation_code: confirmationCode,
	});
}
