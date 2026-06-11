import { apiUrl } from "@/lib/apiUrl";
import { analytics } from "@/lib/analytics";
import { supabase } from "@/services/supabase";

const CONTENT_KEY_RE = /caption|content|text|body|url|media|token|secret|email/i;

function sanitize(properties: Record<string, unknown> | undefined) {
	const safe: Record<string, unknown> = {};
	for (const [key, value] of Object.entries(properties ?? {})) {
		if (CONTENT_KEY_RE.test(key)) continue;
		if (
			typeof value === "string" ||
			typeof value === "number" ||
			typeof value === "boolean" ||
			value === null
		) {
			safe[key] = typeof value === "string" ? value.slice(0, 120) : value;
		}
	}
	return safe;
}

export function trackClientEvent(
	event: string,
	properties?: Record<string, unknown>,
) {
	const safeProperties = sanitize(properties);
	analytics.capture(event, safeProperties);

	if (typeof window === "undefined") return;
	void (async () => {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session?.access_token) return;
		await fetch(apiUrl("/api/telemetry?action=client-event"), {
			method: "POST",
			headers: {
				Authorization: `Bearer ${session.access_token}`,
				"Content-Type": "application/json",
			},
			body: JSON.stringify({
				event,
				route: `${window.location.pathname}${window.location.search}`,
				properties: safeProperties,
			}),
		}).catch(() => {});
	})();
}
