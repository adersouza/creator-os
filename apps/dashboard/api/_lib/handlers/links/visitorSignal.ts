import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getSupabaseAny } from "../../supabase.js";
import { z, zRecord, zUnknown } from "../../zodCompat.js";

const BlockSchema = z.object({
  id: z.string(),
  title: z.string().optional(),
  url: z.string().optional(),
  metadata: zRecord(z.string(), zUnknown()).optional(),
});

const VisitorSignalSchema = z.object({
  link_id: z.string().uuid(),
  fingerprint: z.string().min(1).max(120),
  referrer: z.string().max(500).optional(),
  visited_blocks: z.array(z.string()).default([]),
  blocks: z.array(BlockSchema).default([]),
});

type LinkVisitorBlock = typeof BlockSchema["_output"];

function referrerScore(block: LinkVisitorBlock, referrer: string) {
  const haystack = [
    block.title ?? "",
    block.url ?? "",
    typeof block.metadata?.referrerMatch === "string"
      ? block.metadata.referrerMatch
      : "",
  ]
    .join(" ")
    .toLowerCase();
  const normalized = referrer.toLowerCase();
  if (!normalized) return 0;
  if (haystack.includes("instagram") && normalized.includes("instagram"))
    return 1;
  if (haystack.includes("tiktok") && normalized.includes("tiktok")) return 1;
  if (haystack.includes("facebook") && normalized.includes("facebook"))
    return 1;
  if (haystack.includes("pinterest") && normalized.includes("pinterest"))
    return 1;
  return 0;
}

export async function handleVisitorSignal(
  req: VercelRequest,
  res: VercelResponse,
  userId: string,
) {
  const parsed = VisitorSignalSchema.safeParse(req.body);
  if (!parsed.success) {
    return apiError(
      res,
      400,
      `Invalid input: ${parsed.error.issues[0]?.message}`,
    );
  }
  const {
    link_id,
    fingerprint,
    referrer = "",
    visited_blocks,
    blocks,
  } = parsed.data;
  const supabase = getSupabaseAny();

  const { data: page, error: pageError } = await supabase
    .from("link_pages")
    .select("id")
    .eq("id", link_id)
    .eq("user_id", userId)
    .maybeSingle();
  if (pageError) return apiError(res, 500, "Failed to verify link page");
  if (!page) return apiError(res, 404, "Link page not found");

  const { data: existing } = await supabase
    .from("link_visitor_signals")
    .select("id, visited_blocks")
    .eq("link_page_id", link_id)
    .eq("fingerprint", fingerprint)
    .order("last_seen", { ascending: false })
    .limit(1)
    .maybeSingle();

  const existingVisitedBlocks = existing?.visited_blocks;
  const mergedVisited = Array.from(
    new Set([
      ...((Array.isArray(existingVisitedBlocks)
        ? existingVisitedBlocks
        : []) as string[]),
      ...visited_blocks,
    ]),
  );

  if (existing?.id) {
    await supabase
      .from("link_visitor_signals")
      .update({
        referrer,
        visited_blocks: mergedVisited,
        last_seen: new Date().toISOString(),
      })
      .eq("id", existing.id);
  } else {
    await supabase.from("link_visitor_signals").insert({
      link_page_id: link_id,
      fingerprint,
      referrer,
      visited_blocks: mergedVisited,
    });
  }

  const clicked = new Set(mergedVisited);
  const sortedBlocks = [...blocks].sort((a, b) => {
    const clickedDelta = Number(clicked.has(b.id)) - Number(clicked.has(a.id));
    if (clickedDelta !== 0) return clickedDelta;
    const referrerDelta =
      referrerScore(b, referrer) - referrerScore(a, referrer);
    return referrerDelta;
  });

  return apiSuccess(res, {
    block_order: sortedBlocks.map((block) => block.id),
    visited_blocks: mergedVisited,
  });
}
