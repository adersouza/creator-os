import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import { z } from "../../zodCompat.js";

const TrackEventSchema = z.object({
  link_id: z.string().uuid(),
  block_id: z.string().optional(),
  event_name: z.enum(["impression", "click", "redirect"]),
  fingerprint: z.string().max(120).optional(),
});

export async function handleTrackEvent(
  req: VercelRequest,
  res: VercelResponse,
  userId: string,
) {
  const parsed = TrackEventSchema.safeParse(req.body);
  if (!parsed.success) {
    return apiError(
      res,
      400,
      `Invalid input: ${parsed.error.issues[0]?.message}`,
    );
  }

  const supabase = getSupabaseAny();
  const { data: smartLink, error: linkError } = await supabase
    .from("smart_links")
    .select("id")
    .eq("id", parsed.data.link_id)
    .eq("user_id", userId)
    .maybeSingle();
  if (linkError) return apiError(res, 500, "Failed to verify smart link");
  if (!smartLink) return apiError(res, 404, "Smart link not found");

  const { error } = await supabase
    .from("smart_link_clicks")
    .insert({
      smart_link_id: parsed.data.link_id,
      fingerprint: parsed.data.fingerprint ?? null,
      event_name: parsed.data.event_name,
      block_id: parsed.data.block_id ?? null,
      source_platform: "server-event",
    });
  if (error) {
    logger.error("[links] track-event insert failed", { error: error.message });
    return apiError(res, 500, "Failed to track event");
  }
  return apiSuccess(res, { ok: true });
}
