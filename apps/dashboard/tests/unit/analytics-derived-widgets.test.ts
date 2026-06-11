import { describe, expect, it } from "vitest";
import {
	normalizeOriginalityContent,
	originalitySetSimilarity,
	originalityShingles,
} from "../../api/_lib/handlers/analytics-sub/originality-risk";
import {
	hammingDistanceHex,
	mediaUrlFingerprint,
	normalizeTextForFingerprint,
	perceptualHashSimilarity,
	textFingerprint,
} from "../../api/_lib/originalitySignals";
import {
	audienceSharedSignals,
	audienceVectorCosine,
} from "../../api/_lib/handlers/analytics-sub/audience-twin-map";

describe("originality-risk derived scoring", () => {
	it("normalizes URLs, handles, hashtags, punctuation, and casing", () => {
		expect(
			normalizeOriginalityContent(
				"THIS is @creator's post!!! https://example.com #Growth",
			),
		).toBe("this is s post");
	});

	it("scores reused copy with high shingle similarity", () => {
		const a = originalityShingles(
			normalizeOriginalityContent(
				"Creators are missing the easiest growth lever: reply faster in the first hour.",
			),
		);
		const b = originalityShingles(
			normalizeOriginalityContent(
				"Creators are missing the easiest growth lever: reply faster in the first hour today.",
			),
		);

		expect(originalitySetSimilarity(a, b)).toBeGreaterThan(0.7);
	});

	it("keeps unrelated posts below the medium-risk threshold", () => {
		const a = originalityShingles(
			normalizeOriginalityContent("The carousel teaches profile conversion in three steps."),
		);
		const b = originalityShingles(
			normalizeOriginalityContent("Morning coffee and a quiet calendar changed the whole day."),
		);

		expect(originalitySetSimilarity(a, b)).toBeLessThan(0.25);
	});
});

describe("audience-twin-map vector math", () => {
	it("returns 1 for identical demographic vectors", () => {
		const a = new Map([
			["age:25-34", 45],
			["gender:female", 65],
			["country:us", 70],
		]);
		const b = new Map(a);

		expect(audienceVectorCosine(a, b)).toBeCloseTo(1, 6);
	});

	it("orders shared demographic signals by common strength", () => {
		const a = new Map([
			["age:25-34", 45],
			["gender:female", 65],
			["country:us", 70],
			["city:new york", 12],
		]);
		const b = new Map([
			["age:25-34", 50],
			["gender:female", 62],
			["country:us", 20],
			["city:los angeles", 14],
		]);

		expect(audienceSharedSignals(a, b)).toEqual([
			"gender · female",
			"age · 25-34",
			"country · us",
		]);
	});
});

describe("originality media/provenance fingerprints", () => {
	it("generates stable text fingerprints after normalization", () => {
		expect(normalizeTextForFingerprint("Hello @you #Growth https://x.test/a")).toBe(
			"hello",
		);
		expect(textFingerprint("Hello @you #Growth")).toBe(textFingerprint("hello"));
	});

	it("ignores query strings when hashing media URLs", () => {
		expect(mediaUrlFingerprint("https://cdn.example.com/a.jpg?token=one")).toBe(
			mediaUrlFingerprint("https://cdn.example.com/a.jpg?token=two"),
		);
	});

	it("scores perceptual hashes by hamming distance", () => {
		expect(hammingDistanceHex("ffff", "ff0f")).toBe(4);
		expect(perceptualHashSimilarity("ffff", "ffff")).toBe(1);
		expect(perceptualHashSimilarity("ffff", "0000")).toBe(0);
	});
});
