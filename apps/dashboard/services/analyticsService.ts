/**
 * Legacy compatibility barrel.
 *
 * Frontend code must import `@/services/analyticsService`; this file exists
 * only for the quarantined root `services/ai*` graph that is still imported by
 * API cron compatibility paths.
 */

export * from "../src/services/analyticsService.js";
export { default } from "../src/services/analyticsService.js";
