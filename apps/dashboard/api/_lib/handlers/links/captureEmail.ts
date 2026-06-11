import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiSuccess, apiError } from "../../apiResponse.js";
import { getSupabase } from "../../supabase.js";
import { z } from "../../zodCompat.js";

const CaptureEmailSchema = z.object({
  link_id: z.string().uuid(),
  block_id: z.string().optional(),
  email: z.string().email(),
});

export async function handleCaptureEmail(
  req: VercelRequest,
  res: VercelResponse,
  userId: string,
) {
  const parsed = CaptureEmailSchema.safeParse(req.body);
  if (!parsed.success) {
    return apiError(
      res,
      400,
      `Invalid input: ${parsed.error.issues[0]?.message}`,
    );
  }
  const { data: page, error } = await getSupabase()
    .from("link_pages")
    .select("id")
    .eq("id", parsed.data.link_id)
    .eq("user_id", userId)
    .maybeSingle();

  if (error) return apiError(res, 500, "Failed to verify link page");
  if (!page) return apiError(res, 404, "Link page not found");

  // Phase 1 stores capture wiring contract only. ESP/webhook persistence comes next.
  return apiSuccess(res, { captured: true });
}
