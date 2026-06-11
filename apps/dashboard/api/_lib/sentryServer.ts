/**
 * Server-side Sentry initialization for cron job monitoring
 * Lazy-import this module in cron jobs to capture errors
 */

import { logger, scrubSensitive } from "./logger.js";

let initialized = false;

async function ensureInit() {
	if (initialized) return;

	// Check DSN before importing to avoid unnecessary overhead
	const dsn = process.env.SENTRY_DSN;
	if (!dsn) {
		initialized = true;
		return;
	}

	const Sentry = await import("@sentry/node");

	Sentry.init({
		dsn,
		environment: process.env.VERCEL_ENV || "development",
		// Enable performance monitoring
		tracesSampleRate: process.env.VERCEL_ENV === "production" ? 0.1 : 1.0,
		// Disable OpenTelemetry HTTP instrumentation (unnecessary overhead in serverless)
		skipOpenTelemetrySetup: true,
		// Scrub sensitive data from events
		beforeSend(event) {
			if (event.extra) {
				event.extra = scrubSensitive(event.extra as Record<string, unknown>);
			}
			if (event.contexts) {
				event.contexts = scrubSensitive(
					event.contexts as Record<string, unknown>,
				) as typeof event.contexts;
			}
			if (event.request?.data && typeof event.request.data === "object") {
				event.request.data = scrubSensitive(
					event.request.data as Record<string, unknown>,
				);
			}
			if (event.request?.headers) {
				event.request.headers = scrubSensitive(
					event.request.headers as Record<string, unknown>,
				) as typeof event.request.headers;
			}
			return event;
		},
	});

	initialized = true;
}

/**
 * Capture an exception with cron job context
 */
export async function captureServerException(
	error: unknown,
	context?: { cronJob?: string | undefined; [key: string]: unknown },
): Promise<void> {
	try {
		await ensureInit();
		const Sentry = await import("@sentry/node");

		const safeContext = context ? scrubSensitive(context) : {};

		Sentry.withScope((scope) => {
			if (safeContext.cronJob) {
				scope.setTag("cron_job", String(safeContext.cronJob));
			}
			scope.setExtras(safeContext);
			scope.setLevel("error");
			Sentry.captureException(
				error instanceof Error
					? error
					: new Error(
							typeof error === "object" && error !== null
								? JSON.stringify(error)
								: String(error),
						),
			);
		});
	} catch (sentryErr) {
		logger.warn("[sentry] Failed to capture exception", {
			error: String(sentryErr),
		});
	}
}

/**
 * Log a cron job message to Sentry (info level)
 */
export async function captureCronMessage(
	message: string,
	context?: { cronJob?: string | undefined; [key: string]: unknown },
): Promise<void> {
	return captureServerMessage(message, context);
}

export async function captureServerMessage(
	message: string,
	context?: { [key: string]: unknown },
	level: "info" | "warning" | "error" = "info",
): Promise<void> {
	try {
		await ensureInit();
		const Sentry = await import("@sentry/node");

		Sentry.withScope((scope) => {
			if (context?.cronJob) {
				scope.setTag("cron_job", String(context.cronJob));
			}
			if (context) scope.setExtras(scrubSensitive(context));
			scope.setLevel(level);
			Sentry.captureMessage(message);
		});
	} catch (sentryErr) {
		logger.warn("[sentry] Failed to capture server message", {
			error: String(sentryErr),
		});
	}
}
