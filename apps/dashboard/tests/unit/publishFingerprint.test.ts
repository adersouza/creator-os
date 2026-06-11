import { describe, expect, it } from "vitest";
import {
	buildPublishFingerprint,
	fingerprintMedia,
	normalizePublishText,
} from "../../api/_lib/handlers/auto-post/publishFingerprint.js";

describe("autoposter publish fingerprints", () => {
	it("normalizes casing, spacing, punctuation, and urls before hashing", () => {
		expect(normalizePublishText("  Hello, WORLD!! https://x.test/a  ")).toBe(
			"hello world",
		);
	});

	it("uses a stable media fingerprint independent of url order", () => {
		expect(fingerprintMedia(["HTTPS://cdn.test/B.jpg", "https://cdn.test/a.jpg"])).toBe(
			fingerprintMedia(["https://cdn.test/a.jpg", "https://cdn.test/b.jpg"]),
		);
		expect(fingerprintMedia([])).toBe("no_media");
	});

	it("scopes publish fingerprints by workspace, account, platform, text, and media", () => {
		const base = buildPublishFingerprint({
			workspaceId: "workspace-1",
			accountId: "account-1",
			platform: "threads",
			content: "Same text",
			mediaUrls: ["https://cdn.test/a.jpg"],
		});
		const same = buildPublishFingerprint({
			workspaceId: "workspace-1",
			accountId: "account-1",
			platform: "threads",
			content: "same   text",
			mediaUrls: ["https://cdn.test/a.jpg"],
		});
		const differentAccount = buildPublishFingerprint({
			workspaceId: "workspace-1",
			accountId: "account-2",
			platform: "threads",
			content: "Same text",
			mediaUrls: ["https://cdn.test/a.jpg"],
		});

		expect(base.normalizedTextHash).toBe(same.normalizedTextHash);
		expect(base.mediaFingerprint).toBe(same.mediaFingerprint);
		expect(base.publishFingerprint).toBe(same.publishFingerprint);
		expect(base.publishFingerprint).not.toBe(differentAccount.publishFingerprint);
	});
});
