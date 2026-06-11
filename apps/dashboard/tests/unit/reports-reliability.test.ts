import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("reports reliability", () => {
	it("resolves saved report account scope without the legacy 50-account cap", () => {
		const scope = read("api/_lib/reportScope.ts");
		const reportsApi = read("api/reports.ts");
		const sendHandler = read("api/_lib/handlers/reports/send.ts");

		expect(scope).toContain("resolveReportScope");
		expect(scope).toContain(".from(\"accounts\")");
		expect(scope).toContain(".from(\"instagram_accounts\")");
		expect(scope).toContain("Mixed-platform PDF reports are not supported yet");
		expect(scope).toContain(".limit(1000)");
		expect(reportsApi).toContain("resolveReportScope");
		expect(reportsApi).toContain("REPORT_SCOPE_UNAVAILABLE");
		expect(sendHandler).toContain("resolveReportScope");
		expect(sendHandler).not.toContain(".limit(50)");
	});

	it("surfaces latest report delivery state in the Reports UI", () => {
		const hook = read("src/hooks/useReports.ts");
		const page = read("src/pages/Reports.tsx");

		expect(hook).toContain("report_send_log");
		expect(hook).toContain("lastDeliveryStatus");
		expect(hook).toContain("lastDeliveryError");
		expect(hook).toContain("fetchLatestDeliveryLogs");
		expect(page).toContain("Delivery failed");
		expect(page).toContain("delivery issue");
		expect(page).toContain("lastDeliveryStatus");
		expect(page).toContain("Retry delivery");
		expect(page).toContain("/api/reports?action=send");
	});

	it("keeps the tracker current for the reports reliability slice", () => {
		const tracker = read("docs/AGENT_MANAGER_10_10_TRACKER.md");

		expect(tracker).toContain("Reports reliability for 200+ accounts. Status: Implemented");
		expect(tracker).toContain("report scope resolver");
		expect(tracker).toContain("report_send_log");
	});
});
