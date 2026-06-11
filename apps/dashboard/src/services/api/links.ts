import { z } from "zod";
import { apiFetch } from "@/lib/apiFetch";
import { supabase } from "@/services/supabase";
import type { LinkBlockType, LinkItem } from "@/components/links/types";

export interface LinkBlockRegistryEntry {
  type: LinkBlockType;
  label: string;
  description: string;
}

export const LINK_BLOCK_TYPE_REGISTRY: LinkBlockRegistryEntry[] = [
  {
    type: "link",
    label: "Link",
    description: "Standard outbound link with click tracking.",
  },
  {
    type: "scheduled_window",
    label: "Scheduled window",
    description: "Only active between activeFrom and activeTo datetimes.",
  },
  {
    type: "email_capture",
    label: "Email capture",
    description: "Email field and CTA; posts to capture-email.",
  },
  {
    type: "tip_jar",
    label: "Tip jar",
    description: "External payment URL with amount presets.",
  },
  {
    type: "digital_product",
    label: "Digital product",
    description: "File URL and display price with payment handoff.",
  },
  {
    type: "affiliate_catalog",
    label: "Affiliate catalog",
    description: "List of affiliate entries with logo, name, and URL.",
  },
  {
    type: "bento_media_grid",
    label: "Bento media grid",
    description: "Two by two grid of image or video URLs.",
  },
];

export function isKnownLinkBlockType(value: string): value is LinkBlockType {
  return LINK_BLOCK_TYPE_REGISTRY.some((entry) => entry.type === value);
}

export interface LinksEnhanceVariant {
  blocks: LinkItem[];
  reasoning: string;
}

export interface LinksEnhanceResult {
  variants: LinksEnhanceVariant[];
}

async function hasSession(): Promise<boolean> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return !!session?.access_token;
}

const linkItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  url: z.string(),
  clicks: z.number(),
  blockType: z.string().optional(),
  subtitle: z.string().optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
});

const enhanceResponseSchema = z.object({
  success: z.boolean().optional(),
  variants: z.array(z.object({
    blocks: z.array(linkItemSchema),
    reasoning: z.string(),
  })),
});

export async function enhanceLinkBlocks({
  linkId,
  blocks,
}: {
  linkId: string;
  blocks: LinkItem[];
}): Promise<LinksEnhanceResult | null> {
  if (!(await hasSession())) return null;
  const data = await apiFetch("/api/links?action=ai-enhance", enhanceResponseSchema, {
    method: "POST",
    json: {
      action: "ai-enhance",
      link_id: linkId,
      blocks,
    },
  });
  return data;
}
