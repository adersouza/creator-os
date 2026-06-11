import { describe, expect, it } from "vitest";
import {
	buildInstagramAudioReplacementParams,
	buildInstagramAudioSearchParams,
	getInstagramMediaAudioType,
	normalizeInstagramAudioAsset,
} from "../../api/_lib/instagram/audio.js";
import { applyInstagramReelsAudioParams } from "../../api/_lib/instagram/publishing.js";

describe("Instagram Audio API support", () => {
	it("normalizes Meta audio assets while preserving the raw payload", () => {
		const raw = {
			audio_id: "17900000000000001",
			title: "Runway Pop",
			display_artist: "Meta Sound Collection",
			audio_type: "music",
			duration_in_ms: 31200,
			cover_artwork_thumbnail_uri: "https://example.com/audio.jpg",
			download_url: "https://example.com/audio.mp3",
		};

		expect(normalizeInstagramAudioAsset(raw)).toEqual({
			id: "17900000000000001",
			title: "Runway Pop",
			artistName: "Meta Sound Collection",
			audioType: "music",
			durationMs: 31200,
			thumbnailUrl: "https://example.com/audio.jpg",
			previewUrl: "https://example.com/audio.mp3",
			isExplicit: undefined,
			raw,
		});
	});

	it("builds documented /ig_audio search parameters", () => {
		const params = buildInstagramAudioSearchParams({
			userId: "17841400000000000",
			audioType: "music",
			query: "runway",
			limit: 12,
		});

		expect(params.get("audio_type")).toBe("music");
		expect(params.get("user_id")).toBe("17841400000000000");
		expect(params.get("search_query")).toBe("runway");
		expect(params.get("q")).toBeNull();
		expect(params.get("limit")).toBe("12");
	});

	it("builds documented replacement audio discovery parameters", () => {
		const params = buildInstagramAudioReplacementParams({
			userId: "17841400000000000",
			igMediaId: "17900000000000001",
			audioReplacementMode: "search",
			query: "royalty free",
		});

		expect(params.get("product")).toBe("ADS");
		expect(params.get("purpose")).toBe("AUDIO_COPYRIGHT_REPLACEMENT");
		expect(params.get("audio_replacement_mode")).toBe("search");
		expect(params.get("ig_media_id")).toBe("17900000000000001");
		expect(params.get("user_id")).toBe("17841400000000000");
		expect(params.get("search_query")).toBe("royalty free");
	});

	it("adds Meta-native audio and original-audio rename params only for Reels", () => {
		const params: Record<string, string> = {};

		applyInstagramReelsAudioParams(params, {
			mediaType: "REELS",
			audioName: "Studio cut",
			igAudioId: "17900000000000001",
		});

		expect(params).toEqual({
			audio_name: "Studio cut",
			audio_id: "17900000000000001",
		});

		const feedParams: Record<string, string> = {};
		applyInstagramReelsAudioParams(feedParams, {
			mediaType: "VIDEO",
			audioName: "Ignored",
			igAudioId: "ignored",
		});
		expect(feedParams).toEqual({});
	});

	it("skips media_audio_type lookup for Instagram Login accounts", async () => {
		const result = await getInstagramMediaAudioType(
			"not-decrypted-for-instagram-login",
			"17900000000000001",
			"instagram",
		);

		expect(result).toEqual({ success: true, mediaAudioType: null });
	});
});
