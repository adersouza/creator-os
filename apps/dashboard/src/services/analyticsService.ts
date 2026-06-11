/**
 * Analytics Service — PostHog integration.
 *
 * Canonical frontend analytics helper. Keep root-level services quarantined for
 * legacy server compatibility only; app code should import this module through
 * `@/services/analyticsService`.
 */

import { analytics, hasConsent } from "@/lib/analytics";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { useWorkspaceStore } from "@/stores/useWorkspaceStore";
import logger from "@/utils/logger";

export const ANALYTICS_EVENTS = {
	POST_CREATED: "post_created",
	POST_SCHEDULED: "post_scheduled",
	POST_PUBLISHED: "post_published",
	POST_DELETED: "post_deleted",
	ACCOUNT_CONNECTED: "account_connected",
	ANALYTICS_VIEWED: "analytics_viewed",
	COMPETITOR_ADDED: "competitor_added",
	COMPETITOR_REMOVED: "competitor_removed",
	COMPETITOR_SYNCED: "competitor_synced",
	AI_CONTENT_GENERATED: "ai_content_generated",
	AI_REPHRASE_USED: "ai_rephrase_used",
	AI_ADAPT_MEDIA_USED: "ai_adapt_media_used",
	AI_BATCH_GENERATED: "ai_batch_generated",
	REPLY_SENT: "reply_sent",
	INBOX_VIEWED: "inbox_viewed",
	MEDIA_UPLOADED: "media_uploaded",
	VIEW_CHANGED: "view_changed",
	PAGE_VIEWED: "page_viewed",
	AUTO_POST_ENABLED: "auto_post_enabled",
	AUTO_POST_DISABLED: "auto_post_disabled",
	ONBOARDING_COMPLETED: "onboarding_completed",
	POST_CROSS_POSTED: "post_cross_posted",
	ERROR_OCCURRED: "error_occurred",
} as const;

export function trackEvent(
	eventName: string,
	params?: Record<string, unknown>,
): void {
	if (hasConsent()) {
		analytics.capture(eventName, params);
	} else if (import.meta.env.DEV) {
		logger.log(`[analytics] ${eventName}`, params);
	}
}

export function withScopePayload<T extends Record<string, unknown>>(
	payload: T,
): T & {
	account_id: string | undefined;
	account_handle: string | undefined;
	account_platform: string | undefined;
	group_id: string | undefined;
} {
	const scopedAccount = useAccountScopeStore.getState().scopedAccount;
	const selectedGroupId = useWorkspaceStore.getState().selectedGroupId;

	return {
		...payload,
		account_id: scopedAccount?.id ?? (payload.account_id as string | undefined),
		account_handle: scopedAccount?.handle,
		account_platform: scopedAccount?.platform,
		group_id: selectedGroupId ?? undefined,
	};
}

export function setAnalyticsUserId(userId: string | null): void {
	if (!hasConsent()) {
		if (import.meta.env.DEV) logger.log("[analytics] identify:", userId);
		return;
	}

	if (userId) {
		analytics.identify(userId);
	} else {
		analytics.reset();
	}
}

export function setAnalyticsUserProperties(
	properties: Record<string, unknown>,
): void {
	if (!hasConsent()) {
		if (import.meta.env.DEV) logger.log("[analytics] user props:", properties);
		return;
	}

	analytics.setPersonProperties(properties);
}

export function trackPageView(path: string): void {
	trackEvent(
		ANALYTICS_EVENTS.PAGE_VIEWED,
		withScopePayload({
			$current_url: window.location.href,
			path,
		}),
	);
}

export function trackPostCreated(params: {
	accountId: string;
	hasImages: boolean;
	isScheduled: boolean;
	contentLength: number;
}): void {
	trackEvent(ANALYTICS_EVENTS.POST_CREATED, params);
}

export function trackPostPublished(params: {
	accountId: string;
	hasImages: boolean;
	contentLength: number;
	wasScheduled: boolean;
}): void {
	trackEvent(ANALYTICS_EVENTS.POST_PUBLISHED, params);
}

export function trackViewChange(viewName: string, platform?: string): void {
	trackEvent(
		ANALYTICS_EVENTS.VIEW_CHANGED,
		withScopePayload({
			view_name: viewName,
			platform: platform || "threads",
		}),
	);
}

export function trackAIContentGeneration(params: {
	feature: "generate" | "rephrase" | "adapt_media" | "batch";
	success: boolean;
	accountId?: string | undefined;
}): void {
	const eventMap = {
		generate: ANALYTICS_EVENTS.AI_CONTENT_GENERATED,
		rephrase: ANALYTICS_EVENTS.AI_REPHRASE_USED,
		adapt_media: ANALYTICS_EVENTS.AI_ADAPT_MEDIA_USED,
		batch: ANALYTICS_EVENTS.AI_BATCH_GENERATED,
	} as const;
	trackEvent(
		eventMap[params.feature],
		withScopePayload({
			success: params.success,
			account_id: params.accountId,
		}),
	);
}

export function trackCompetitor(
	action: "added" | "removed" | "synced",
	competitorUsername: string,
): void {
	const eventMap = {
		added: ANALYTICS_EVENTS.COMPETITOR_ADDED,
		removed: ANALYTICS_EVENTS.COMPETITOR_REMOVED,
		synced: ANALYTICS_EVENTS.COMPETITOR_SYNCED,
	} as const;

	trackEvent(
		eventMap[action],
		withScopePayload({ competitor_username: competitorUsername }),
	);
}

export function trackAnalyticsView(accountId: string): void {
	trackEvent(ANALYTICS_EVENTS.ANALYTICS_VIEWED, { account_id: accountId });
}

export function trackError(params: {
	error_name: string;
	error_message: string;
	error_stack?: string | undefined;
	component?: string | undefined;
}): void {
	trackEvent(
		ANALYTICS_EVENTS.ERROR_OCCURRED,
		withScopePayload({
			...params,
			error_stack: params.error_stack?.substring(0, 100),
		}),
	);
}

export const analyticsService = {
	trackEvent,
	withScopePayload,
	setUserId: setAnalyticsUserId,
	setUserProperties: setAnalyticsUserProperties,
	trackPostCreated,
	trackPostPublished,
	trackViewChange,
	trackAIContentGeneration,
	trackCompetitor,
	trackAnalyticsView,
	trackPageView,
	trackError,
	EVENTS: ANALYTICS_EVENTS,
};

export default analyticsService;
