import { describe, expect, it } from "vitest";
import { detectPwaInstallState, pwaSetupCopy } from "./pwaSetup";

describe("detectPwaInstallState", () => {
	it("detects iPhone Safari before install", () => {
		expect(
			detectPwaInstallState({
				userAgent:
					"Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
				pushSupported: true,
			}),
		).toBe("iphone-safari");
	});

	it("detects installed iOS PWA", () => {
		expect(
			detectPwaInstallState({
				userAgent:
					"Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
				displayModeStandalone: true,
				pushSupported: true,
			}),
		).toBe("installed-ios");
	});

	it("detects Android Chrome with push support", () => {
		expect(
			detectPwaInstallState({
				userAgent:
					"Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
				pushSupported: true,
			}),
		).toBe("android-chrome");
	});

	it("returns unsupported when push APIs are unavailable", () => {
		expect(
			detectPwaInstallState({
				userAgent:
					"Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
				pushSupported: false,
			}),
		).toBe("unsupported");
	});
});

describe("pwaSetupCopy", () => {
	it("gives iPhone users the exact Home Screen and login sequence", () => {
		const copy = pwaSetupCopy("iphone-safari");
		expect(copy.steps).toContain("Open juno33.com in Safari");
		expect(copy.steps).toContain("Tap Share, then Add to Home Screen");
		expect(copy.steps).toContain("Log in and enable notifications");
	});

	it("keeps unsupported browsers on a manual fallback path", () => {
		const copy = pwaSetupCopy("unsupported");
		expect(copy.detail).toContain("Scheduling still creates the handoff");
		expect(copy.steps).toContain("Use the in-app handoff fallback");
	});
});
