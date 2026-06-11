/**
 * Shared API Handler Helpers
 *
 * Central barrel export for all handler helpers.
 */

export type { AvatarProxyConfig } from "./avatarProxy.js";
export { handleAvatarProxy } from "./avatarProxy.js";

export type {
	AnalyticsQueryParams,
	ParseAnalyticsOptions,
} from "./parseAnalyticsQuery.js";
export { parseAnalyticsQuery } from "./parseAnalyticsQuery.js";
export {
	verifyAccountOwnership,
	verifyAnyAccountOwnership,
	verifyCompetitorOwnership,
	verifyIgAccountOwnership,
} from "./verifyOwnership.js";
export type { AuthUser } from "./withAuthAndBody.js";
export {
	withAuthAndBody,
	withAuthAndQuery,
	withAuthOnly,
} from "./withAuthAndBody.js";
