/**
 * analyticsDispatch — pipeline-active guard
 *
 * Tests that dispatchAnalyticsSync() defers when analytics-pipeline is running
 * (idempotent Redis flag replaces the old clock-based 2:02 AM skip).
 *
 * When `analytics-pipeline:active` key is set in Redis, dispatch must:
 * - return 0 immediately
 * - never call QStash publishJSON
 * - log the defer reason
 *
 * vi.mock must be at module scope (Vitest hoists it).
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { dispatchAnalyticsSync } from "../../api/_lib/analyticsDispatch";

// ── Redis mock ───────────────────────────────────────────────────────────────

const mockGet = vi.fn();
const mockSet = vi.fn().mockResolvedValue("OK");

vi.mock("../../api/_lib/redis.js", () => ({
	getRedis: () => ({ get: mockGet, set: mockSet }),
}));

// ── QStash mock ──────────────────────────────────────────────────────────────

const mockPublishJSON = vi.fn().mockResolvedValue({ messageId: "msg-1" });

vi.mock("../../api/_lib/qstash.js", () => ({
	getQStashClient: () => ({ publishJSON: mockPublishJSON }),
}));

// ── Supabase mock — return empty arrays so the function exits cleanly ─────────
// The query builder is both chainable AND thenable so that:
//   let q = db().from(...).select(...).limit(N);
//   if (cond) q = q.or(...);         // must have .or()
//   const { data } = await q;        // must be awaitable

function makeQueryBuilder(): Record<string, unknown> {
	const builder: Record<string, unknown> = {
		then: (
			resolve: (v: { data: unknown[]; error: null }) => unknown,
			_reject?: (e: unknown) => unknown,
		) => Promise.resolve(resolve({ data: [], error: null })),
	};
	for (const method of [
		"select",
		"not",
		"neq",
		"eq",
		"is",
		"or",
		"order",
		"limit",
	]) {
		builder[method] = () => builder;
	}
	return builder;
}

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabase: () => ({
		from: () => makeQueryBuilder(),
		rpc: vi.fn().mockResolvedValue({ data: null, error: null }),
	}),
}));

// ── Logger mock ───────────────────────────────────────────────────────────────
// vi.hoisted() is required here because vi.mock() factories are hoisted to
// module scope; a plain `const mockLogInfo = vi.fn()` would not be initialized
// at the point the factory runs.

const mockLogInfo = vi.hoisted(() => vi.fn());
vi.mock("../../api/_lib/logger.js", () => ({
	logger: { info: mockLogInfo, warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("dispatchAnalyticsSync — pipeline-active guard", () => {
	beforeEach(() => {
		mockGet.mockReset();
		mockPublishJSON.mockReset().mockResolvedValue({ messageId: "msg-1" });
		mockLogInfo.mockReset();
		process.env.APP_URL = "https://juno33.com";
	});

	it("returns 0 and skips QStash when analytics-pipeline:active is set", async () => {
		// Simulate the pipeline-active flag being set
		mockGet.mockImplementation((key: string) => {
			if (key === "analytics-pipeline:active") return Promise.resolve("1");
			return Promise.resolve(null); // cohort-classify and dedup keys absent
		});

		const dispatched = await dispatchAnalyticsSync();

		expect(dispatched).toBe(0);
		expect(mockPublishJSON).not.toHaveBeenCalled();
	});

	it("logs the defer reason when pipeline is active", async () => {
		mockGet.mockImplementation((key: string) => {
			if (key === "analytics-pipeline:active") return Promise.resolve("1");
			return Promise.resolve(null);
		});

		await dispatchAnalyticsSync();

		expect(mockLogInfo).toHaveBeenCalledWith(
			expect.stringContaining("analytics-pipeline"),
		);
	});

	it("proceeds with dispatch when analytics-pipeline:active is absent", async () => {
		// All Redis gets return null → pipeline not active, no dedup entries
		mockGet.mockResolvedValue(null);

		const dispatched = await dispatchAnalyticsSync();

		// DB returns empty arrays, so dispatched = 0, but the function ran to completion
		// without early-returning due to the pipeline-active guard.
		// The key assertion: it did NOT short-circuit via the pipeline-active path.
		expect(dispatched).toBe(0); // empty DB → nothing to dispatch
		// If the guard had fired, logger would have been called with the defer message.
		// We verify it was NOT called with that message.
		const deferCallArgs = mockLogInfo.mock.calls.find((args: unknown[]) =>
			typeof args[0] === "string" && args[0].includes("Dispatch deferred"),
		);
		expect(deferCallArgs).toBeUndefined();
	});

	it("respects the active flag even when set to a non-'1' truthy value", async () => {
		// Redis might return a non-"1" truthy value depending on how it was set
		mockGet.mockImplementation((key: string) => {
			if (key === "analytics-pipeline:active") return Promise.resolve("true");
			return Promise.resolve(null);
		});

		const dispatched = await dispatchAnalyticsSync();
		expect(dispatched).toBe(0);
		expect(mockPublishJSON).not.toHaveBeenCalled();
	});
});
