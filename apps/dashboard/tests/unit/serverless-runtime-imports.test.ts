import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function read(relativePath: string) {
	return readFileSync(join(process.cwd(), relativePath), "utf8");
}

describe("serverless runtime imports", () => {
	it("uses emitted JavaScript specifiers for pipeline contracts in API code", () => {
		const source = read("api/_lib/publishPreflight.ts");

		expect(source).toContain('from "../../pipeline_contracts/typescript.js"');
		expect(source).not.toContain('from "../../pipeline_contracts/typescript"');
	});
});
