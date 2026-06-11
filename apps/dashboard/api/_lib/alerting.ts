/**
 * Alerting System — Discord Webhook Integration
 *
 * Sends alerts to Discord when critical events occur:
 * - Cron job failures
 * - Token refresh failures
 * - Dead letter queue threshold exceeded
 * - Meta API sustained outages
 *
 * Requires env var: DISCORD_ALERT_WEBHOOK_URL
 *
 * Usage:
 *   import { alert, AlertLevel } from "./_lib/alerting.js";
 *   await alert(AlertLevel.ERROR, "Token refresh failed", { username: "foo", error: "..." });
 */

import { logger } from "./logger.js";
import { getSupabaseAny } from "./supabase.js";

// ============================================================================
// Types
// ============================================================================

export enum AlertLevel {
	INFO = "info",
	WARN = "warn",
	ERROR = "error",
	CRITICAL = "critical",
}

interface AlertOptions {
	/** Additional context fields shown in the embed */
	[key: string]: string | number | boolean | undefined;
}

interface AlertDeliveryOptions {
	mirrorToGlobal?: boolean | undefined;
}

// ============================================================================
// Color mapping for Discord embeds
// ============================================================================

const LEVEL_COLORS: Record<AlertLevel, number> = {
	[AlertLevel.INFO]: 0x3498db, // Blue
	[AlertLevel.WARN]: 0xf39c12, // Orange
	[AlertLevel.ERROR]: 0xe74c3c, // Red
	[AlertLevel.CRITICAL]: 0x9b59b6, // Purple
};

const LEVEL_EMOJI: Record<AlertLevel, string> = {
	[AlertLevel.INFO]: "ℹ️",
	[AlertLevel.WARN]: "⚠️",
	[AlertLevel.ERROR]: "🔴",
	[AlertLevel.CRITICAL]: "🚨",
};

// ============================================================================
// Rate limiting — don't spam Discord
// ============================================================================

const alertCooldowns = new Map<string, number>();
const COOLDOWN_MS = 5 * 60 * 1000; // 5 minutes per unique alert key

function shouldThrottle(key: string): boolean {
	const now = Date.now();
	const lastSent = alertCooldowns.get(key);
	if (lastSent && now - lastSent < COOLDOWN_MS) return true;
	alertCooldowns.set(key, now);
	// Prevent memory leak in long-running processes
	if (alertCooldowns.size > 200) {
		const cutoff = now - COOLDOWN_MS;
		for (const [k, v] of Array.from(alertCooldowns)) {
			if (v < cutoff) alertCooldowns.delete(k);
		}
	}
	return false;
}

// ============================================================================
// Main alert function
// ============================================================================

/**
 * Send an alert to Discord webhook.
 * Fire-and-forget — never throws or blocks the caller.
 *
 * @param level   Alert severity
 * @param title   Short description of the event
 * @param options Additional context (key-value pairs shown in embed fields)
 */
export async function alert(
	level: AlertLevel,
	title: string,
	options?: AlertOptions,
): Promise<void> {
	const webhookUrl = process.env.DISCORD_ALERT_WEBHOOK_URL;
	if (!webhookUrl) {
		// No webhook configured — log and return silently
		logger.warn("Alert skipped: DISCORD_ALERT_WEBHOOK_URL not set", {
			level,
			title,
		});
		return;
	}

	// Throttle duplicate alerts
	const throttleKey = `${level}:${title}`;
	if (shouldThrottle(throttleKey)) {
		return;
	}

	try {
		// #622: Sanitize fields — strip stack traces and PII from Discord alerts
		const sanitizeValue = (key: string, val: string): string => {
			let s = val.slice(0, 1024);
			// Strip stack traces (lines starting with "at ")
			s = s.replace(/\n\s*at .+/g, "").trim();
			// Redact usernames in non-title fields
			if (key === "username" || key === "email") {
				s = s.length > 2 ? `${s[0]}***${s[s.length - 1]}` : "***";
			}
			return s;
		};

		const fields = options
			? Object.entries(options)
					.filter(([, v]) => v !== undefined)
					.map(([name, value]) => ({
						name,
						value: sanitizeValue(name, String(value)),
						inline: String(value).length < 50,
					}))
			: [];

		const payload = {
			embeds: [
				{
					title: `${LEVEL_EMOJI[level]} ${title}`,
					color: LEVEL_COLORS[level],
					fields,
					timestamp: new Date().toISOString(),
					footer: {
						text: "Juno33 Backend",
					},
				},
			],
		};

		await fetch(webhookUrl, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
			signal: AbortSignal.timeout(5000),
		});
	} catch (err: unknown) {
		// Never let alerting crash the caller
		logger.error("Failed to send Discord alert", {
			level,
			title,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}

async function postDiscordPayload(
	webhookUrl: string,
	payload: Record<string, unknown>,
): Promise<void> {
	await fetch(webhookUrl, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
		signal: AbortSignal.timeout(5000),
	});
}

async function getWorkspaceDiscordWebhook(
	workspaceId: string,
): Promise<string | null> {
	try {
		const { data } = await getSupabaseAny()
			.from("auto_post_config")
			.select("discord_webhook_url")
			.eq("workspace_id", workspaceId)
			.maybeSingle();
		return (data?.discord_webhook_url as string | null) || null;
	} catch {
		return null;
	}
}

export async function alertWorkspace(
	workspaceId: string,
	level: AlertLevel,
	title: string,
	options?: AlertOptions,
	delivery?: AlertDeliveryOptions,
): Promise<void> {
	const webhookUrl = await getWorkspaceDiscordWebhook(workspaceId);

	if (!webhookUrl) {
		await alert(level, title, { workspace: workspaceId, ...options });
		return;
	}

	// Throttle duplicate alerts across both workspace/global delivery.
	const throttleKey = `workspace:${workspaceId}:${level}:${title}`;
	if (shouldThrottle(throttleKey)) {
		return;
	}

	try {
		const sanitizeValue = (key: string, val: string): string => {
			let s = val.slice(0, 1024);
			s = s.replace(/\n\s*at .+/g, "").trim();
			if (key === "username" || key === "email") {
				s = s.length > 2 ? `${s[0]}***${s[s.length - 1]}` : "***";
			}
			return s;
		};

		const fields = options
			? Object.entries(options)
					.filter(([, v]) => v !== undefined)
					.map(([name, value]) => ({
						name,
						value: sanitizeValue(name, String(value)),
						inline: String(value).length < 50,
					}))
			: [];

		await postDiscordPayload(webhookUrl, {
			embeds: [
				{
					title: `${LEVEL_EMOJI[level]} ${title}`,
					color: LEVEL_COLORS[level],
					fields,
					timestamp: new Date().toISOString(),
					footer: {
						text: `Juno33 Backend · Workspace ${workspaceId}`,
					},
				},
			],
		});

		if (delivery?.mirrorToGlobal) {
			await alert(level, title, { workspace: workspaceId, ...options });
		}
	} catch (err: unknown) {
		logger.error("Failed to send workspace Discord alert", {
			workspaceId,
			level,
			title,
			error: err instanceof Error ? err.message : String(err),
		});
		// Fall back to global alerting if workspace delivery fails.
		await alert(level, title, { workspace: workspaceId, ...options });
	}
}

// ============================================================================
// Convenience helpers
// ============================================================================

export const alertInfo = (title: string, options?: AlertOptions) =>
	alert(AlertLevel.INFO, title, options);

export const alertWarn = (title: string, options?: AlertOptions) =>
	alert(AlertLevel.WARN, title, options);

export const alertError = (title: string, options?: AlertOptions) =>
	alert(AlertLevel.ERROR, title, options);

export const alertCritical = (title: string, options?: AlertOptions) =>
	alert(AlertLevel.CRITICAL, title, options);

// ============================================================================
// Specialized alert helpers
// ============================================================================

/**
 * Alert on cron job failure. Called from withCron middleware.
 */
export async function alertCronFailure(
	jobName: string,
	error: string,
	durationMs?: number,
): Promise<void> {
	await alert(AlertLevel.ERROR, `Cron job failed: ${jobName}`, {
		error: error.slice(0, 500),
		duration: durationMs ? `${durationMs}ms` : "unknown",
		job: jobName,
	});
}

/**
 * Alert on token refresh failures.
 */
export async function alertTokenRefreshFailure(
	platform: string,
	username: string,
	error: string,
): Promise<void> {
	await alert(AlertLevel.WARN, `Token refresh failed: @${username}`, {
		platform,
		username,
		error: error.slice(0, 500),
	});
}

/**
 * Alert when dead letter queue exceeds threshold.
 */
export async function alertDeadLetterThreshold(
	count: number,
	table: string,
): Promise<void> {
	await alert(AlertLevel.WARN, `Dead letter queue growing: ${table}`, {
		count: String(count),
		table,
		action: "Review at /api/admin/dead-letters",
	});
}

// ============================================================================
// Meta API contract change detection
// ============================================================================

/** In-memory accumulator for partial insight responses within a single invocation */
const partialInsightAccumulator = {
	total: 0,
	partial: 0,
	missingMetrics: new Set<string>(),
	flushed: false,
};

/**
 * Track an account insights response. Call after every getInstagramAccountInsights.
 * At the end of the sync job, call flushPartialInsightsAlert() to send ONE alert.
 */
export function trackInsightsResponse(
	partial: boolean,
	missingMetrics?: string[],
): void {
	partialInsightAccumulator.total++;
	if (partial) {
		partialInsightAccumulator.partial++;
		for (const m of missingMetrics || []) {
			partialInsightAccumulator.missingMetrics.add(m);
		}
	}
}

/**
 * Resets all in-memory alerting state. FOR TESTS ONLY.
 * Clears the partial insights accumulator and the Discord cooldown map so
 * each test starts with a clean slate.
 */
export function _resetAlertingForTests(): void {
	partialInsightAccumulator.total = 0;
	partialInsightAccumulator.partial = 0;
	partialInsightAccumulator.missingMetrics = new Set();
	partialInsightAccumulator.flushed = false;
	alertCooldowns.clear();
}

/**
 * Flush accumulated partial insights data as a single Discord alert.
 * Only fires if >50% of accounts returned partial data (indicates API contract change,
 * not just one account with bad permissions).
 */
// Metrics that Meta is known to omit under normal conditions:
// - follower_count: time-series day-only; omitted for accounts with <100 followers
// These should not trigger a contract-change alert since the code already handles
// their absence with fallbacks (e.g. profile node for follower_count).
const EXPECTED_OPTIONAL_METRICS = new Set(["follower_count"]);

export async function flushPartialInsightsAlert(): Promise<void> {
	const { total, partial, missingMetrics, flushed } = partialInsightAccumulator;
	// Reset for next invocation
	partialInsightAccumulator.total = 0;
	partialInsightAccumulator.partial = 0;
	partialInsightAccumulator.missingMetrics = new Set();
	partialInsightAccumulator.flushed = false;

	if (flushed || total === 0 || partial === 0) return;

	// Filter out metrics that Meta is known to omit — only alert on unexpected gaps
	const unexpectedMissing = [...missingMetrics].filter(
		(m) => !EXPECTED_OPTIONAL_METRICS.has(m),
	);
	if (unexpectedMissing.length === 0) return;

	const pct = Math.round((partial / total) * 100);

	// Only alert if widespread (>50%) AND sample size is meaningful (>=3 accounts).
	// Without the minimum, a single-account sync run where that one account has a
	// transient Meta API error triggers 1/1 = 100% → false alarm.
	if (pct > 50 && total >= 3) {
		await alert(AlertLevel.ERROR, "IG insights API contract change detected", {
			affected: `${partial}/${total} accounts (${pct}%)`,
			missingMetrics: unexpectedMissing.join(", "),
			action: "Check metric_type params and Meta API changelog",
		});
	}
}
