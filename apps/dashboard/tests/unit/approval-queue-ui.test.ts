import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("approval queue UI", () => {
	it("exposes exact-action review controls for 200-account operator use", () => {
		const page = read("src/pages/ApprovalQueue.tsx");

		expect(page).toContain("useSearchParams");
		expect(page).toContain("statusFilter");
		expect(page).toContain("riskFilter");
		expect(page).toContain("Exact action preview");
		expect(page).toContain("copyActionSummary");
		expect(page).toContain("decisionNotes");
		expect(page).toContain("approvalId");
		expect(page).toContain("payloadHash");
		expect(page).toContain("idempotencyKey");
		expect(page).toContain("reviseApproval");
		expect(page).toContain("/api/operator?action=revise-approval");
		expect(page).toContain("Edit and resubmit");
		expect(page).toContain("Resubmit revised");
		expect(page).toContain("rejectionTemplates");
		expect(page).toContain("diffPayload");
		expect(page).toContain("buildApprovalTimeline");
		expect(page).toContain("Approval history");
		expect(page).toContain("Exact intent bound");
		expect(page).toContain("Dispatch");
		expect(page).toContain("getEditablePayloadFields");
		expect(page).toContain("Structured editor");
		expect(page).toContain("Caption / post text");
		expect(page).toContain("Scheduled time");
		expect(page).toContain("Reply text");
		expect(page).toContain("executeApproval");
		expect(page).toContain("/api/operator?action=execute");
		expect(page).toContain("Dispatch failed");
		expect(page).toContain("Open recovery");
	});
});
