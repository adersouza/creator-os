/**
 * PostHog Analytics — initialization and singleton access.
 *
 * Reads VITE_POSTHOG_KEY and VITE_POSTHOG_HOST from environment.
 * In development or when the key is missing, PostHog is never loaded
 * and all exported helpers silently no-op.
 *
 * `posthog-js` is loaded lazily via dynamic import — its ~60KB gz chunk
 * was previously eagerly imported, shipping to every visitor on first
 * paint regardless of whether analytics ever fires. The dynamic import
 * defers it until `initPostHog()` is called (which happens after first
 * render, not in the critical path).
 */

const POSTHOG_KEY = import.meta.env.VITE_POSTHOG_KEY as string | undefined;
const POSTHOG_HOST =
	(import.meta.env.VITE_POSTHOG_HOST as string) || "https://us.i.posthog.com";

/** Whether PostHog is actually active (production + key present) */
export const isPostHogEnabled = import.meta.env.PROD && !!POSTHOG_KEY;

// Lazily-resolved instance. Stays null until init kicks off the dynamic import.
type PostHogInstance = typeof import("posthog-js").default;
let posthogInstance: PostHogInstance | null = null;
let initialized = false;
let initPromise: Promise<PostHogInstance | null> | null = null;

/**
 * Call once at app bootstrap. Returns a promise so callers (analytics
 * service) can await readiness before firing events; in practice the
 * service fires-and-forgets and PostHog buffers internally.
 */
export function initPostHog(): Promise<PostHogInstance | null> {
	if (initialized) return Promise.resolve(posthogInstance);
	if (!isPostHogEnabled || !POSTHOG_KEY) {
		initialized = true;
		return Promise.resolve(null);
	}
	if (initPromise) return initPromise;

	initPromise = import("posthog-js").then(({ default: posthog }) => {
		posthog.init(POSTHOG_KEY, {
			api_host: POSTHOG_HOST,
			capture_pageview: false,
			person_profiles: "identified_only",
			respect_dnt: true,
			disable_session_recording: false,
			session_recording: {
				maskAllInputs: true,
				maskTextSelector: "[data-mask]",
			},
			autocapture: false,
			persistence: "localStorage+cookie",
			advanced_disable_feature_flags: true,
		});
		posthogInstance = posthog;
		initialized = true;
		return posthog;
	});
	return initPromise;
}

/**
 * Returns the PostHog instance once init has resolved. Returns null when
 * disabled or before init completes — analyticsService should no-op in
 * that case.
 */
export function getPostHog(): PostHogInstance | null {
	return posthogInstance;
}
