import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();

describe("autoposter quality gate effectiveness analytics handler", () => {
	it("registers the quality gate effectiveness analytics action", () => {
		const source = readFileSync(join(root, "api/analytics.ts"), "utf8");

		expect(source).toContain('"autoposter-quality-gate-effectiveness"');
		expect(source).toContain(
			'analyticsSubHandler(\n\t\t"autoposter-quality-gate-effectiveness"',
		);
	});

	it("stays read-only and does not call mutation paths", () => {
		const source = readFileSync(
			join(
				root,
				"api/_lib/handlers/analytics-sub/autoposter-quality-gate-effectiveness.ts",
			),
			"utf8",
		);

		expect(source).toContain("autoposter_post_performance_facts");
		expect(source).toContain("auto_post_queue");
		expect(source).not.toContain(".upsert(");
		expect(source).not.toContain(".update(");
		expect(source).not.toContain(".insert(");
		expect(source).not.toContain("replaceStrategyRecommendations");
		expect(source).not.toContain("persistWinnerPatterns");
	});
});
