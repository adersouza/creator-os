/**
 * Media Validation — top-level re-export.
 *
 * Avoids auto-poster and other callers needing to import from deep
 * inside the cron directory tree.
 */
export { checkMediaUrlAccessible } from "./cron/scheduled-posts/mediaValidation.js";
