import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("Meta compliance verification note", () => {
	it("keeps official Meta docs as the source for encoded platform policy", () => {
		const doc = read("docs/META_COMPLIANCE_VERIFICATION_2026.md");
		const tracker = read("docs/AGENT_MANAGER_10_10_TRACKER.md");

		expect(doc).toContain("https://developers.facebook.com/docs/instagram-platform/content-publishing/");
		expect(doc).toContain("https://developers.facebook.com/docs/threads/");
		expect(doc).toContain("https://developers.facebook.com/docs/instagram-api/reference/media/comments/");
		expect(doc).toContain("https://developers.facebook.com/docs/graph-api/overview/rate-limiting/");
		expect(doc).toContain("Use official Meta APIs only");
		expect(doc).toContain("Claims Not Yet Safe To Hard-Code");
		expect(tracker).toContain("META_COMPLIANCE_VERIFICATION_2026.md");
	});
});
