import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();

describe("autoposter performance validation analytics handler", () => {
	it("registers the validation analytics action", () => {
		const source = readFileSync(join(root, "api/analytics.ts"), "utf8");

		expect(source).toContain('"autoposter-performance-validation"');
		expect(source).toContain(
			'analyticsSubHandler(\n\t\t"autoposter-performance-validation"',
		);
	});

	it("stays read-only and does not call attribution persistence paths", () => {
		const source = readFileSync(
			join(
				root,
				"api/_lib/handlers/analytics-sub/autoposter-performance-validation.ts",
			),
			"utf8",
		);

		expect(source).toContain("autoposter_post_performance_facts");
		expect(source).not.toContain("persistPerformanceFacts");
		expect(source).not.toContain("persistWinnerPatterns");
		expect(source).not.toContain("replaceStrategyRecommendations");
		expect(source).not.toContain("buildPerformanceFirstRecommendations");
		expect(source).not.toContain(".upsert(");
		expect(source).not.toContain(".update(");
		expect(source).not.toContain(".insert(");
	});
});
