/**
 * Types for AI Content Helpers:
 * - Content Repurposer
 * - Hashtag Research
 * - Thread/Carousel Builder
 */

export interface RepurposedPart {
  type: "carousel" | "story" | "reel" | "thread" | "condensed" | "ig-caption" | "threads-native";
  title?: string | undefined;
  content: string;
  order: number;
  sceneDescription?: string | undefined;
}

export interface HashtagSuggestion {
  tag: string;
  category: "niche" | "broad" | "trending";
  estimatedReach: "low" | "medium" | "high";
  competition: "low" | "medium" | "high";
  verified?: boolean | undefined;
  realAvgEngagement?: number | undefined;
}

export interface HashtagSet {
  name: string;
  tags: string[];
  createdAt: string;
}

export interface ThreadPart {
  id: string;
  content: string;
  type: "hook" | "body" | "cta";
  charCount: number;
  order: number;
}

export interface CarouselSlide {
  id: string;
  title: string;
  body: string;
  order: number;
}

export type RepurposeFormat =
  | "carousel"
  | "story"
  | "reel"
  | "thread"
  | "condensed"
  | "ig-caption"
  | "threads-native";

export interface WeeklyPlanPost {
  day: string;
  time: string;
  content: string;
  contentType: "text" | "image" | "carousel" | "video";
  hook: string;
}

export interface WeeklyPlan {
  theme: string;
  strategy: string;
  posts: WeeklyPlanPost[];
}

export interface RepurposeOption {
  format: RepurposeFormat;
  label: string;
  description: string;
  icon: string;
}
