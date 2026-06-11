import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { runPublishPreflight } from "../api/_lib/publishPreflight.js";
import {
	campaignFactoryAudioAllowsLive,
	getCampaignFactoryMetadata,
} from "../src/lib/campaignFactory";

const account = {
	found: true,
	isActive: true,
	needsReauth: false,
	status: "active",
	hasAccessToken: true,
	hasPlatformUserId: true,
};

function loadSmokeDraft() {
	const fixture = process.env.PIPELINE_AUDIO_SMOKE_FIXTURE;
	if (!fixture) return null;
	const payload = JSON.parse(readFileSync(fixture, "utf8"));
	const drafts = payload?.payload?.drafts || payload?.drafts || [];
	return drafts[0] || null;
}

function preflightInputFromDraft(draft: Record<string, unknown>, status?: string, audioName?: string) {
	const metadata = JSON.parse(JSON.stringify(draft.metadata || {}));
	if (status) {
		metadata.campaign_factory.audio_intent.status = status;
		if (status === "attached" || status === "verified") {
			metadata.campaign_factory.audio_intent.operator_selection = {
				platform_audio_id: "ig_runway_pop",
				selected_at: "2026-05-22T12:00:00.000Z",
				...(status === "attached"
					? { attached_at: "2026-05-22T12:05:00.000Z" }
					: { verified_at: "2026-05-22T12:10:00.000Z" }),
			};
		}
	}
	return {
		platform: "instagram" as const,
		instagramAccountId: String(draft.instagramAccountId || "ig_smoke"),
		content: String(draft.content || "caption"),
		igMediaType: "REELS" as const,
		media: [{ type: "video", url: "https://example.com/smoke.mp4" }],
		audioName,
		metadata,
	};
}

describe("pipeline audio smoke fixture", () => {
	it.runIf(process.env.PIPELINE_AUDIO_SMOKE_FIXTURE)("parses Campaign Factory audio intent and enforces native audio gates", async () => {
		const draft = loadSmokeDraft();
		expect(draft).not.toBeNull();
		const cf = getCampaignFactoryMetadata({ metadata: draft.metadata });
		const firstRecommendation = cf?.audio_intent?.recommendations?.[0];

		expect(cf?.audio_intent?.status).toBe("recommended");
		expect(firstRecommendation?.audio_title).toEqual(expect.any(String));
		expect(firstRecommendation?.platform_audio_id).toBeTruthy();
		expect(campaignFactoryAudioAllowsLive(cf)).toBe(false);

		const unresolved = await runPublishPreflight(preflightInputFromDraft(draft), { account });
		expect(unresolved.ok).toBe(false);
		expect(unresolved.issues.some((issue) => issue.code === "native_audio_unresolved")).toBe(true);

		const withAudioName = await runPublishPreflight(preflightInputFromDraft(draft, "selected", firstRecommendation?.audio_title), { account });
		expect(withAudioName.ok).toBe(false);
		expect(withAudioName.issues.some((issue) => issue.code === "audio_name_not_native_verification")).toBe(true);

		for (const status of ["attached", "verified", "skipped", "not_required"]) {
			const result = await runPublishPreflight(preflightInputFromDraft(draft, status), { account });
			expect(result.ok).toBe(true);
		}
	});
});
