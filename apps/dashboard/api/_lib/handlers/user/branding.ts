// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Agency Branding Handler
 * GET  /api/agency-branding — get user's branding
 * POST /api/agency-branding — upsert branding (name, logo_url, brand_color)
 * Merged from api/agency-branding.ts
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { withAuthDb } from "../../middleware.js";
import { requireMinTier } from "../../tierGate.js";
import { z } from "../../zodCompat.js";

export const AgencyBrandingSchema = z.object({
	agency_name: z.string().max(200).optional(),
	brand_color: z.string().max(30).optional(),
	logo_base64: z.string().optional(),
	remove_logo: z.boolean().optional(),
});

async function handleGet(
	_req: VercelRequest,
	res: VercelResponse,
	context: DbContext,
) {
	const { data, error } = await context.userDb
		.from("agency_branding")
		.select("agency_name, agency_logo_url, brand_color, updated_at")
		.eq("user_id", context.user.id)
		.maybeSingle();

	if (error) return apiError(res, 500, "Internal server error");
	return apiSuccess(res, { branding: data || null });
}

async function handlePost(
	req: VercelRequest,
	res: VercelResponse,
	context: DbContext,
) {
	const parsed = AgencyBrandingSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { agency_name, brand_color, logo_base64 } = parsed.data;

	let agency_logo_url: string | undefined;

	if (logo_base64) {
		const match = (logo_base64 as string).match(
			/^data:(image\/(?:png|jpeg|jpg|gif|webp));base64,(.+)$/,
		);
		if (!match) {
			return apiError(res, 400, "Invalid image format. Use image/* base64.");
		}

		const mimeType = match[1];
		const base64Data = match[2];
		const buffer = Buffer.from(base64Data!, "base64");

		if (buffer.length > 500 * 1024) {
			return apiError(res, 400, "Logo must be under 500KB");
		}

		const ext = mimeType!.split("/")[1]!.replace("+xml", "");
		const filename = `agency-logo-${context.user.id}.${ext}`;

		const { error: uploadError } = await context.adminDb.storage
				.from("agency-logos")
				.upload(filename, buffer, {
					upsert: true,
					...(mimeType ? { contentType: mimeType } : {}),
				});

		if (!uploadError) {
			const { data: urlData } = context.adminDb.storage
				.from("agency-logos")
				.getPublicUrl(filename);
			agency_logo_url = urlData?.publicUrl;
		}
	}

	const payload: Record<string, unknown> = {
		user_id: context.user.id,
		updated_at: new Date().toISOString(),
	};
	if (agency_name !== undefined) payload.agency_name = agency_name;
	if (brand_color !== undefined) payload.brand_color = brand_color;
	if (agency_logo_url) payload.agency_logo_url = agency_logo_url;

	if (parsed.data.remove_logo === true) {
		payload.agency_logo_url = null;
	}

	const { data, error } = await context.userDb
		.from("agency_branding")
		// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert requires cast for dynamic record
		.upsert(payload as any, { onConflict: "user_id" })
		.select("agency_name, agency_logo_url, brand_color, updated_at")
		.maybeSingle();

	if (error) return apiError(res, 500, "Internal server error");
	return apiSuccess(res, { branding: data });
}

export default withAuthDb(async (req, res, context) => {
	if (!(await requireMinTier(context.user.id, "agency", res))) return;

	if (req.method === "GET") return handleGet(req, res, context);
	if (req.method === "POST") return handlePost(req, res, context);
	return apiError(res, 405, "Method not allowed");
});
