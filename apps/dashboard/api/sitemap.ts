// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { logger } from "./_lib/logger.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "./_lib/privilegedDb.js";

const SITE_URL = "https://juno33.com";

const STATIC_PAGES = [
	{ loc: "/", priority: "1.0", changefreq: "weekly" },
	{ loc: "/about", priority: "0.8", changefreq: "monthly" },
	{ loc: "/login", priority: "0.5", changefreq: "monthly" },
	{ loc: "/privacy", priority: "0.3", changefreq: "yearly" },
	{ loc: "/terms", priority: "0.3", changefreq: "yearly" },
];

function escapeXml(str: string): string {
	return str
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&apos;");
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET") {
		const { apiError } = await import("./_lib/apiResponse.js");
		return apiError(res, 405, "Method not allowed");
	}

	try {
		const db = getPrivilegedSupabase(PRIVILEGED_DB_REASONS.publicSitemap);

		const { data: linkPages, error } = await db
			.from("link_pages")
			.select("slug, updated_at")
			.eq("is_published", true);

		if (error) {
			logger.error("Sitemap: failed to fetch link_pages", {
				error: error.message,
			});
			// Fall back to static-only sitemap on DB error
		}

		const urls: string[] = [];

		// Static pages
		for (const page of STATIC_PAGES) {
			urls.push(`  <url>
    <loc>${SITE_URL}${page.loc}</loc>
    <changefreq>${page.changefreq}</changefreq>
    <priority>${page.priority}</priority>
  </url>`);
		}

		// Dynamic link pages
		if (linkPages) {
			for (const page of linkPages) {
				const lastmod = page.updated_at
					? `\n    <lastmod>${page.updated_at.split("T")[0]!}</lastmod>`
					: "";
				urls.push(`  <url>
    <loc>${SITE_URL}/@${escapeXml(page.slug)}</loc>${lastmod}
    <changefreq>weekly</changefreq>
    <priority>0.6</priority>
  </url>`);
			}
		}

		const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.join("\n")}
</urlset>`;

		res.setHeader("Content-Type", "application/xml; charset=utf-8");
		res.setHeader(
			"Cache-Control",
			"public, s-maxage=3600, stale-while-revalidate=86400",
		);
		return res.status(200).send(xml);
	} catch (err) {
		logger.error("Sitemap: unexpected error", {
			error: err instanceof Error ? err.message : String(err),
		});
		return res.status(500).send("Internal Server Error");
	}
}
