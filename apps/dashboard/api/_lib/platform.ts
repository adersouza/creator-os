/**
 * Platform types for API routes.
 * Mirrors src/types/platform.ts — kept here for Vercel bundler compatibility
 * since @vercel/node does not resolve @/src/ path aliases.
 */

/** A supported social platform (Threads or Instagram). */
export type Platform = "threads" | "instagram";

/** Platform filter including the "all" option for multi-platform views. */
export type PlatformFilter = "threads" | "instagram" | "all";
