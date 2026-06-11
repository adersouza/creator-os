import { describe, expect, it } from "vitest";
import { createScaleFixture } from "../../e2e/helpers/scaleFixtures";

describe("scale e2e fixtures", () => {
	it("creates a deterministic 200-account mixed-platform workspace", () => {
		const fixture = createScaleFixture();

		expect(fixture.accounts).toHaveLength(200);
		expect(fixture.threadsAccounts).toHaveLength(100);
		expect(fixture.instagramAccounts).toHaveLength(100);
		expect(fixture.groups).toHaveLength(8);
		expect(fixture.groups.every((group) => group.account_ids.length > 0)).toBe(true);
	});

	it("seeds all operator surfaces used by the scale browser suite", () => {
		const fixture = createScaleFixture();
		const snapshot = fixture.operatorSnapshot as {
			tasks: unknown[];
			pendingApprovals: unknown[];
			failedPosts: unknown[];
			opsHealth: { unhealthyAccounts: unknown[] };
			fleetCapacity: { accounts: unknown[]; days: unknown[] };
			aiEvalSummary: { total: number };
		};

		expect(snapshot.tasks.length).toBeGreaterThan(0);
		expect(snapshot.pendingApprovals.length).toBeGreaterThan(0);
		expect(snapshot.failedPosts.length).toBeGreaterThan(0);
		expect(snapshot.opsHealth.unhealthyAccounts.length).toBeGreaterThan(0);
		expect(snapshot.fleetCapacity.accounts).toHaveLength(200);
		expect(snapshot.fleetCapacity.days).toHaveLength(7);
		expect(snapshot.aiEvalSummary.total).toBeGreaterThan(0);
		expect(fixture.approvals.length).toBeGreaterThan(0);
		expect(fixture.inboxMessages.length).toBeGreaterThan(0);
		expect(fixture.listeningAlerts.length).toBeGreaterThan(0);
		expect(fixture.listeningResults.length).toBeGreaterThan(0);
		expect(fixture.competitors.length).toBeGreaterThan(0);
		expect(fixture.competitorPosts.length).toBeGreaterThan(0);
		expect(fixture.trendKeywords.length).toBeGreaterThan(0);
		expect(fixture.trendPosts.length).toBeGreaterThan(0);
		expect(snapshot.tasks.some((task) => JSON.stringify(task).includes("qstash_dlq"))).toBe(true);
		expect(snapshot.tasks.some((task) => JSON.stringify(task).includes("qstash_dispatch_backlog"))).toBe(true);
		expect(fixture.reports.length).toBeGreaterThan(0);
		expect(fixture.reportSendLogs.some((log) => log.status === "failed")).toBe(true);
	});
});
