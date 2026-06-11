// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Create a new smart link.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { validatePublicRedirectUrl } from "../../outboundUrlSecurity.js";
import { getUserTier } from "../../tierGate.js";
import {
	CreateSchema,
	db,
	generateUniqueCode,
	generateWebhookSecret,
	getAlternateRedirectErrors,
	getCloakingWarnings,
	isReservedSmartLinkCode,
	SMART_LINK_LIMITS,
} from "./shared.js";

type SmartLinkCreateClient = ReturnType<typeof db> & {
	rpc?: (
		fn: string,
		args: Record<string, unknown>,
	) => Promise<{
		data: unknown;
		error: { code?: string | undefined; message?: string | undefined } | null;
	}>;
};

export async function handleCreate(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = CreateSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const alternateRedirectErrors = getAlternateRedirectErrors(parsed.data);
	if (alternateRedirectErrors.length > 0) {
		return apiError(res, 400, alternateRedirectErrors[0]!);
	}

	const targetError = await validatePublicRedirectUrl(
		parsed.data.target_url,
		"smart-link-create",
	);
	if (targetError) {
		return apiError(res, 400, "Target URL is not allowed");
	}

	// Check tier limits
	const tier = await getUserTier(userId);
	const limit = SMART_LINK_LIMITS[tier] || 0;

	const { count } = await db()
		.from("smart_links")
		.select("id", { count: "exact", head: true })
		.eq("user_id", userId);

	if ((count || 0) >= limit) {
		return apiError(res, 403, `Your ${tier} plan allows ${limit} smart links`);
	}

	// Validate post_id ownership if provided
	if (parsed.data.post_id) {
		const { data: ownedPost } = await db()
			.from("posts")
			.select("id")
			.eq("id", parsed.data.post_id)
			.eq("user_id", userId)
			.maybeSingle();
		if (!ownedPost) {
			return apiError(res, 403, "Post not found or not owned by you");
		}
	}

	// Generate or validate code
	let code = parsed.data.code?.toLowerCase();
	if (code) {
		if (isReservedSmartLinkCode(code)) {
			return apiError(res, 400, "Code is reserved");
		}
		const { data: existing } = await db()
			.from("smart_links")
			.select("id")
			.eq("code", code)
			.maybeSingle();
		if (existing) {
			return apiError(res, 409, "Code already taken");
		}
	} else {
		code = await generateUniqueCode();
	}

	const client = db() as SmartLinkCreateClient;
	const createPayload = {
		code,
		target_url: parsed.data.target_url,
		title: parsed.data.title || null,
		ig_deep_link: parsed.data.ig_deep_link || null,
		threads_deep_link: parsed.data.threads_deep_link || null,
		enable_deep_links: parsed.data.enable_deep_links ?? true,
		webhook_secret: generateWebhookSecret(),
		post_id: parsed.data.post_id || null,
		est_conversion_rate: parsed.data.est_conversion_rate ?? null,
		est_conversion_value: parsed.data.est_conversion_value ?? null,
		metadata: parsed.data.metadata ?? null,
	};
	const { data, error } =
		typeof client.rpc === "function"
			? await client.rpc("create_smart_link_with_quota", {
					p_user_id: userId,
					p_limit: limit,
					p_payload: createPayload,
				})
			: await client
					.from("smart_links")
					.insert({
						user_id: userId,
						...createPayload,
						ig_redirect_url: null,
						threads_redirect_url: null,
						mobile_redirect_url: null,
					})
					.select()
					.maybeSingle();

	if (error) {
		if (error.message?.includes("QUOTA_EXCEEDED")) {
			return apiError(
				res,
				403,
				`Your ${tier} plan allows ${limit} smart links`,
			);
		}
		if (error.code === "23505" || error.message?.includes("duplicate")) {
			return apiError(res, 409, "Code already taken");
		}
		logger.error("[smart-links] Create error", { error: String(error) });
		return apiError(res, 500, "Failed to create smart link");
	}

	const warnings = getCloakingWarnings(parsed.data);
	return apiSuccess(
		res,
		{ link: data, ...(warnings.length > 0 ? { warnings } : {}) },
		201,
	);
}
