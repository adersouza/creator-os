/**
 * Lazy-loading wrapper for AI service
 * Delays loading @google/genai until actually needed (button clicks, not render-critical)
 *
 * Imports directly from ./ai (skipping the ./aiService barrel re-export).
 *
 * Benefits:
 * - Reduces initial bundle size by ~100 KB
 * - AI operations are event-driven (user clicks), not needed immediately
 * - Improves initial page load performance
 */

let aiServicePromise: Promise<typeof import("./ai/index.js")> | null = null;

/**
 * Get AI service (lazy loads on first call)
 * @returns Promise resolving to AI service module
 */
export const getAIService = () => {
	if (!aiServicePromise) {
		aiServicePromise = import("./ai/index.js");
	}
	return aiServicePromise;
};

// Re-export types for type safety (types are free, no runtime cost)
export type {
	DiagnosisCategory,
	// Growth Diagnosis types
	GrowthDiagnosisInput,
	GrowthDiagnosisResult,
	// Post Ideas types
	PostIdea,
	PostIdeasInput,
	SimulationInput,
	SimulationResult,
	// Simulation types
	SimulationSettings,
	VoiceProfile,
} from "./ai/index.js";
