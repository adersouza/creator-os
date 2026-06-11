import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("operator manifest docs", () => {
	it("documents the canonical manifest fields and representative executable actions", () => {
		const manifestDoc = read("docs/OPERATOR_ACTION_MANIFEST.md");
		const apiReference = read("docs/API_REFERENCE.md");
		const packageJson = read("package.json");
		const docsCheck = read("scripts/check-operator-docs.mjs");

		for (const field of [
			"toolName",
			"riskLevel",
			"sideEffectType",
			"requiresApproval",
			"requiresIdempotencyKey",
			"supportsDryRun",
			"hostedAvailable",
			"rollbackSupport",
			"compensationActionName",
			"compensationDescription",
			"compensationRequiresApproval",
			"rollbackWindowHours",
		]) {
			expect(manifestDoc).toContain(`\`${field}\``);
			expect(apiReference).toContain(field);
		}

		for (const action of [
			"publish_post",
			"schedule_post",
			"reschedule_post",
			"send_reply",
			"trigger_queue_fill",
			"override_account_state",
		]) {
			expect(manifestDoc).toContain(`\`${action}\``);
		}

		expect(apiReference).toContain("| `source-workflow` | PATCH |");
		expect(docsCheck).toContain("requiredFields");
		expect(packageJson).toContain("docs:check-operator");
	});
});
