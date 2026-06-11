/**
 * Trace ID generator for end-to-end publish pipeline observability.
 *
 * Format: {prefix}-{timestamp}-{random6}
 * Prefixes:
 *   ap     = auto-post publish dispatch
 *   sched  = scheduled post dispatch
 *   fill   = queue fill dispatch
 *   recon  = publish-worker reconciliation dispatch
 *   manual = manual retry dispatch
 *   del    = deletion cascade
 */
export function generateTraceId(prefix = "tr"): string {
	return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}
