/**
 * Shared token refresh utilities for Instagram/Facebook OAuth tokens.
 *
 * Centralizes the refresh logic used by:
 * - api/auth/instagram/refresh.ts (user-triggered)
 * - api/cron/token-refresh.ts (scheduled)
 * - api/cron/daily-maintenance.ts (scheduled)
 */

import { withRetry } from "./retryUtils.js";

const FB_GRAPH_VERSION = "v25.0";

interface TokenRefreshResult {
	ok: boolean;
	data: {
		access_token?: string | undefined;
		token_type?: string | undefined;
		expires_in?: number | undefined;
		error?: Record<string, unknown> | undefined;
	};
}

export function isTokenExpired(
	expiresAt: string | Date | null | undefined,
	now = new Date(),
): boolean {
	if (!expiresAt) return false;
	const expiresTime =
		expiresAt instanceof Date ? expiresAt.getTime() : Date.parse(expiresAt);
	return Number.isFinite(expiresTime) && expiresTime <= now.getTime();
}

/**
 * Refresh a Facebook Login token via fb_exchange_token grant.
 * Uses POST body to keep client_secret out of URL/server logs.
 */
export async function refreshFacebookToken(
	currentToken: string,
): Promise<TokenRefreshResult> {
	const appId = process.env.FACEBOOK_APP_ID;
	const appSecret = process.env.FACEBOOK_APP_SECRET;
	if (!appId || !appSecret) {
		throw new Error(
			"Missing FACEBOOK_APP_ID or FACEBOOK_APP_SECRET for FB token refresh",
		);
	}

	const response = await withRetry(() =>
		fetch(`https://graph.facebook.com/${FB_GRAPH_VERSION}/oauth/access_token`, {
			method: "POST",
			headers: { "Content-Type": "application/x-www-form-urlencoded" },
			body: new URLSearchParams({
				grant_type: "fb_exchange_token",
				client_id: appId,
				client_secret: appSecret,
				fb_exchange_token: currentToken,
			}),
			signal: AbortSignal.timeout(10000),
		}),
	);

	const data = await response.json();
	return { ok: response.ok, data };
}

/**
 * Refresh an Instagram Login token via ig_refresh_token grant.
 *
 * IMPORTANT: Meta's IG token refresh endpoint is GET-only and explicitly requires the
 * access_token as a query parameter. There is no POST-body alternative for this grant
 * type — using POST returns a 400 "Method Not Allowed" error. This is a Meta API
 * constraint, not a design choice. Reference:
 * https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/refresh-access-tokens
 *
 * Mitigation: The token is never logged here. Callers must ensure they do not log the
 * full error object from this function without scrubbing the token first.
 */
export async function refreshInstagramToken(
	currentToken: string,
): Promise<TokenRefreshResult> {
	const response = await withRetry(() =>
		fetch(
			`https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=${encodeURIComponent(currentToken)}`,
			{
				signal: AbortSignal.timeout(10000),
			},
		),
	);

	// Parse response without logging — caller handles error reporting
	const data = await response.json();
	return { ok: response.ok, data };
}

/**
 * Refresh a Threads long-lived token via th_refresh_token grant.
 *
 * Same GET-only constraint as Instagram — Meta requires access_token as a query param.
 */
export async function refreshThreadsToken(
	currentToken: string,
): Promise<TokenRefreshResult> {
	const response = await withRetry(() =>
		fetch(
			`https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=${encodeURIComponent(currentToken)}`,
			{
				signal: AbortSignal.timeout(10000),
			},
		),
	);

	const data = await response.json();
	return { ok: response.ok, data };
}

/**
 * Refresh a token based on login type (facebook or instagram).
 */
export async function refreshTokenByLoginType(
	currentToken: string,
	loginType: string,
): Promise<TokenRefreshResult> {
	if (loginType === "facebook") {
		return refreshFacebookToken(currentToken);
	}
	return refreshInstagramToken(currentToken);
}
