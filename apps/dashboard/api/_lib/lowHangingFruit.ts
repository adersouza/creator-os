/**
 * Low-Hanging Fruit Recommendations Engine
 *
 * Analyzes user data to surface high-ROI growth recommendations.
 * Returns top 3 sorted by ROI (impact / effort).
 *
 * Refactored: logic lives in sub-modules under ./low-hanging-fruit/.
 * This file re-exports everything for backward compatibility.
 */

export * from "./low-hanging-fruit/index.js";
