import { describe, expect, it } from "vitest";
import {
	getAlternateRedirectErrors,
	isReservedSmartLinkCode,
} from "../../api/_lib/handlers/smart-links/shared.js";

describe("getAlternateRedirectErrors", () => {
	it("allows smart links with only a canonical target URL", () => {
		expect(
			getAlternateRedirectErrors({
				target_url: "https://example.com/landing",
			}),
		).toEqual([]);
	});

	it("rejects instagram-specific web redirect URLs", () => {
		expect(
			getAlternateRedirectErrors({
				target_url: "https://example.com/landing",
				ig_redirect_url: "https://example.com/instagram",
			}),
		).toContain(
			"ig_redirect_url is no longer supported. Smart links now use one canonical web destination for all visitors.",
		);
	});

	it("rejects threads-specific web redirect URLs", () => {
		expect(
			getAlternateRedirectErrors({
				target_url: "https://example.com/landing",
				threads_redirect_url: "https://example.com/threads",
			}),
		).toContain(
			"threads_redirect_url is no longer supported. Smart links now use one canonical web destination for all visitors.",
		);
	});

	it("rejects mobile-specific web redirect URLs", () => {
		expect(
			getAlternateRedirectErrors({
				target_url: "https://example.com/landing",
				mobile_redirect_url: "https://m.example.com/landing",
			}),
		).toContain(
			"mobile_redirect_url is no longer supported. Smart links now use one canonical web destination for all visitors.",
		);
	});
});

describe("isReservedSmartLinkCode", () => {
	it("reserves internal /go route segments", () => {
		expect(isReservedSmartLinkCode("convert")).toBe(true);
		expect(isReservedSmartLinkCode("R")).toBe(true);
		expect(isReservedSmartLinkCode("track")).toBe(true);
	});

	it("allows ordinary creator codes", () => {
		expect(isReservedSmartLinkCode("summer-sale")).toBe(false);
	});
});
