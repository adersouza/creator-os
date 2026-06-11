import { beforeEach, describe, expect, it, vi } from "vitest";

const mockRedisGet = vi.fn();
const mockRedisSet = vi.fn();
const mockFrom = vi.fn();
const mockAlertWarn = vi.fn();

vi.mock("../../api/_lib/redis.js", () => ({
	getRedis: () => ({
		get: mockRedisGet,
		set: mockRedisSet,
	}),
}));

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabaseAny: () => ({
		from: mockFrom,
	}),
}));

vi.mock("../../api/_lib/alerting.js", () => ({
	alertWarn: (...args: unknown[]) => mockAlertWarn(...args),
}));

vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		warn: vi.fn(),
		info: vi.fn(),
		debug: vi.fn(),
		error: vi.fn(),
	},
}));

function staleRateLimitRows(count: number) {
	const chain: Record<string, any> = {};
	for (const method of ["select", "gt", "lt", "limit"]) {
		chain[method] = vi.fn().mockReturnValue(chain);
	}
	chain.then = (resolve: (value: unknown) => void) =>
		resolve({
			data: Array.from({ length: count }, (_, index) => ({
				account_id: `account-${index}`,
			})),
			error: null,
		});
	return chain;
}

describe("isMetaApiHealthy", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockRedisGet.mockResolvedValue(null);
		mockRedisSet.mockResolvedValue("OK");
	});

	it("fails open without Discord noise when local Threads rate-limit bookkeeping rows are stale", async () => {
		mockFrom.mockReturnValue(staleRateLimitRows(3));

		const { isMetaApiHealthy } = await import("../../api/_lib/metaApiHealth.js");
		const healthy = await isMetaApiHealthy("threads");

		expect(healthy).toBe(true);
		expect(mockAlertWarn).not.toHaveBeenCalled();
		expect(mockRedisSet).toHaveBeenCalledWith("meta-health:threads", "1", {
			ex: 300,
		});
	});

	it("does not create a stale-bookkeeping alert dedupe key", async () => {
		mockFrom.mockReturnValue(staleRateLimitRows(3));

		const { isMetaApiHealthy } = await import("../../api/_lib/metaApiHealth.js");
		const healthy = await isMetaApiHealthy("threads");

		expect(healthy).toBe(true);
		expect(mockAlertWarn).not.toHaveBeenCalled();
		expect(mockRedisSet).not.toHaveBeenCalledWith(
			"meta-health:threads:stale-bookkeeping-alert",
			expect.anything(),
			expect.anything(),
		);
	});
});
