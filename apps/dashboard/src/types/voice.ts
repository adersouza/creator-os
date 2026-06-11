/**
 * Voice Profile Types
 * Centralized types for voice/persona configuration
 */

// Extracted style DNA from analyzing user's top posts
export interface ExtractedStyle {
  sentence_patterns: {
    avg_length: "short" | "medium" | "long";
    structure: "simple" | "compound" | "fragmented" | "mixed";
    rhythm: string; // description of cadence
  };
  hooks: {
    patterns: string[]; // 3-5 opening patterns they use
    examples: string[]; // direct quotes of their best hooks
  };
  closings: {
    patterns: string[]; // how they end posts
    cta_style: "none" | "soft" | "direct" | "link-focused";
  };
  emoji_usage: {
    frequency: "none" | "rare" | "moderate" | "heavy";
    placement: "start" | "end" | "inline" | "emphasis";
    favorites: string[]; // most used emojis
  };
  vocabulary: {
    signature_words: string[]; // words they overuse intentionally
    avoid_words: string[]; // words they never use
    tone_markers: string[]; // phrases that define their voice
  };
  formatting: {
    line_breaks: "minimal" | "moderate" | "heavy";
    lists: boolean;
    caps_usage: "none" | "emphasis" | "shouting";
  };
  // New fields for better voice matching
  tone: {
    vibe: string; // e.g., "casual, bold, slightly confrontational, relatable"
    energy: "low-key" | "moderate" | "high-energy" | "chaotic";
  };
  length: {
    typical_chars: string; // e.g., "80-180"
    preference: "very-short" | "short" | "medium" | "long";
  };
  punctuation: {
    quirks: string[]; // e.g., ["lots of !", "minimal commas", "ellipsis for drama"]
    question_frequency: "never" | "rare" | "often" | "signature";
  };
  extracted_at?: string | undefined; // ISO timestamp of when extraction occurred
}

// Voice profile for personalized AI content generation
export interface VoiceProfile {
  voice_profile?: string | undefined; // Description of writing voice/persona
  focus_topics?: string[] | undefined; // Topics to emphasize
  avoid_topics?: string[] | undefined; // Topics to avoid
  avoid_words?: string[] | undefined; // Specific words/phrases to avoid
  emoji_usage?: "none" | "minimal" | "moderate" | "heavy" | undefined;
  cta_style?: "none" | "link_in_bio" | "dm_me" | "subscribe" | undefined;
  tone?: string | undefined; // Tone of voice (edgy, professional, casual, etc.)
  extracted_style?: ExtractedStyle | undefined; // AI-extracted style DNA from top posts
}
