// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Meta Deauthorize Callback
 * POST /api/meta/deauthorize
 *
 * Called by Meta when a user removes the app from their account settings.
 * Per Meta Platform Terms, must respond with a confirmation URL.
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
		key: `meta-deauth:${getClientIp(req)}`,
		limit: 10,
		windowSeconds: 60,
		failMode: "closed",
		message: "Too many requests",
	});
	if (!allowed) return;

	const appSecret = process.env.META_APP_SECRET;
	if (!appSecret) {
		logger.error("[meta/deauthorize] META_APP_SECRET not configured");
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
			PRIVILEGED_DB_REASONS.metaDeauthorizeCallback,
		);

		// Mark Threads accounts as deauthorized
		await supabase
			.from("accounts")
			.update({
				status: "deauthorized",
				threads_access_token_encrypted: null as unknown as string,
			})
			.eq("threads_user_id", metaUserId);

		// Mark Instagram accounts as deauthorized
		await supabase
			.from("instagram_accounts")
			.update({
				status: "deauthorized",
				instagram_access_token_encrypted: null,
			})
			.eq("instagram_user_id", metaUserId);

		logger.info("[meta/deauthorize] User deauthorized", {
			metaUserId,
			confirmationCode,
		});
	} catch (err) {
		logger.error("[meta/deauthorize] Error processing", { error: String(err) });
	}

	// Meta requires a JSON response with a confirmation URL
	return apiSuccess(res, {
		url: `${APP_BASE_URL}/deauthorize?code=${confirmationCode}`,
		confirmation_code: confirmationCode,
	});
}
