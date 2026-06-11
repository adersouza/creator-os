import { describe, it, expect } from "vitest";

/**
 * Pure-logic tests for the feature gating thresholds.
 * We extract the logic from the hook and test it directly
 * to avoid needing React rendering + Supabase mocks for every case.
 */

// Mirror the FEATURE_UNLOCK_MAP from useFeatureGating.ts
const FEATURE_UNLOCK_MAP: Record<string, number> = {
	content_type_performance: 5,
	best_times: 5,
	ai_autopsy: 20,
	shadowban_detection: 20,
	growth_simulator: 20,
	content_dna: 50,
	decay_rate: 50,
	viral_score: 20,
};

function isUnlocked(feature: string, postCount: number): boolean {
	const required = FEATURE_UNLOCK_MAP[feature];
	return required === undefined || postCount >= required;
}

function postsUntilUnlock(feature: string, postCount: number): number {
	const required = FEATURE_UNLOCK_MAP[feature];
	if (required === undefined) return 0;
	return Math.max(required - postCount, 0);
}

describe("Feature gating logic", () => {
	describe("5-post milestone", () => {
		it("locks content_type_performance at 4 posts", () => {
			expect(isUnlocked("content_type_performance", 4)).toBe(false);
		});

		it("unlocks content_type_performance at exactly 5 posts", () => {
			expect(isUnlocked("content_type_performance", 5)).toBe(true);
		});
	});

	describe("20-post milestone", () => {
		it("locks growth_simulator at 19 posts", () => {
			expect(isUnlocked("growth_simulator", 19)).toBe(false);
		});

		it("unlocks growth_simulator at exactly 20 posts", () => {
			expect(isUnlocked("growth_simulator", 20)).toBe(true);
		});

		it("locks ai_autopsy at 19 posts", () => {
			expect(isUnlocked("ai_autopsy", 19)).toBe(false);
		});
	});

	describe("50-post milestone", () => {
		it("locks content_dna at 49 posts", () => {
			expect(isUnlocked("content_dna", 49)).toBe(false);
		});

		it("unlocks content_dna at exactly 50 posts", () => {
			expect(isUnlocked("content_dna", 50)).toBe(true);
		});

		it("locks decay_rate at 49 posts", () => {
			expect(isUnlocked("decay_rate", 49)).toBe(false);
		});

		it("unlocks decay_rate at exactly 50 posts", () => {
			expect(isUnlocked("decay_rate", 50)).toBe(true);
		});
	});

	describe("downward drift — live count, no persistence", () => {
		it("revokes content_dna when posts drop from 52 to 42", () => {
			expect(isUnlocked("content_dna", 52)).toBe(true);
			expect(isUnlocked("content_dna", 42)).toBe(false);
		});

		it("revokes decay_rate when posts drop from 52 to 42", () => {
			expect(isUnlocked("decay_rate", 52)).toBe(true);
			expect(isUnlocked("decay_rate", 42)).toBe(false);
		});

		it("revokes growth_simulator when posts drop from 25 to 15", () => {
			expect(isUnlocked("growth_simulator", 25)).toBe(true);
			expect(isUnlocked("growth_simulator", 15)).toBe(false);
		});
	});

	describe("postsUntilUnlock", () => {
		it("returns 0 for already-unlocked features", () => {
			expect(postsUntilUnlock("content_dna", 60)).toBe(0);
		});

		it("returns remaining posts needed", () => {
			expect(postsUntilUnlock("content_dna", 42)).toBe(8);
		});

		it("returns 0 for unknown features (no gate)", () => {
			expect(postsUntilUnlock("nonexistent_feature", 0)).toBe(0);
		});
	});

	describe("unknown features are always unlocked", () => {
		it("returns true for a feature not in the map", () => {
			expect(isUnlocked("unknown_feature", 0)).toBe(true);
		});
	});
});
