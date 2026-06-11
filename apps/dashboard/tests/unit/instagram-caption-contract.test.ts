import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();

describe("Instagram Campaign caption contract", () => {
	it("publishSinglePost sends the first-class Campaign Instagram caption to Meta", () => {
		const publishPost = readFileSync(
			resolve(root, "api/_lib/publishPost.ts"),
			"utf8",
		);
		const publishing = readFileSync(
			resolve(root, "api/_lib/instagram/publishing.ts"),
			"utf8",
		);

		expect(publishPost).toContain("campaignFactoryInstagramPostCaption");
		expect(publishPost).toContain("content: igContent");
		expect(publishPost).toContain("caption: igContent");
		expect(publishing).toContain("caption: postData.caption");
	});
});
