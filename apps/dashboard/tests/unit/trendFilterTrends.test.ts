import { describe, expect, it, vi } from "vitest";

import { getTodayPostCount } from "../../api/_lib/handlers/trend-pipeline/filterTrends";

describe("trend pipeline daily cap counting", () => {
	it("counts queued, posted, and review trend discoveries toward the daily cap", async () => {
		const inMock = vi.fn().mockResolvedValue({ count: 2 });
		const inStatusMock = vi.fn().mockReturnValue({ gte: inMock });
		const eqGroupMock = vi.fn().mockReturnValue({ in: inStatusMock });
		const selectMock = vi.fn().mockReturnValue({ eq: eqGroupMock });
		const fromMock = vi.fn().mockReturnValue({ select: selectMock });

		const count = await getTodayPostCount({ from: fromMock }, "group-1");

		expect(count).toBe(2);
		expect(fromMock).toHaveBeenCalledWith("trend_discoveries");
		expect(inStatusMock).toHaveBeenCalledWith("status", [
			"queued",
			"posted",
			"needs_review",
		]);
	});
});
