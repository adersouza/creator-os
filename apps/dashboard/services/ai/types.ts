/**
 * Shared AI types — extracted to break circular deps between
 * analytics.ts ↔ ideas.ts ↔ contextEngine.ts.
 */

import type { ExtractedStyle } from "../../types/voice.js";

export interface PostIdea {
	id: string;
	content: string;
	viralScore: number; // 0-100
	category:
		| "hook"
		| "story"
		| "question"
		| "list"
		| "controversial"
		| "educational"
		| "personal";
	mediaType: "text" | "image" | "carousel" | "video";
	mediaSuggestion?: string | undefined;
	inspiration?: string | undefined; // What inspired this idea
	hooks: string[]; // Alternative hook options
	hashtags: string[];
	estimatedEngagement: {
		likes: number;
		replies: number;
		shares: number;
	};
	tone: string;
}

// Voice profile for personalized AI content generation
export interface VoiceProfile {
	voice_profile?: string | undefined; // Description of writing voice/persona
	focus_topics?: string[] | undefined; // Topics to emphasize
	avoid_topics?: string[] | undefined; // Topics to avoid
	avoid_words?: string[] | undefined; // Specific words/phrases to avoid
	emoji_usage?: "none" | "minimal" | "moderate" | "heavy" | undefined;
	cta_style?: "none" | "link_in_bio" | "dm_me" | "subscribe" | undefined;
	extracted_style?: ExtractedStyle | undefined; // AI-extracted writing DNA from top posts
}

export interface UserEngagementStats {
	avgLikes: number;
	avgReplies: number;
	avgShares: number;
}
