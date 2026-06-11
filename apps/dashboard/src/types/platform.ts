/**
 * A supported social platform (Threads or Instagram).
 *
 * Note: the root types.ts has a broader Platform that includes future
 * platforms (bluesky, tiktok). Import from here for active-only code.
 */
export type Platform = "threads" | "instagram";

/** Platform filter including the "all" option for multi-platform views. */
export type PlatformFilter = "threads" | "instagram" | "all";
