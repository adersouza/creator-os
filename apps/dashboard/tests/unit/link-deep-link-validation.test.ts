import { describe, expect, it } from "vitest";
import { isSafeDeepLinkUrl } from "../../api/_lib/handlers/links/shared.js";

describe("link-page deep link validation", () => {
	it("allows HTTPS Universal/App Links and known app schemes", () => {
		expect(isSafeDeepLinkUrl("https://example.com/product")).toBe(true);
		expect(isSafeDeepLinkUrl("instagram://user?username=test")).toBe(true);
		expect(isSafeDeepLinkUrl("barcelona://user/123")).toBe(true);
		expect(isSafeDeepLinkUrl("spotify://track/123")).toBe(true);
	});

	it("rejects browser escape and broad custom schemes", () => {
		expect(isSafeDeepLinkUrl("x-safari-https://example.com")).toBe(false);
		expect(isSafeDeepLinkUrl("googlechrome://example.com")).toBe(false);
		expect(isSafeDeepLinkUrl("intent://example.com/#Intent;end")).toBe(false);
		expect(isSafeDeepLinkUrl("randomapp://open")).toBe(false);
	});
});
