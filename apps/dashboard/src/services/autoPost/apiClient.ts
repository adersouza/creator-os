import { apiUrl } from "@/lib/apiUrl";
import { randomUUID } from "@/lib/uuid";
import { supabase } from "../api/shared";

export async function postAutoPostAction<T = unknown>(
	action: string,
	body: Record<string, unknown>,
	options: { idempotencyKey?: string | undefined } = {},
): Promise<T> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) {
		throw new Error("Not signed in");
	}

	const key =
		options.idempotencyKey ??
		`auto-post:${action}:${hashStableValue(body).slice(0, 24)}:${randomUUID()}`;
	const response = await fetch(apiUrl(`/api/auto-post?action=${encodeURIComponent(action)}`), {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session.access_token}`,
			"Idempotency-Key": key,
		},
		body: JSON.stringify(body),
	});

	const json = await response.json().catch(() => ({}));
	if (!response.ok) {
		throw new Error(json?.error || `Auto-post action failed (${response.status})`);
	}
	return json as T;
}

function hashStableValue(value: unknown): string {
	let hash = 2166136261;
	const text = stableStringify(value);
	for (let i = 0; i < text.length; i += 1) {
		hash ^= text.charCodeAt(i);
		hash = Math.imul(hash, 16777619);
	}
	return (hash >>> 0).toString(16).padStart(8, "0");
}

function stableStringify(value: unknown): string {
	if (value === null || typeof value !== "object") return JSON.stringify(value);
	if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
	const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
		a.localeCompare(b),
	);
	return `{${entries
		.map(([key, child]) => `${JSON.stringify(key)}:${stableStringify(child)}`)
		.join(",")}}`;
}
