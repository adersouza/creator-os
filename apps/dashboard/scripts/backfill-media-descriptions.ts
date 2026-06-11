/**
 * One-off script: Backfill ai_description on media items using Gemini Vision.
 *
 * Usage: npx tsx scripts/backfill-media-descriptions.ts
 *
 * - Images: Sends to Gemini Vision for a 1-line description
 * - Videos: Sets a group-contextual description (can't vision-analyze videos cheaply)
 * - Processes in batches of 5 with 1s delay between batches
 */

import { createClient } from "@supabase/supabase-js";

const SUPABASE_URL = process.env.VITE_SUPABASE_URL || process.env.SUPABASE_URL || "";
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.VITE_SUPABASE_ANON_KEY || "";
const GEMINI_KEY = process.env.GEMINI_API_KEY || "";
const USER_ID = "16cedeac-c441-4b22-b190-fd7f28392fb8";

const db = createClient(SUPABASE_URL, SUPABASE_KEY);

// Group name → persona description for video fallbacks
const GROUP_DESCRIPTIONS: Record<string, string> = {
	"Stacey": "selfie/lifestyle video of young woman, casual vibe",
	"Lola": "selfie/lifestyle video of young woman, flirty casual vibe",
	"Larissa": "selfie/lifestyle video of young Latina woman, confident vibe",
	"GFE": "selfie/lifestyle video of young Latina woman, girlfriend energy",
};

async function describeImage(url: string): Promise<string | null> {
	if (!GEMINI_KEY) {
		console.error("No GEMINI_API_KEY set");
		return null;
	}
	try {
		const resp = await fetch(
			`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${GEMINI_KEY}`,
			{
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					contents: [{
						parts: [
							{ text: "Describe this image in one short sentence (10-15 words max). Focus on: what the person is doing, setting, mood. Example: 'gym selfie in mirror, confident pose, workout clothes'. Do NOT mention race/ethnicity." },
							{ inlineData: { mimeType: "image/jpeg", data: await fetchImageBase64(url) } },
						],
					}],
					generationConfig: { maxOutputTokens: 50 },
				}),
				signal: AbortSignal.timeout(15000),
			},
		);
		if (!resp.ok) return null;
		const data = await resp.json();
		return data.candidates?.[0]?.content?.parts?.[0]?.text?.trim() || null;
	} catch {
		return null;
	}
}

async function fetchImageBase64(url: string): Promise<string> {
	const resp = await fetch(url, { signal: AbortSignal.timeout(10000) });
	const buf = await resp.arrayBuffer();
	return Buffer.from(buf).toString("base64");
}

function getVideoDescription(groupName: string): string {
	for (const [key, desc] of Object.entries(GROUP_DESCRIPTIONS)) {
		if (groupName.includes(key)) return desc;
	}
	return "lifestyle video of young woman";
}

async function main() {
	// Get all groups for name mapping
	const { data: groups } = await db.from("account_groups").select("id, name");
	const groupMap = new Map((groups || []).map((g: { id: string; name: string }) => [g.id, g.name]));

	// Get media needing descriptions
	const { data: media, error } = await db
		.from("media")
		.select("id, url, file_type, group_id")
		.eq("user_id", USER_ID)
		.is("ai_description", null)
		.not("url", "is", null)
		.order("created_at", { ascending: false })
		.limit(1000);

	if (error || !media) {
		console.error("Failed to fetch media:", error);
		return;
	}

	console.log(`Found ${media.length} media items needing descriptions`);

	let described = 0;
	let failed = 0;
	const BATCH_SIZE = 5;

	for (let i = 0; i < media.length; i += BATCH_SIZE) {
		const batch = media.slice(i, i + BATCH_SIZE);
		const promises = batch.map(async (item: { id: string; url: string; file_type: string; group_id: string }) => {
			const isVideo = (item.file_type || "").startsWith("video");
			const groupName = groupMap.get(item.group_id) || "";

			let description: string | null;
			if (isVideo) {
				description = getVideoDescription(groupName);
			} else {
				description = await describeImage(item.url);
			}

			if (description) {
				const { error: updateErr } = await db
					.from("media")
					.update({ ai_description: description })
					.eq("id", item.id);
				if (!updateErr) {
					described++;
				} else {
					failed++;
				}
			} else {
				failed++;
			}
		});

		await Promise.all(promises);
		console.log(`Progress: ${i + batch.length}/${media.length} (${described} described, ${failed} failed)`);

		// Rate limit: 1s between batches
		if (i + BATCH_SIZE < media.length) {
			await new Promise((r) => setTimeout(r, 1000));
		}
	}

	console.log(`\nDone! ${described} described, ${failed} failed out of ${media.length} total`);
}

main().catch(console.error);
