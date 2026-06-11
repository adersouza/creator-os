// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Cross-browser UUID v4 generator.
 *
 * `crypto.randomUUID()` was only added in Chrome 92 / Safari 15.4 / Firefox 95.
 * This shim falls back to `crypto.getRandomValues()` (available since Chrome 37,
 * Safari 11, Firefox 26) so auth flows work on older OS/browser combos.
 *
 * Usage: import { randomUUID } from "@/lib/uuid";
 *
 * DO NOT use `crypto.randomUUID()` directly — Biome will flag it.
 */
export function randomUUID(): string {
	// Native path — no overhead for users on modern browsers
	if (
		typeof crypto !== "undefined" &&
		typeof crypto.randomUUID === "function"
	) {
		return crypto.randomUUID();
	}
	// Fallback via getRandomValues (RFC 4122 v4)
	return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) => {
		const n = Number(c);
		return (
			n ^
			(crypto.getRandomValues(new Uint8Array(1))[0]! & (15 >> (n / 4)))
		).toString(16);
	});
}
