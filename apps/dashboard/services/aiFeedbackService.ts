// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * aiFeedbackService — Track which AI suggestions users actually use.
 * This data feeds back into prompt engineering for better suggestions over time.
 */

import type { Json } from "../types/supabase.js";
import { createServiceLogger, supabase } from "./api/shared.js";

const log = createServiceLogger("aiFeedback");

export type AIFeature =
	| "reply_suggestion"
	| "post_idea"
	| "content_variation"
	| "dm_response"
	| "hashtag_set"
	| "caption"
	| "repurpose";

interface TrackOptions {
	feature: AIFeature;
	suggestionIndex?: number | undefined;
	content?: string | undefined;
	wasEdited?: boolean | undefined;
	context?: Record<string, unknown> | undefined;
}

type FeedbackContext = Record<string, Json | undefined>;

function isJsonValue(value: unknown): value is Json {
	if (
		value === null ||
		typeof value === "string" ||
		typeof value === "number" ||
		typeof value === "boolean"
	) {
		return true;
	}

	if (Array.isArray(value)) {
		return value.every((item) => isJsonValue(item));
	}

	if (typeof value !== "object") {
		return false;
	}

	return Object.values(value).every(
		(item) => item === undefined || isJsonValue(item),
	);
}

function sanitizeContext(
	context: Record<string, unknown> | undefined,
): FeedbackContext | null {
	if (!context) {
		return null;
	}

	const sanitized: FeedbackContext = {};
	for (const [key, value] of Object.entries(context)) {
		if (value !== undefined && isJsonValue(value)) {
			sanitized[key] = value;
		}
	}

	return Object.keys(sanitized).length > 0 ? sanitized : null;
}

function getContextTone(context: Json | null | undefined): string | null {
	if (!context || Array.isArray(context) || typeof context !== "object") {
		return null;
	}

	const tone = context.tone;
	if (typeof tone === "string" && tone.length > 0) {
		return tone;
	}

	const style = context.style;
	return typeof style === "string" && style.length > 0 ? style : null;
}

/**
 * Track when a user picks/uses an AI suggestion.
 */
export async function trackSuggestionUsed(opts: TrackOptions): Promise<void> {
	try {
		const user = (await supabase.auth.getUser()).data.user;
		if (!user) return;

		// Get workspace_id from profile
		const { data: profile } = await supabase
			.from("profiles")
			.select("workspace_id")
			.eq("id", user.id)
			.maybeSingle();

		await supabase.from("ai_feedback").insert({
			user_id: user.id,
			workspace_id: profile?.workspace_id || null,
			feature: opts.feature,
			suggestion_index: opts.suggestionIndex ?? null,
			suggestion_content: opts.content?.substring(0, 2000) || null,
			was_edited: opts.wasEdited ?? false,
			was_used: true,
			context: sanitizeContext(opts.context),
		});

		// Invalidate cached feedback context so next AI call uses fresh data
		try {
			const { invalidateFeedbackCache } = await import(
				"../utils/buildFeedbackContext.js"
			);
			invalidateFeedbackCache();
		} catch {
			/* non-critical */
		}
	} catch (err) {
		// Non-critical — don't block user flow
		log.error("Track error:", err);
	}
}

/**
 * Track when a user skips/dismisses all AI suggestions.
 */
export async function trackSuggestionSkipped(
	feature: AIFeature,
	context?: Record<string, unknown>,
): Promise<void> {
	try {
		const user = (await supabase.auth.getUser()).data.user;
		if (!user) return;

		const { data: profile } = await supabase
			.from("profiles")
			.select("workspace_id")
			.eq("id", user.id)
			.maybeSingle();

		await supabase.from("ai_feedback").insert({
			user_id: user.id,
			workspace_id: profile?.workspace_id || null,
			feature,
			was_used: false,
			context: sanitizeContext(context),
		});

		// Invalidate cached feedback context so next AI call uses fresh data
		try {
			const { invalidateFeedbackCache } = await import(
				"../utils/buildFeedbackContext.js"
			);
			invalidateFeedbackCache();
		} catch {
			/* non-critical */
		}
	} catch (err) {
		log.error("Track skip error:", err);
	}
}

/**
 * Analyze past feedback to determine user's preferred style for a feature.
 * Returns a hint string to inject into AI prompts.
 */
export async function getPreferredStyle(
	feature: AIFeature,
): Promise<string | null> {
	try {
		const user = (await supabase.auth.getUser()).data.user;
		if (!user) return null;

		// Get last 50 used suggestions for this feature
		const { data, error } = await supabase
			.from("ai_feedback")
			.select("suggestion_content, context, was_edited")
			.eq("user_id", user.id)
			.eq("feature", feature)
			.eq("was_used", true)
			.order("created_at", { ascending: false })
			.limit(50);

		if (error || !data || data.length < 5) return null;

		// Extract tone preferences from context
		const tones: Record<string, number> = {};
		for (const row of data) {
			const tone = getContextTone(row.context);
			if (tone) {
				tones[tone] = (tones[tone] || 0) + 1;
			}
		}

		const editRate = data.filter((r) => r.was_edited).length / data.length;

		// Build preference hint
		const parts: string[] = [];

		// Top tone
		const topTone = Object.entries(tones).sort((a, b) => b[1] - a[1])[0];
		if (topTone && topTone[1] >= 3) {
			parts.push(
				`The user typically prefers a ${topTone[0]} tone (chosen ${topTone[1]}/${data.length} times).`,
			);
		}

		// Edit rate
		if (editRate > 0.5) {
			parts.push(
				"The user often edits AI suggestions before using them — generate content that's close to their style but leaves room for personalization.",
			);
		} else if (editRate < 0.1) {
			parts.push(
				"The user rarely edits AI suggestions — generate polished, ready-to-use content.",
			);
		}

		// Include 2-3 snippets of previously accepted content as concrete examples
		const acceptedSamples = data
			.filter((r) => r.suggestion_content && !r.was_edited)
			.slice(0, 3)
			.map((r) => `"${(r.suggestion_content ?? "").substring(0, 120)}"`);
		if (acceptedSamples.length >= 2) {
			parts.push(
				`Content the user accepted as-is: ${acceptedSamples.join("; ")}`,
			);
		}

		return parts.length > 0 ? parts.join(" ") : null;
	} catch (err) {
		log.error("Get preferred style error:", err);
		return null;
	}
}

/**
 * Get a user-facing "What AI Learned About You" profile summary.
 * Returns structured insights suitable for a Settings panel or dashboard card.
 */
export interface LearnedProfile {
	totalInteractions: number;
	preferredTones: { tone: string; percentage: number }[];
	editBehavior: { rate: number; trend: "improving" | "stable" | "increasing" };
	bestFeature: { feature: string; acceptanceRate: number } | null;
	contentLengthPreference: { avg: number; range: string } | null;
	positionPreference: { position: number; percentage: number } | null;
	topPatterns: string[];
}

export async function getLearnedProfile(
	days: number = 90,
): Promise<LearnedProfile | null> {
	try {
		const user = (await supabase.auth.getUser()).data.user;
		if (!user) return null;

		const since = new Date();
		since.setDate(since.getDate() - days);

		const { data, error } = await supabase
			.from("ai_feedback")
			.select(
				"feature, was_used, was_edited, suggestion_index, suggestion_content, context, created_at",
			)
			.eq("user_id", user.id)
			.gte("created_at", since.toISOString())
			.order("created_at", { ascending: true });

		if (error || !data || data.length < 5) return null;

		const rows = data as {
			feature: string;
			was_used: boolean;
			was_edited: boolean | null;
			suggestion_index: number | null;
			suggestion_content: string | null;
			context: FeedbackContext | null;
			created_at: string;
		}[];

		const totalInteractions = rows.length;

		// Tone preferences
		const toneCounts: Record<string, number> = {};
		let toneTotal = 0;
		for (const r of rows) {
			if (!r.was_used) continue;
			const tone = getContextTone(r.context);
			if (tone) {
				toneCounts[tone] = (toneCounts[tone] || 0) + 1;
				toneTotal++;
			}
		}
		const preferredTones = Object.entries(toneCounts)
			.sort((a, b) => b[1] - a[1])
			.slice(0, 5)
			.map(([tone, count]) => ({
				tone,
				percentage: toneTotal > 0 ? Math.round((count / toneTotal) * 100) : 0,
			}));

		// Edit behavior + trend (compare first half vs second half)
		const usedRows = rows.filter((r) => r.was_used);
		const totalEdited = usedRows.filter((r) => r.was_edited).length;
		const editRate =
			usedRows.length > 0
				? Math.round((totalEdited / usedRows.length) * 100)
				: 0;
		let editTrend: "improving" | "stable" | "increasing" = "stable";
		if (usedRows.length >= 10) {
			const mid = Math.floor(usedRows.length / 2);
			const firstHalfEdit =
				usedRows.slice(0, mid).filter((r) => r.was_edited).length / mid;
			const secondHalfEdit =
				usedRows.slice(mid).filter((r) => r.was_edited).length /
				(usedRows.length - mid);
			if (secondHalfEdit < firstHalfEdit - 0.05) editTrend = "improving";
			else if (secondHalfEdit > firstHalfEdit + 0.05) editTrend = "increasing";
		}

		// Best feature by acceptance rate
		const featureStats: Record<string, { used: number; total: number }> = {};
		for (const r of rows) {
			if (!featureStats[r.feature])
				featureStats[r.feature] = { used: 0, total: 0 };
			featureStats[r.feature]!.total++;
			if (r.was_used) featureStats[r.feature]!.used++;
		}
		const bestFeatureEntry = Object.entries(featureStats)
			.filter(([, s]) => s.total >= 3)
			.sort((a, b) => b[1].used / b[1].total - a[1].used / a[1].total)[0];
		const bestFeature = bestFeatureEntry
			? {
					feature: bestFeatureEntry[0],
					acceptanceRate: Math.round(
						(bestFeatureEntry[1].used / bestFeatureEntry[1].total) * 100,
					),
				}
			: null;

		// Content length preference
		const lengths = usedRows
			.filter((r) => r.suggestion_content)
			.map((r) => r.suggestion_content?.length ?? 0);
		let contentLengthPreference: LearnedProfile["contentLengthPreference"] =
			null;
		if (lengths.length >= 5) {
			lengths.sort((a, b) => a - b);
			const avg = Math.round(
				lengths.reduce((s, l) => s + l, 0) / lengths.length,
			);
			const p25 = lengths[Math.floor(lengths.length * 0.25)];
			const p75 = lengths[Math.floor(lengths.length * 0.75)];
			contentLengthPreference = { avg, range: `${p25}-${p75} chars` };
		}

		// Position preference
		const positionCounts: Record<number, number> = {};
		let posTotal = 0;
		for (const r of usedRows) {
			if (r.suggestion_index != null) {
				positionCounts[r.suggestion_index] =
					(positionCounts[r.suggestion_index] || 0) + 1;
				posTotal++;
			}
		}
		const topPos = Object.entries(positionCounts).sort(
			(a, b) => Number(b[1]) - Number(a[1]),
		)[0];
		const positionPreference =
			topPos && posTotal > 0
				? {
						position: Number(topPos[0]) + 1,
						percentage: Math.round((Number(topPos[1]) / posTotal) * 100),
					}
				: null;

		// Generate human-readable pattern descriptions
		const topPatterns: string[] = [];
		if (preferredTones.length > 0 && preferredTones[0]!.percentage >= 30) {
			topPatterns.push(
				`You prefer ${preferredTones[0]!.tone} tone ${preferredTones[0]!.percentage}% of the time`,
			);
		}
		if (editTrend === "improving") {
			topPatterns.push(
				"AI suggestions are matching your style better over time (fewer edits)",
			);
		} else if (editRate < 15) {
			topPatterns.push(
				"You rarely edit AI suggestions — they match your voice well",
			);
		} else if (editRate > 50) {
			topPatterns.push(
				"You frequently customize AI suggestions before using them",
			);
		}
		if (bestFeature && bestFeature.acceptanceRate >= 70) {
			topPatterns.push(
				`${bestFeature.feature.replace(/_/g, " ")} has ${bestFeature.acceptanceRate}% acceptance rate`,
			);
		}
		if (positionPreference && positionPreference.percentage >= 40) {
			topPatterns.push(
				`You most often pick suggestion #${positionPreference.position}`,
			);
		}
		if (contentLengthPreference) {
			topPatterns.push(
				`Preferred content length: ${contentLengthPreference.range}`,
			);
		}

		return {
			totalInteractions,
			preferredTones,
			editBehavior: { rate: editRate, trend: editTrend },
			bestFeature,
			contentLengthPreference,
			positionPreference,
			topPatterns,
		};
	} catch (err) {
		log.error("Get learned profile error:", err);
		return null;
	}
}

/**
 * Get usage statistics for a workspace.
 */
export async function getUsageStats(): Promise<{
	totalUsed: number;
	totalSkipped: number;
	byFeature: Record<string, { used: number; skipped: number }>;
} | null> {
	try {
		const user = (await supabase.auth.getUser()).data.user;
		if (!user) return null;

		const { data, error } = await supabase
			.from("ai_feedback")
			.select("feature, was_used")
			.eq("user_id", user.id);

		if (error || !data) return null;

		const byFeature: Record<string, { used: number; skipped: number }> = {};
		let totalUsed = 0;
		let totalSkipped = 0;

		for (const row of data) {
			if (!byFeature[row.feature]) {
				byFeature[row.feature] = { used: 0, skipped: 0 };
			}
			if (row.was_used) {
				byFeature[row.feature]!.used++;
				totalUsed++;
			} else {
				byFeature[row.feature]!.skipped++;
				totalSkipped++;
			}
		}

		return { totalUsed, totalSkipped, byFeature };
	} catch (err) {
		log.error("Get usage stats error:", err);
		return null;
	}
}
