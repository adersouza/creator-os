/**
 * Low-Hanging Fruit Recommendations Engine — barrel re-export.
 *
 * Sub-modules:
 *   shared.ts               — Types, interfaces, DB accessors, confidence helper
 *   postChecks.ts           — Post-level checks 1-10 (timing, alt text, hashtags, etc.)
 *   advancedChecks.ts       — Advanced checks 11-13 (group gap, decay, account health)
 *   historyRecommendations.ts — History-based recs (engagement trend, best hour, velocity)
 *   solvedAndRegressed.ts   — Solved/regression tracking and baseline storage
 *   filtering.ts            — Deprioritization, dismissal, and snooze filtering
 *   orchestrator.ts         — Main getLowHangingFruit() entry point
 */

export { getLowHangingFruit } from "./orchestrator.js";
// Re-export only the public API that was previously exported from lowHangingFruit.ts
export type {
	ConfidenceLevel,
	LowHangingFruitResult,
	Recommendation,
	RecommendationCategory,
	RegressedRecommendation,
	SolvedRecommendation,
} from "./shared.js";
