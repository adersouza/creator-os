import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("calendar portfolio capacity mode", () => {
	it("renders the portfolio view from the operator fleet capacity snapshot", () => {
		const calendar = read("src/pages/Calendar.tsx");
		const portfolio = read("src/components/calendar/PortfolioMatrix.tsx");

		expect(calendar).toContain("viewMode === 'portfolio'");
		expect(calendar).toContain("capacityStart={formatWeekStartForUrl(weekStart)}");
		expect(calendar).toContain("onComposeForAccountDate={openComposerForAccountDate}");
		expect(portfolio).toContain("useOperatorSnapshot({ capacityStart");
		expect(portfolio).toContain("Portfolio capacity");
		expect(portfolio).toContain("account.days");
		expect(portfolio).toContain("hasGap");
		expect(portfolio).toContain("hasConflict");
		expect(portfolio).toContain("approvalPending");
		expect(portfolio).toContain("deadLetter");
	});

	it("routes matrix actions to existing safe recovery surfaces", () => {
		const portfolio = read("src/components/calendar/PortfolioMatrix.tsx");

		expect(portfolio).toContain("/approval-queue?status=pending");
		expect(portfolio).toContain("status=failed");
		expect(portfolio).toContain("/api/operator?action=dry-run");
		expect(portfolio).toContain("/api/operator?action=request-approval");
		expect(portfolio).toContain("trigger_queue_fill");
		expect(portfolio).toContain("reschedule_post");
		expect(portfolio).toContain("requestCapacityApproval");
		expect(portfolio).toContain("Resolve");
	});
});
