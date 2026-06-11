/**
 * Shared types, interfaces, and utilities for the Low-Hanging Fruit engine.
 * All sub-modules import from here to avoid circular dependencies.
 */

import { getSupabase, getSupabaseAny } from "../supabase.js";

// ── Exported Types ──────────────────────────────────────────────────────────

export type ConfidenceLevel = "high" | "medium" | "low";

export type RecommendationCategory =
	| "timing"
	| "content"
	| "engagement"
	| "frequency"
	| "accessibility"
	| "format"
	| "health";

export interface Recommendation {
	id: string;
	title: string;
	description: string;
	impactScore: number; // 1-10
	effortScore: number; // 1-5
	roi: number; // impactScore / effortScore
	dataPoint: string;
	icon: string; // emoji
	confidence: ConfidenceLevel;
	confidenceLabel: string;
	ctaPath: string | null; // in-app route to take action, null if not actionable
	category: RecommendationCategory;
	baselineValue: number; // metric value when rec was generated (0-1 scale)
}

export interface SolvedRecommendation {
	id: string;
	title: string;
	icon: string;
	category: RecommendationCategory;
	improvementPct: number; // e.g. 133 means 133% improvement
	baselineValue: number;
	currentValue: number;
}

export interface RegressedRecommendation {
	id: string;
	title: string;
	icon: string;
	category: RecommendationCategory;
	regressionPct: number;
	daysSinceRegression: number;
	status: "regressed" | "faded";
}

export interface LowHangingFruitResult {
	recommendations: Recommendation[];
	solved: SolvedRecommendation[];
	regressed: RegressedRecommendation[];
}

export interface LhfPost {
	id?: string | undefined;
	published_at?: string | undefined;
	media_type?: string | undefined;
	alt_text?: string | undefined;
	content?: string | undefined;
	likes_count?: number | undefined;
	replies_count?: number | undefined;
	reposts_count?: number | undefined;
	shares_count?: number | undefined;
	views_count?: number | undefined;
	views?: number | undefined;
	reach?: number | undefined;
	engagement_rate?: number | undefined;
	platform?: string | undefined;
	[key: string]: unknown;
}

export interface BestHourEntry {
	hour: number;
	avgEngagement?: number | undefined;
	[key: string]: unknown;
}

// ── DB Accessors ────────────────────────────────────────────────────────────

export const db = () => getSupabase();
export const dbAny = () => getSupabaseAny();

// ── Confidence Helper ───────────────────────────────────────────────────────

export function getConfidence(sampleSize: number): {
	confidence: ConfidenceLevel;
	confidenceLabel: string;
} {
	if (sampleSize >= 30)
		return {
			confidence: "high",
			confidenceLabel: `Strong evidence from your last ${sampleSize} posts`,
		};
	if (sampleSize >= 10)
		return { confidence: "medium", confidenceLabel: "Based on recent trends" };
	return {
		confidence: "low",
		confidenceLabel: "Early data — monitor after more posts",
	};
}
