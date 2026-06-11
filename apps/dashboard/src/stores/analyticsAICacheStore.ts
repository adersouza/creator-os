/**
 * analyticsAICacheStore — Persisted cache for expensive AI-generated outputs.
 *
 * Stores diagnosis, viral analysis, and post analysis results with a 24-hour TTL.
 * These are costly to regenerate so we persist them across navigation and page reloads.
 *
 * Split from analyticsStore (M14) — UI state (timeframe, refreshKey) stays there.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface CachedDiagnosis {
	accountId: string;
	diagnosis: unknown;
	generatedAt: number;
}

export interface CachedViralAnalysis {
	postId: string;
	analysis: string;
	generatedAt: number;
}

interface AnalyticsAICacheState {
	diagnosisCache: Record<string, CachedDiagnosis>;
	viralAnalysisCache: Record<string, CachedViralAnalysis>;
	postAnalysisCache: Record<string, { analysis: string; generatedAt: number }>;

	setCachedDiagnosis: (accountId: string, diagnosis: unknown) => void;
	getCachedDiagnosis: (accountId: string) => CachedDiagnosis | null;
	setCachedViralAnalysis: (postId: string, analysis: string) => void;
	getCachedViralAnalysis: (postId: string) => string | null;
	setCachedPostAnalysis: (postId: string, analysis: string) => void;
	getCachedPostAnalysis: (postId: string) => string | null;
	clearAICache: () => void;
}

const CACHE_EXPIRY_MS = 24 * 60 * 60 * 1000;

export const useAnalyticsAICacheStore = create<AnalyticsAICacheState>()(
	persist(
		(set, get) => ({
			diagnosisCache: {},
			viralAnalysisCache: {},
			postAnalysisCache: {},

			setCachedDiagnosis: (accountId, diagnosis) =>
				set((state) => ({
					diagnosisCache: {
						...state.diagnosisCache,
						[accountId]: { accountId, diagnosis, generatedAt: Date.now() },
					},
				})),

			getCachedDiagnosis: (accountId) => {
				const cached = get().diagnosisCache[accountId];
				if (!cached) return null;
				if (Date.now() - cached.generatedAt > CACHE_EXPIRY_MS) return null;
				return cached;
			},

			setCachedViralAnalysis: (postId, analysis) =>
				set((state) => ({
					viralAnalysisCache: {
						...state.viralAnalysisCache,
						[postId]: { postId, analysis, generatedAt: Date.now() },
					},
				})),

			getCachedViralAnalysis: (postId) => {
				const cached = get().viralAnalysisCache[postId];
				if (!cached) return null;
				if (Date.now() - cached.generatedAt > CACHE_EXPIRY_MS) return null;
				return cached.analysis;
			},

			setCachedPostAnalysis: (postId, analysis) =>
				set((state) => ({
					postAnalysisCache: {
						...state.postAnalysisCache,
						[postId]: { analysis, generatedAt: Date.now() },
					},
				})),

			getCachedPostAnalysis: (postId) => {
				const cached = get().postAnalysisCache[postId];
				if (!cached) return null;
				if (Date.now() - cached.generatedAt > CACHE_EXPIRY_MS) return null;
				return cached.analysis;
			},

			clearAICache: () =>
				set({
					diagnosisCache: {},
					viralAnalysisCache: {},
					postAnalysisCache: {},
				}),
		}),
		{
			name: "analytics-ai-cache",
			onRehydrateStorage: () => (state) => {
				if (!state) return;
				const now = Date.now();
				const cleanDiagnosis: typeof state.diagnosisCache = {};
				for (const [k, v] of Object.entries(state.diagnosisCache)) {
					if (now - v.generatedAt < CACHE_EXPIRY_MS) cleanDiagnosis[k] = v;
				}
				const cleanViral: typeof state.viralAnalysisCache = {};
				for (const [k, v] of Object.entries(state.viralAnalysisCache)) {
					if (now - v.generatedAt < CACHE_EXPIRY_MS) cleanViral[k] = v;
				}
				const cleanPost: typeof state.postAnalysisCache = {};
				for (const [k, v] of Object.entries(state.postAnalysisCache)) {
					if (now - v.generatedAt < CACHE_EXPIRY_MS) cleanPost[k] = v;
				}
				state.diagnosisCache = cleanDiagnosis;
				state.viralAnalysisCache = cleanViral;
				state.postAnalysisCache = cleanPost;
			},
		},
	),
);
