#!/usr/bin/env node
import "dotenv/config";
import { createClient } from "@supabase/supabase-js";

const SUPABASE_URL =
	process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL;
const SERVICE_KEY =
	process.env.SUPABASE_SERVICE_ROLE_KEY ||
	process.env.SUPABASE_SERVICE_KEY ||
	process.env.SERVICE_ROLE_KEY;
const APP_URL = (process.env.APP_URL || "https://juno33.com").replace(/\/$/, "");
const USER_ID = process.env.SMOKE_USER_ID;
const TARGET_URL = process.env.SMOKE_TARGET_URL || "https://example.com";

if (!SUPABASE_URL || !SERVICE_KEY || !USER_ID) {
	console.error(
		"Missing SUPABASE_URL/VITE_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, or SMOKE_USER_ID.",
	);
	process.exit(1);
}

const supabase = createClient(SUPABASE_URL, SERVICE_KEY, {
	auth: { persistSession: false },
});
const code = `smoke-${Date.now().toString(36)}`;
const uas = [
	{
		name: "Instagram iOS webview",
		ua: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Instagram 356.0.0.0.0",
		expectHtml: true,
	},
	{
		name: "Mobile Safari",
		ua: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
		expectHtml: true,
	},
	{
		name: "Meta crawler",
		ua: "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
		expectHtml: false,
	},
];

try {
	const { data: link, error: insertError } = await supabase
		.from("smart_links")
		.insert({
			user_id: USER_ID,
			code,
			title: "Smoke smart link",
			target_url: TARGET_URL,
			is_active: true,
			enable_deep_links: true,
			metadata: {
				appearance: {
					displayTitle: "Smoke smart link",
					subtitle: "Tap once to continue.",
					ctaLabel: "Open Link",
				},
			},
		})
		.select("id, code")
		.single();
	if (insertError) throw insertError;

	for (const check of uas) {
		const response = await fetch(`${APP_URL}/go/${encodeURIComponent(code)}`, {
			redirect: "manual",
			headers: { "User-Agent": check.ua, Accept: "text/html" },
		});
		const body = await response.text();
		if (check.expectHtml && !body.includes("No hidden redirects or auto-launches")) {
			throw new Error(`${check.name}: expected interstitial HTML`);
		}
		if (/window\.location\.(href|replace)\s*=|intent:\/\//i.test(body)) {
			throw new Error(`${check.name}: found auto-launch redirect script`);
		}
		if (check.expectHtml && !body.includes('rel="canonical"')) {
			throw new Error(`${check.name}: missing canonical metadata`);
		}
		console.log(
			`${check.name}: ${response.status} ${response.headers.get("location") || "html"}`,
		);
	}

	await supabase.from("smart_link_clicks").delete().eq("smart_link_id", link.id);
	await supabase.from("smart_links").delete().eq("id", link.id);
	console.log(`Cleaned up ${code}`);
} catch (error) {
	console.error(error);
	await supabase.from("smart_links").delete().eq("code", code);
	process.exit(1);
}
