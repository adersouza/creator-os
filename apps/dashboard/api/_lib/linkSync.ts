/**
 * Sync link page data from Supabase to Cloudflare Worker KV.
 *
 * Called after any mutation in api/links.ts.
 * Uses the Cloudflare Worker's API to write KV data.
 *
 * If CLOUDFLARE_WORKER_URL or CLOUDFLARE_API_KEY are not set,
 * sync is silently skipped (Vercel-only mode works fine).
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { logger } from "./logger.js";

const WORKER_URL = process.env.CLOUDFLARE_WORKER_URL;
const WORKER_API_KEY = process.env.CLOUDFLARE_API_KEY;

export async function syncPageToCloudflare(
	supabase: SupabaseClient,
	pageId: string,
): Promise<{ synced: boolean; error?: string | undefined }> {
	if (!WORKER_URL || !WORKER_API_KEY) {
		return { synced: false, error: "Cloudflare not configured (optional)" };
	}

	try {
		const { data: page, error } = await supabase
			.from("link_pages")
			.select("*, link_items(*)")
			.eq("id", pageId)
			.maybeSingle();

		if (error || !page) {
			return { synced: false, error: "Page not found" };
		}

		interface LinkItem {
			id: string;
			title: string;
			url: string;
			icon: string;
			is_primary: boolean;
			is_visible: boolean;
			platform: string;
			deep_link_url: string;
			position: number;
		}
		const links = ((page.link_items || []) as LinkItem[])
			.filter((l) => l.is_visible)
			.sort((a, b) => a.position - b.position)
			.map((l) => ({
				id: l.id,
				title: l.title,
				url: l.url,
				icon: l.icon,
				is_primary: l.is_primary,
				is_visible: l.is_visible,
				platform: l.platform,
				deep_link_url: l.deep_link_url,
			}));

		// Build KV payload (both multi-link and legacy single-link compat)
		const kvPayload = {
			links,
			title: page.title,
			bio: page.bio,
			avatar_url: page.avatar_url,
			brand_color: page.brand_color,
			background_color: page.background_color,
			show_online_badge: page.show_online_badge,
			promo_text: page.promo_text,
			enable_deeplink_escape: page.enable_deeplink_escape,
			is_published: page.is_published,
			// Legacy single-link compat fields
			destination:
				links.find((l) => l.is_primary)?.url || links[0]?.url || null,
			name: page.title,
			description: page.bio,
			image: page.avatar_url,
			color: page.brand_color,
			promo: page.promo_text,
			showOnline: page.show_online_badge,
		};

		// #624: Retry once on transient failure to avoid stale data
		let lastError = "";
		for (let attempt = 0; attempt < 2; attempt++) {
			try {
				const response = await fetch(`${WORKER_URL}/api/links`, {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						Authorization: `Bearer ${WORKER_API_KEY}`,
					},
					body: JSON.stringify({
						slug: page.slug,
						...kvPayload,
					}),
					signal: AbortSignal.timeout(15000),
				});

				if (response.ok) return { synced: true };

				lastError = await response.text();
				if (response.status >= 400 && response.status < 500) break; // Don't retry client errors
			} catch (err) {
				lastError = err instanceof Error ? err.message : String(err);
			}
		}

		return { synced: false, error: `Cloudflare sync failed: ${lastError}` };
	} catch (error: unknown) {
		logger.error("Link sync error", { error: String(error) });
		return {
			synced: false,
			error: error instanceof Error ? error.message : String(error),
		};
	}
}

export async function deletePageFromCloudflare(slug: string): Promise<void> {
	if (!WORKER_URL || !WORKER_API_KEY) return;

	try {
		await fetch(`${WORKER_URL}/api/links/${slug}`, {
			method: "DELETE",
			headers: { Authorization: `Bearer ${WORKER_API_KEY}` },
			signal: AbortSignal.timeout(15000),
		});
	} catch (error) {
		logger.error("Link sync delete error", { error: String(error) });
	}
}
