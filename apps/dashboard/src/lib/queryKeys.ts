/**
 * Centralized React Query key factory.
 *
 * All TanStack Query hooks should build their `queryKey` through this module
 * rather than hand-rolling a string array. Benefits:
 *  - One typo doesn't silently break cache invalidation for a given domain.
 *  - `queryClient.invalidateQueries({ queryKey: queryKeys.accounts.all })`
 *    invalidates every account-scoped query in one call (prefix match).
 *  - Key shape is visible in one place when adding params (e.g., adding a
 *    `timeframe` to a metrics query).
 *
 * Shape convention: every key is anchored by a user key (the auth user id or
 * null when signed out) so that re-logging-in as a different user doesn't
 * replay stale cache for the previous session. Hooks that don't need the user
 * scope (e.g., pure client-side computed results keyed on a hash) skip it.
 */

type UserKey = string | null;

export const queryKeys = {
  fleet: {
    all: ['fleet'] as const,
    metrics: (userKey: UserKey, timeframe: string, platform: string) =>
      ['fleetMetrics', userKey, timeframe, platform] as const,
    healthAll: ['fleetHealth'] as const,
    health: (userKey: UserKey) => ['fleetHealth', userKey] as const,
    totals: (userKey: UserKey) => ['fleetTotals', userKey] as const,
    profileVisits: (userKey: UserKey, periodDays: number) =>
      ['fleetProfileVisits', userKey, periodDays] as const,
  },

  accounts: {
    all: ['accounts'] as const,
    connectedAll: ['connectedAccounts'] as const,
    connected: (userKey: UserKey) => ['connectedAccounts', 'v2', userKey] as const,
    groupsAll: ['accountGroups'] as const,
    groups: (userKey: UserKey) => ['accountGroups', userKey] as const,
    vanity: (userKey: UserKey, timeframeDays: number) =>
      ['vanityAccounts', userKey, timeframeDays] as const,
  },

  posts: {
    all: ['posts'] as const,
    top: (userKey: UserKey, timeframe: string, platform: string) =>
      ['topPosts', userKey, timeframe, platform] as const,
    nextUp: (userKey: UserKey, platform: string, timeframe: string, windowHours: number) =>
      ['nextUpPosts', userKey, platform, timeframe, windowHours] as const,
    nextUpAll: ['nextUpPosts'] as const,
    needsAttentionAll: ['needsAttention'] as const,
    needsAttention: (
      userKey: UserKey,
      platform: string,
      timeframe: string,
      scopedAccountId?: string | null,
      scopedPlatform?: string | null,
      groupId?: string | null,
      accountIdsKey?: string | null,
    ) =>
      ['needsAttention', userKey, platform, timeframe, scopedAccountId ?? null, scopedPlatform ?? null, groupId ?? 'all', accountIdsKey ?? null] as const,
    latestDraft: (userKey: UserKey, revision?: number) =>
      ['latestDraft', userKey, revision] as const,
  },

  analytics: {
    all: ['analytics'] as const,
    hookPatterns: (userKey: UserKey, accountId?: string | null) =>
      ['hookPatterns', userKey, accountId ?? null] as const,
    eqsTrendSubtitle: (cacheKey: string) => ['eqsTrendSubtitle', cacheKey] as const,
    reelRetention: (
      userKey: UserKey,
      timeframeDays: number,
      instagramAccountId?: string | null,
    ) => ['reelRetention', userKey, timeframeDays, instagramAccountId ?? null] as const,
    replyChainDistribution: (userKey: UserKey, timeframeDays: number) =>
      ['replyChainDistribution', userKey, timeframeDays] as const,
    bestPostingTimes: (userKey: UserKey, accountId?: string | null) =>
      ['bestPostingTimes', userKey, accountId ?? null] as const,
    competitorPulse: (userKey: UserKey) => ['competitorPulse', userKey] as const,
    competitorSurprises: (userKey: UserKey) =>
      ['competitorSurprises', userKey] as const,
    crossAccountPatterns: (userKey: UserKey) =>
      ['crossAccountPatterns', userKey] as const,
  },

  system: {
    all: ['system'] as const,
    status: (userKey: UserKey) => ['systemStatus', userKey] as const,
    activityEvents: (userKey: UserKey) => ['activityEvents', userKey] as const,
    trialStatus: (userKey: UserKey) => ['trialStatus', userKey] as const,
    reliabilitySummary: (windowHours: number) =>
      ['reliabilitySummary', windowHours] as const,
    instagramPublishingLimits: (userKey: UserKey) =>
      ['instagramPublishingLimits', userKey] as const,
  },

  calendar: {
    all: ['calendarPosts'] as const,
    posts: (userKey: UserKey, weekCacheKey: number, normalizedWeekSpan: number) =>
      ['calendarPosts', userKey, weekCacheKey, normalizedWeekSpan] as const,
    userPosts: (userKey: UserKey) => ['calendarPosts', userKey] as const,
  },

  listening: {
    snapshotAll: ['listeningSnapshot'] as const,
    snapshot: (userKey: UserKey, workspaceId?: string | null) =>
      ['listeningSnapshot', userKey, workspaceId ?? null] as const,
  },

  operator: {
    snapshotAll: ['operatorSnapshot'] as const,
    snapshot: (userKey: UserKey, capacityStart?: string | null) =>
      ['operatorSnapshot', userKey, capacityStart ?? null] as const,
  },

  branding: {
    all: ['branding'] as const,
    agency: (userKey: UserKey) => ['agencyBranding', userKey] as const,
  },

  onboarding: {
    all: ['onboardingState'] as const,
    state: (userKey: UserKey) => ['onboardingState', userKey] as const,
  },
} as const;

export type QueryKeys = typeof queryKeys;
