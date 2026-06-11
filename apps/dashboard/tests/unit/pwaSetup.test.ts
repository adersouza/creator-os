import { describe, expect, it } from "vitest";
import { detectPwaInstallState } from "@/lib/pwaSetup";

describe("PWA setup detector", () => {
	it("detects iPhone Safari before install", () => {
		expect(
			detectPwaInstallState({
				userAgent:
					"Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Version/17.4 Mobile/15E148 Safari/604.1",
				pushSupported: true,
			}),
		).toBe("iphone-safari");
	});

	it("detects installed iOS PWA display mode", () => {
		expect(
			detectPwaInstallState({
				userAgent:
					"Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Version/17.4 Mobile/15E148 Safari/604.1",
				displayModeStandalone: true,
				pushSupported: true,
			}),
		).toBe("installed-ios");
	});

	it("detects Android Chrome with push support", () => {
		expect(
			detectPwaInstallState({
				userAgent:
					"Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/124.0.0.0 Mobile Safari/537.36",
				pushSupported: true,
			}),
		).toBe("android-chrome");
	});

	it("detects unsupported browsers when push is unavailable", () => {
		expect(
			detectPwaInstallState({
				userAgent: "Mozilla/5.0 Firefox/122.0",
				pushSupported: false,
			}),
		).toBe("unsupported");
	});
});
