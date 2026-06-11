/**
 * Feature Flags Configuration
 *
 * Toggle features on/off for different deployment scenarios.
 */

export const FEATURE_FLAGS = {
  // Individual feature flags
  ENABLE_AUTO_POSTER: true,

  ENABLE_SMART_FILL: true,

  ENABLE_BULK_OPERATIONS: true,

  ENABLE_AI_CONTENT_GENERATION: true,

  // Empire tier visibility (includes Auto-Poster)
  ENABLE_EMPIRE_TIER: true,

  // Instagram integration
  ENABLE_INSTAGRAM_POSTING: true,

  ENABLE_INSTAGRAM_STORIES: true,

  ENABLE_IG_BUSINESS_DISCOVERY: true,

  // Platform-specific dashboard views (Phase 3: dashboard differentiation)
  USE_PLATFORM_DASHBOARDS: true,
} as const;
