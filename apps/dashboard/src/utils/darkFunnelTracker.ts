/**
 * Dark Funnel Metric Tracking
 *
 * Tracks invisible engagement signals:
 * - Dashboard time (seconds spent on dashboard)
 * - Tab refresh count (visibilitychange events)
 * - Export count (already tracked via feature_usage)
 */

import { supabase } from "@/services/supabase";

import { apiUrl } from '@/lib/apiUrl';
let _tabRefreshCount = 0;

async function getToken(): Promise<string | null> {
	try {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		return session?.access_token || null;
	} catch {
		return null;
	}
}

async function trackFeature(feature: string): Promise<void> {
	const token = await getToken();
	if (!token) return;
	try {
		await fetch(apiUrl("/api/analytics/feature-usage"), {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${token}`,
			},
			body: JSON.stringify({ feature }),
			keepalive: true,
		});
	} catch {
		// silent
	}
}

/**
 * Track time spent on the dashboard.
 * Call on unmount with the start timestamp.
 */
export function trackDashboardTime(startTime: number): void {
	const seconds = Math.round((Date.now() - startTime) / 1000);
	if (seconds < 3) return; // ignore trivial visits
	trackFeature(`dashboard_time_seconds:${seconds}`);
}

/**
 * Track tab returning to visibility (user switching back).
 * Call this from a visibilitychange listener.
 */
export function trackTabRefresh(): void {
	_tabRefreshCount++;
	// Batch: only flush every 5 refreshes to avoid spam
	if (_tabRefreshCount % 5 === 0) {
		trackFeature(`tab_refresh_count:${_tabRefreshCount}`);
	}
}

/**
 * Flush any pending tab refresh count (e.g., on page unload).
 */
export function flushTabRefreshCount(): void {
	if (_tabRefreshCount > 0) {
		trackFeature(`tab_refresh_count:${_tabRefreshCount}`);
		_tabRefreshCount = 0;
	}
}

/**
 * Initialize dark funnel tracking.
 * Sets up visibilitychange listener. Returns cleanup function.
 */
export function initDarkFunnelTracking(): () => void {
	const handleVisibility = () => {
		if (document.visibilityState === "visible") {
			trackTabRefresh();
		}
	};

	document.addEventListener("visibilitychange", handleVisibility);

	const handleBeforeUnload = () => flushTabRefreshCount();
	window.addEventListener("beforeunload", handleBeforeUnload);

	return () => {
		document.removeEventListener("visibilitychange", handleVisibility);
		window.removeEventListener("beforeunload", handleBeforeUnload);
		flushTabRefreshCount();
	};
}
