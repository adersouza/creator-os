// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * SSRF Protection — Prevent requests to private/internal IP ranges.
 *
 * Resolves hostnames via DNS before connecting to block DNS rebinding attacks.
 * Blocks RFC 1918, loopback, link-local, and IPv6 private ranges.
 */

import { logger } from "./logger.js";

/**
 * Check if an IPv4 address falls within private/internal ranges.
 */
function isPrivateIPv4(ip: string): boolean {
	const parts = ip.split(".").map(Number);
	if (
		parts.length !== 4 ||
		parts.some((p) => Number.isNaN(p) || p < 0 || p > 255)
	) {
		return true; // Malformed = treat as private (block it)
	}

	const [a, b] = parts;

	// 0.0.0.0
	if (ip === "0.0.0.0") return true;

	// 127.0.0.0/8 — loopback
	if (a === 127) return true;

	// 10.0.0.0/8 — private
	if (a === 10) return true;

	// 172.16.0.0/12 — private (172.16.0.0 – 172.31.255.255)
	if (a === 172 && b! >= 16 && b! <= 31) return true;

	// 192.168.0.0/16 — private
	if (a === 192 && b === 168) return true;

	// 169.254.0.0/16 — link-local
	if (a === 169 && b === 254) return true;

	return false;
}

/**
 * Check if an IPv6 address is private/internal.
 */
function isPrivateIPv6(ip: string): boolean {
	const normalized = ip.toLowerCase();

	// ::1 — loopback
	if (normalized === "::1") return true;

	// fc00::/7 — unique local (fc00:: and fd00::)
	if (normalized.startsWith("fc") || normalized.startsWith("fd")) return true;

	// fe80::/10 — link-local
	if (normalized.startsWith("fe80")) return true;

	// :: — unspecified
	if (normalized === "::") return true;

	// IPv4-mapped IPv6 (::ffff:x.x.x.x)
	const v4MappedMatch = normalized.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
	if (v4MappedMatch) {
		return isPrivateIPv4(v4MappedMatch[1]!);
	}

	const v4MappedHexMatch = normalized.match(
		/^(?:::ffff:|0:0:0:0:0:ffff:)([0-9a-f]{1,4}):([0-9a-f]{1,4})$/,
	);
	if (v4MappedHexMatch) {
		const high = Number.parseInt(v4MappedHexMatch[1]!, 16);
		const low = Number.parseInt(v4MappedHexMatch[2]!, 16);
		if (
			Number.isNaN(high) ||
			Number.isNaN(low) ||
			high < 0 ||
			high > 0xffff ||
			low < 0 ||
			low > 0xffff
		) {
			return true;
		}
		return isPrivateIPv4(
			[
				(high >> 8) & 0xff,
				high & 0xff,
				(low >> 8) & 0xff,
				low & 0xff,
			].join("."),
		);
	}

	return false;
}

/**
 * Check if any IP address (v4 or v6) is private.
 */
export function isPrivateIP(ip: string): boolean {
	if (ip.includes(":")) {
		return isPrivateIPv6(ip);
	}
	return isPrivateIPv4(ip);
}

/**
 * Validate that a URL does not resolve to a private/internal IP.
 *
 * Resolves the hostname via DNS and checks all resolved addresses.
 * Returns an error message if the URL is blocked, or null if it's safe.
 */
export async function validateUrlNotPrivate(
	url: string,
): Promise<string | null> {
	try {
		const parsed = new URL(url);

		// Only allow http(s)
		if (!["http:", "https:"].includes(parsed.protocol)) {
			return "Only HTTP(S) URLs are allowed";
		}

		const hostname = parsed.hostname;

		// Block obvious localhost/private hostnames
		if (
			hostname === "localhost" ||
			hostname === "0.0.0.0" ||
			hostname === "[::1]"
		) {
			return "URLs pointing to localhost are not allowed";
		}

		// If the hostname is already an IP literal, check it directly
		const ipLiteralV4 = /^\d+\.\d+\.\d+\.\d+$/.test(hostname);
		const ipLiteralV6 = hostname.startsWith("[") && hostname.endsWith("]");

		if (ipLiteralV4) {
			if (isPrivateIP(hostname)) {
				return "URLs pointing to private IP ranges are not allowed";
			}
			return null;
		}

		if (ipLiteralV6) {
			const rawIp = hostname.slice(1, -1);
			if (isPrivateIP(rawIp)) {
				return "URLs pointing to private IP ranges are not allowed";
			}
			return null;
		}

		// Resolve hostname via DNS
		const dns = await import("node:dns");
		const { promisify } = await import("node:util");
		const resolve4 = promisify(dns.resolve4);
		const resolve6 = promisify(dns.resolve6);

		const allIps: string[] = [];

		try {
			const ipv4s = await resolve4(hostname);
			allIps.push(...ipv4s);
		} catch {
			// No A records — that's fine, try AAAA
		}

		try {
			const ipv6s = await resolve6(hostname);
			allIps.push(...ipv6s);
		} catch {
			// No AAAA records — that's fine
		}

		if (allIps.length === 0) {
			return "Could not resolve hostname";
		}

		for (const ip of allIps) {
			if (isPrivateIP(ip)) {
				logger.warn("[ssrf] Blocked private IP resolution", {
					hostname,
					ip,
					url,
				});
				return "URLs pointing to private IP ranges are not allowed";
			}
		}

		return null; // All IPs are public — safe to proceed
	} catch (err) {
		logger.warn("[ssrf] URL validation failed", {
			url,
			error: String(err),
		});
		return `URL validation failed: ${err instanceof Error ? err.message : String(err)}`;
	}
}
