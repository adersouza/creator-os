import { ViewMode, Platform } from "../types";

/**
 * URL slug -> ViewMode mapping
 * Used to derive the current view from the URL path
 */
export const SLUG_TO_VIEWMODE: Record<string, ViewMode> = {
  dashboard: ViewMode.DASHBOARD,
  calendar: ViewMode.CALENDAR,
  posts: ViewMode.POSTS,
  replies: ViewMode.REPLIES,
  analytics: ViewMode.ANALYTICS,
  discover: ViewMode.DISCOVER,
  competitors: ViewMode.COMPETITORS,
  media: ViewMode.MEDIA,
  groups: ViewMode.GROUPS,
  team: ViewMode.TEAM,
  settings: ViewMode.SETTINGS,
  "auto-poster": ViewMode.AUTO_POSTER,
  "ig-analytics": ViewMode.IG_ANALYTICS,
  hashtags: ViewMode.IG_HASHTAGS,
  mentions: ViewMode.IG_MENTIONS,
  inbox: ViewMode.IG_INBOX,
  collabs: ViewMode.IG_COLLABS,
  stories: ViewMode.IG_STORIES,
  "dm-templates": ViewMode.IG_DM_TEMPLATES,
  overview: ViewMode.OVERVIEW,
  approvals: ViewMode.APPROVAL_QUEUE,
  listening: ViewMode.SOCIAL_LISTENING,
  "creator-tools": ViewMode.CREATOR_TOOLS,
  "unified-inbox": ViewMode.UNIFIED_INBOX,
  health: ViewMode.SYSTEM_HEALTH,
  reports: ViewMode.REPORTS,
  links: ViewMode.LINK_IN_BIO,
  explore: ViewMode.EXPLORE,
  "creator-hub": ViewMode.CREATOR_HUB,
  "ai-studio": ViewMode.AI_STUDIO,
};

/**
 * ViewMode -> URL slug mapping
 */
export const VIEWMODE_TO_SLUG: Record<ViewMode, string> = {
  [ViewMode.DASHBOARD]: "dashboard",
  [ViewMode.CALENDAR]: "calendar",
  [ViewMode.POSTS]: "posts",
  [ViewMode.REPLIES]: "replies",
  [ViewMode.ANALYTICS]: "analytics",
  [ViewMode.DISCOVER]: "discover",
  [ViewMode.COMPETITORS]: "competitors",
  [ViewMode.MEDIA]: "media",
  [ViewMode.GROUPS]: "groups",
  [ViewMode.TEAM]: "team",
  [ViewMode.SETTINGS]: "settings",
  [ViewMode.AUTO_POSTER]: "auto-poster",
  [ViewMode.IG_ANALYTICS]: "ig-analytics",
  [ViewMode.IG_HASHTAGS]: "hashtags",
  [ViewMode.IG_MENTIONS]: "mentions",
  [ViewMode.IG_INBOX]: "inbox",
  [ViewMode.IG_COLLABS]: "collabs",
  [ViewMode.IG_STORIES]: "stories",
  [ViewMode.IG_DM_TEMPLATES]: "dm-templates",
  [ViewMode.OVERVIEW]: "overview",
  [ViewMode.APPROVAL_QUEUE]: "approvals",
  [ViewMode.SOCIAL_LISTENING]: "listening",
  [ViewMode.CREATOR_TOOLS]: "creator-tools",
  [ViewMode.UNIFIED_INBOX]: "unified-inbox",
  [ViewMode.SYSTEM_HEALTH]: "health",
  [ViewMode.REPORTS]: "reports",
  [ViewMode.LINK_IN_BIO]: "links",
  [ViewMode.EXPLORE]: "explore",
  [ViewMode.CREATOR_HUB]: "creator-hub",
  [ViewMode.AI_STUDIO]: "ai-studio",
};

/**
 * Build a full path like /threads/dashboard
 */
export function getViewPath(platform: Platform, viewMode: ViewMode): string {
  const slug = VIEWMODE_TO_SLUG[viewMode] || "dashboard";
  return `/${platform}/${slug}`;
}

/**
 * Slugs valid for each platform.
 * Used to validate whether a slug is available on a given platform.
 */
export const PLATFORM_SLUGS: Record<Platform, Set<string>> = {
  threads: new Set([
    "overview",
    "dashboard",
    "calendar",
    "posts",
    "replies",
    "analytics",
    "discover",
    "competitors",
    "media",
    "groups",
    "team",
    "settings",
    "auto-poster",
    "approvals",
    "listening",
    "creator-tools",
    "unified-inbox",
    "health",
    "reports",
    "links",
    "explore",
    "creator-hub",
    "ai-studio",
  ]),
  instagram: new Set([
    "overview",
    "dashboard",
    "calendar",
    "posts",
    "analytics",
    "ig-analytics",
    "hashtags",
    "mentions",
    "inbox",
    "collabs",
    "stories",
    "dm-templates",
    "competitors",
    "media",
    "groups",
    "team",
    "settings",
    "approvals",
    "listening",
    "creator-tools",
    "unified-inbox",
    "health",
    "reports",
    "links",
    "explore",
    "creator-hub",
    "ai-studio",
  ]),
  bluesky: new Set([
    "dashboard",
    "posts",
    "analytics",
    "settings",
  ]),
  tiktok: new Set([
    "dashboard",
    "posts",
    "analytics",
    "settings",
  ]),
};

/**
 * Check if a slug exists on the target platform.
 * Returns the slug if valid, or "dashboard" as fallback.
 */
export function resolveSlugForPlatform(
  slug: string,
  targetPlatform: Platform,
): string {
  if (PLATFORM_SLUGS[targetPlatform].has(slug)) {
    return slug;
  }
  return "dashboard";
}

/** Valid platform values */
export const VALID_PLATFORMS: Platform[] = ["threads", "instagram", "bluesky", "tiktok"];

export function isValidPlatform(value: string): value is Platform {
  return VALID_PLATFORMS.includes(value as Platform);
}
