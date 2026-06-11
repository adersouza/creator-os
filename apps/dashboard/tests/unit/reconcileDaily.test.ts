import { describe, expect, it } from "vitest";

import { isRecentReconcileOrphan } from "@/api/cron/reconcile-daily";

describe("reconcile-daily orphan freshness", () => {
	it("treats recent missing Meta posts as webhook-loss orphans", () => {
		const now = Date.parse("2026-06-05T12:00:00.000Z");
		const publishedAt = "2026-06-04T12:00:00.000Z";

		expect(isRecentReconcileOrphan(publishedAt, now, 72 * 60 * 60 * 1000)).toBe(true);
	});

	it("ignores old historical Meta posts for daily orphan insertion", () => {
		const now = Date.parse("2026-06-05T12:00:00.000Z");
		const historicalPost = "2025-09-26T12:00:00.000Z";

		expect(isRecentReconcileOrphan(historicalPost, now, 72 * 60 * 60 * 1000)).toBe(false);
	});

	it("keeps missing or malformed timestamps eligible so fresh anomalies are not hidden", () => {
		const now = Date.parse("2026-06-05T12:00:00.000Z");

		expect(isRecentReconcileOrphan(undefined, now, 72 * 60 * 60 * 1000)).toBe(true);
		expect(isRecentReconcileOrphan("not-a-date", now, 72 * 60 * 60 * 1000)).toBe(true);
	});
});
