import { describe, expect, it } from "vitest";
import {
	appendUtms,
	detectDevice,
	detectPlatform,
	generateFingerprint,
	isCrawler,
	isInAppBrowser,
	parseUtmParams,
} from "../platformDetect.js";

describe("detectPlatform", () => {
	describe("User-Agent detection", () => {
		it("detects Instagram from UA", () => {
			expect(
				detectPlatform(
					"Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) Instagram 275.0",
				),
			).toBe("instagram");
		});

		it("detects Threads from UA", () => {
			expect(detectPlatform("Mozilla/5.0 (iPhone) Threads/1.0")).toBe(
				"threads",
			);
		});

		it("detects Facebook from UA (FBAN)", () => {
			expect(detectPlatform("Mozilla/5.0 (iPhone) [FBAN/FBIOS]")).toBe(
				"facebook",
			);
		});

		it("detects Facebook from UA (FBAV)", () => {
			expect(detectPlatform("Mozilla/5.0 (Linux; Android 12) FBAV/410.0")).toBe(
				"facebook",
			);
		});

		it("detects Facebook from UA (FB_IAB)", () => {
			expect(
				detectPlatform("Mozilla/5.0 (Linux; Android) FB_IAB/MESSENGER"),
			).toBe("facebook");
		});

		it("detects Twitter from UA", () => {
			expect(detectPlatform("Mozilla/5.0 (iPhone) Twitter for iOS")).toBe(
				"twitter",
			);
		});

		it("detects TikTok from UA (TikTok)", () => {
			expect(detectPlatform("Mozilla/5.0 (iPhone) TikTok 28.0")).toBe("tiktok");
		});

		it("detects TikTok from UA (ByteDance)", () => {
			expect(detectPlatform("Mozilla/5.0 (Linux; Android) ByteDance/1.0")).toBe(
				"tiktok",
			);
		});

		it("detects TikTok from UA (musical_ly)", () => {
			expect(detectPlatform("Mozilla/5.0 (iPhone) musical_ly/25.0")).toBe(
				"tiktok",
			);
		});

		it("detects WhatsApp from UA", () => {
			expect(detectPlatform("Mozilla/5.0 (iPhone) WhatsApp/2.22")).toBe(
				"whatsapp",
			);
		});

		it("detects Snapchat from UA", () => {
			expect(detectPlatform("Mozilla/5.0 (iPhone) Snapchat/12.0")).toBe(
				"snapchat",
			);
		});

		it("detects Telegram from UA", () => {
			expect(detectPlatform("Mozilla/5.0 (iPhone) Telegram/9.0")).toBe(
				"telegram",
			);
		});
	});

	describe("referrer-based detection", () => {
		it("detects Threads from referrer", () => {
			expect(
				detectPlatform("Mozilla/5.0 (Macintosh)", "https://threads.net/@user"),
			).toBe("threads");
		});

		it("detects Instagram from referrer", () => {
			expect(
				detectPlatform(
					"Mozilla/5.0 (Macintosh)",
					"https://www.instagram.com/p/abc",
				),
			).toBe("instagram");
		});

		it("detects Twitter from referrer (t.co)", () => {
			expect(
				detectPlatform("Mozilla/5.0 (Macintosh)", "https://t.co/abc123"),
			).toBe("twitter");
		});

		it("detects Twitter from referrer (twitter.com)", () => {
			expect(
				detectPlatform(
					"Mozilla/5.0 (Macintosh)",
					"https://twitter.com/user/status/123",
				),
			).toBe("twitter");
		});

		it("detects Twitter from referrer (x.com)", () => {
			expect(
				detectPlatform("Mozilla/5.0 (Macintosh)", "https://x.com/user"),
			).toBe("twitter");
		});

		it("detects Facebook from referrer (facebook.com)", () => {
			expect(
				detectPlatform(
					"Mozilla/5.0 (Macintosh)",
					"https://www.facebook.com/post/123",
				),
			).toBe("facebook");
		});

		it("detects Facebook from referrer (fb.com)", () => {
			expect(
				detectPlatform("Mozilla/5.0 (Macintosh)", "https://fb.com/share"),
			).toBe("facebook");
		});

		it("detects TikTok from referrer", () => {
			expect(
				detectPlatform(
					"Mozilla/5.0 (Macintosh)",
					"https://www.tiktok.com/@user",
				),
			).toBe("tiktok");
		});
	});

	describe("direct and unknown", () => {
		it("returns 'direct' when no referrer and generic browser UA", () => {
			expect(
				detectPlatform(
					"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
				),
			).toBe("direct");
		});

		it("returns 'direct' with empty UA and no referrer", () => {
			expect(detectPlatform("")).toBe("direct");
		});

		it("returns 'unknown' with unrecognized referrer", () => {
			expect(
				detectPlatform("Mozilla/5.0 (Macintosh)", "https://example.com/page"),
			).toBe("unknown");
		});
	});

	describe("case insensitivity", () => {
		it("detects Instagram with mixed case UA", () => {
			expect(detectPlatform("INSTAGRAM app")).toBe("instagram");
		});

		it("handles null-ish UA gracefully", () => {
			expect(detectPlatform(null as unknown as string)).toBe("direct");
		});
	});
});

describe("detectDevice", () => {
	it("detects iPhone as ios", () => {
		expect(
			detectDevice("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"),
		).toBe("ios");
	});

	it("detects iPad as ios", () => {
		expect(detectDevice("Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X)")).toBe(
			"ios",
		);
	});

	it("detects iPod as ios", () => {
		expect(detectDevice("Mozilla/5.0 (iPod touch; CPU iPhone OS 15_0)")).toBe(
			"ios",
		);
	});

	it("detects Android", () => {
		expect(detectDevice("Mozilla/5.0 (Linux; Android 13; Pixel 7)")).toBe(
			"android",
		);
	});

	it("detects desktop for Mac UA", () => {
		expect(
			detectDevice("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"),
		).toBe("desktop");
	});

	it("detects desktop for Windows UA", () => {
		expect(detectDevice("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe(
			"desktop",
		);
	});

	it("detects desktop for Linux UA", () => {
		expect(detectDevice("Mozilla/5.0 (X11; Linux x86_64)")).toBe("desktop");
	});

	it("returns unknown for generic mobile UA without specific platform", () => {
		expect(detectDevice("Mozilla/5.0 (Mobile; rv:68.0)")).toBe("unknown");
	});

	it("handles empty UA", () => {
		expect(detectDevice("")).toBe("desktop");
	});

	it("handles null UA", () => {
		expect(detectDevice(null as unknown as string)).toBe("desktop");
	});
});

describe("isInAppBrowser", () => {
	it("detects Instagram webview", () => {
		expect(isInAppBrowser("Mozilla/5.0 (iPhone) Instagram 275.0")).toBe(true);
	});

	it("detects Facebook webview (FBAN)", () => {
		expect(isInAppBrowser("Mozilla/5.0 (iPhone) [FBAN/FBIOS]")).toBe(true);
	});

	it("detects Facebook webview (FBAV)", () => {
		expect(isInAppBrowser("Mozilla/5.0 (Android) FBAV/400.0")).toBe(true);
	});

	it("detects TikTok webview", () => {
		expect(isInAppBrowser("Mozilla/5.0 TikTok 28.0")).toBe(true);
	});

	it("detects Snapchat webview", () => {
		expect(isInAppBrowser("Mozilla/5.0 Snapchat/12.0")).toBe(true);
	});

	it("detects Twitter webview", () => {
		expect(isInAppBrowser("Mozilla/5.0 Twitter for iPhone")).toBe(true);
	});

	it("detects Telegram webview", () => {
		expect(isInAppBrowser("Mozilla/5.0 Telegram/9.0")).toBe(true);
	});

	it("detects Messenger webview (FB_IAB)", () => {
		expect(isInAppBrowser("Mozilla/5.0 FB_IAB/MESSENGER")).toBe(true);
	});

	it("returns false for normal Safari", () => {
		expect(
			isInAppBrowser(
				"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
			),
		).toBe(false);
	});

	it("returns false for normal Chrome", () => {
		expect(
			isInAppBrowser("Mozilla/5.0 (Windows NT 10.0) Chrome/120.0.0.0"),
		).toBe(false);
	});

	it("returns false for empty UA", () => {
		expect(isInAppBrowser("")).toBe(false);
	});

	it("handles null UA", () => {
		expect(isInAppBrowser(null as unknown as string)).toBe(false);
	});
});

describe("isCrawler", () => {
	it("detects Googlebot", () => {
		expect(
			isCrawler(
				"Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
			),
		).toBe(true);
	});

	it("detects Twitterbot", () => {
		expect(isCrawler("Twitterbot/1.0")).toBe(true);
	});

	it("detects facebookexternalhit", () => {
		expect(
			isCrawler(
				"facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
			),
		).toBe(true);
	});

	it("detects newer Meta crawler user agents", () => {
		expect(
			isCrawler(
				"meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)",
			),
		).toBe(true);
		expect(isCrawler("Meta-ExternalFetcher/1.1")).toBe(true);
	});

	it("detects Bingbot", () => {
		expect(isCrawler("Mozilla/5.0 (compatible; bingbot/2.0)")).toBe(true);
	});

	it("detects LinkedInBot", () => {
		expect(isCrawler("LinkedInBot/1.0")).toBe(true);
	});

	it("detects Applebot", () => {
		expect(isCrawler("Mozilla/5.0 (Applebot/0.1)")).toBe(true);
	});

	it("detects DiscordBot", () => {
		expect(isCrawler("Mozilla/5.0 (compatible; Discordbot/2.0)")).toBe(true);
	});

	it("detects WhatsApp crawler", () => {
		expect(isCrawler("WhatsApp/2.21.23.23")).toBe(true);
	});

	it("detects TelegramBot", () => {
		expect(isCrawler("TelegramBot (like TwitterBot)")).toBe(true);
	});

	it("detects Pinterest", () => {
		expect(isCrawler("Pinterest/0.2 (+http://www.pinterest.com/)")).toBe(true);
	});

	it("returns false for normal browser", () => {
		expect(
			isCrawler(
				"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0",
			),
		).toBe(false);
	});

	it("returns false for empty UA", () => {
		expect(isCrawler("")).toBe(false);
	});

	it("handles null UA", () => {
		expect(isCrawler(null as unknown as string)).toBe(false);
	});
});

describe("generateFingerprint", () => {
	it("produces a 16-character hex string", () => {
		const result = generateFingerprint("1.2.3.4", "Mozilla/5.0");
		expect(result).toMatch(/^[0-9a-f]{16}$/);
	});

	it("is deterministic for the same inputs within the same day", () => {
		const a = generateFingerprint("1.2.3.4", "Mozilla/5.0");
		const b = generateFingerprint("1.2.3.4", "Mozilla/5.0");
		expect(a).toBe(b);
	});

	it("produces different fingerprints for different IPs", () => {
		const a = generateFingerprint("1.2.3.4", "Mozilla/5.0");
		const b = generateFingerprint("5.6.7.8", "Mozilla/5.0");
		expect(a).not.toBe(b);
	});

	it("produces different fingerprints for different UAs", () => {
		const a = generateFingerprint("1.2.3.4", "Mozilla/5.0 Chrome");
		const b = generateFingerprint("1.2.3.4", "Mozilla/5.0 Firefox");
		expect(a).not.toBe(b);
	});

	it("handles empty strings", () => {
		const result = generateFingerprint("", "");
		expect(result).toMatch(/^[0-9a-f]{16}$/);
	});
});

describe("parseUtmParams", () => {
	it("extracts all UTM parameters", () => {
		const result = parseUtmParams({
			utm_source: "instagram",
			utm_medium: "social",
			utm_campaign: "launch_2024",
		});
		expect(result).toEqual({
			utm_source: "instagram",
			utm_medium: "social",
			utm_campaign: "launch_2024",
		});
	});

	it("returns undefined for missing UTM params", () => {
		const result = parseUtmParams({});
		expect(result).toEqual({
			utm_source: undefined,
			utm_medium: undefined,
			utm_campaign: undefined,
		});
	});

	it("extracts partial UTM params", () => {
		const result = parseUtmParams({ utm_source: "threads" });
		expect(result).toEqual({
			utm_source: "threads",
			utm_medium: undefined,
			utm_campaign: undefined,
		});
	});

	it("ignores non-string UTM values", () => {
		const result = parseUtmParams({
			utm_source: 123,
			utm_medium: ["array"],
			utm_campaign: null,
		});
		expect(result).toEqual({
			utm_source: undefined,
			utm_medium: undefined,
			utm_campaign: undefined,
		});
	});

	it("ignores non-UTM query params", () => {
		const result = parseUtmParams({
			page: "1",
			sort: "desc",
			utm_source: "newsletter",
		});
		expect(result).toEqual({
			utm_source: "newsletter",
			utm_medium: undefined,
			utm_campaign: undefined,
		});
	});
});

describe("appendUtms", () => {
	it("appends UTM params to a clean URL", () => {
		const result = appendUtms("https://example.com/page", {
			utm_source: "instagram",
			utm_medium: "bio",
		});
		const url = new URL(result);
		expect(url.searchParams.get("utm_source")).toBe("instagram");
		expect(url.searchParams.get("utm_medium")).toBe("bio");
	});

	it("preserves existing query params", () => {
		const result = appendUtms("https://example.com/page?ref=home", {
			utm_source: "threads",
		});
		const url = new URL(result);
		expect(url.searchParams.get("ref")).toBe("home");
		expect(url.searchParams.get("utm_source")).toBe("threads");
	});

	it("does not overwrite existing UTM params on the URL", () => {
		const result = appendUtms("https://example.com?utm_source=original", {
			utm_source: "new",
		});
		const url = new URL(result);
		expect(url.searchParams.get("utm_source")).toBe("original");
	});

	it("skips undefined values", () => {
		const result = appendUtms("https://example.com", {
			utm_source: "test",
			utm_medium: undefined,
		});
		const url = new URL(result);
		expect(url.searchParams.get("utm_source")).toBe("test");
		expect(url.searchParams.has("utm_medium")).toBe(false);
	});

	it("returns original URL for invalid URLs", () => {
		const badUrl = "not-a-valid-url";
		const result = appendUtms(badUrl, { utm_source: "test" });
		expect(result).toBe(badUrl);
	});

	it("handles URL with hash fragment", () => {
		const result = appendUtms("https://example.com/page#section", {
			utm_source: "test",
		});
		const url = new URL(result);
		expect(url.searchParams.get("utm_source")).toBe("test");
		expect(url.hash).toBe("#section");
	});

	it("handles empty UTM object", () => {
		const result = appendUtms("https://example.com/page", {});
		expect(result).toBe("https://example.com/page");
	});
});
