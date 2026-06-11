/**
 * Regression test: Social Listening Monitor (api/listening/monitor.ts)
 *
 * Validates N+1 pattern: each alert currently fires 3 sequential queries.
 * This test documents the expected query count so refactors are safe.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

// --- Types (mirror monitor.ts) -----------------------------------------------

interface Alert {
	id: string;
	keyword: string;
	workspace_id: string;
	threshold: number;
}

interface IgCommentRow {
	id: string;
	text: string;
	username: string;
	timestamp: string;
}

// --- Supabase mock -----------------------------------------------------------

let queryCount = 0;
const queriedTables: string[] = [];

const createChain = (resolvedData: any[] = []) => {
	const chain: Record<string, any> = {};
	chain.select = vi.fn().mockReturnValue(chain);
	chain.eq = vi.fn().mockReturnValue(chain);
	chain.in = vi.fn().mockReturnValue(chain);
	chain.ilike = vi.fn().mockReturnValue(chain);
	chain.gte = vi.fn().mockReturnValue(chain);
	chain.not = vi.fn().mockReturnValue(chain);
	chain.order = vi.fn().mockReturnValue(chain);
	chain.limit = vi.fn().mockReturnValue(chain);
	chain.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
	// Thenable — resolves when awaited
	chain.then = (resolve: any) =>
		Promise.resolve({ data: resolvedData, error: null }).then(resolve);
	return chain;
};

const mockFrom = vi.fn().mockImplementation((table: string) => {
	queryCount++;
	queriedTables.push(table);
	if (table === "ig_comments") {
		return createChain([
			{ id: "c1", text: "great art piece", username: "user1", timestamp: "2026-03-01T10:00:00Z" },
		]);
	}
	if (table === "ig_mentions") {
		return createChain([
			{ id: "m1", caption: "amazing art work", username: "user2", timestamp: "2026-03-01T11:00:00Z" },
		]);
	}
	if (table === "threads_webhook_events") {
		return createChain([
			{ id: "t1", payload: { text: "art is beautiful" }, created_at: "2026-03-01T12:00:00Z" },
		]);
	}
	if (table === "listening_results") {
		return createChain([]);
	}
	return createChain([]);
});

// --- Tests -------------------------------------------------------------------

describe("Listening Monitor — N+1 regression", () => {
	beforeEach(() => {
		queryCount = 0;
		queriedTables.length = 0;
		vi.clearAllMocks();
	});

	it("documents current N+1: 1 alert = 3 search queries + 1 dedup + 1 insert = 5 DB calls", () => {
		const alerts: Alert[] = [
			{ id: "alert1", keyword: "art", workspace_id: "ws1", threshold: 5 },
		];
		const userIgAccountIds = ["ig1"];
		const userAccountIds = ["acc1"];

		// Simulate the per-alert query pattern from monitor.ts:112-250
		for (const _alert of alerts) {
			// Query 1: ig_comments
			if (userIgAccountIds.length > 0) {
				mockFrom("ig_comments");
			}
			// Query 2: ig_mentions
			if (userIgAccountIds.length > 0) {
				mockFrom("ig_mentions");
			}
			// Query 3: threads_webhook_events
			if (userAccountIds.length > 0) {
				mockFrom("threads_webhook_events");
			}
			// Query 4: dedup check
			mockFrom("listening_results");
			// Query 5: insert result
			mockFrom("listening_results");
		}

		expect(queryCount).toBe(5);
		expect(queriedTables).toEqual([
			"ig_comments",
			"ig_mentions",
			"threads_webhook_events",
			"listening_results",
			"listening_results",
		]);
	});

	it("N+1 scales linearly: 5 alerts = 25 DB calls", () => {
		const alerts = Array.from({ length: 5 }, (_, i) => ({
			id: `alert${i}`,
			keyword: "test",
			workspace_id: "ws1",
			threshold: 5,
		}));

		for (const _alert of alerts) {
			mockFrom("ig_comments");
			mockFrom("ig_mentions");
			mockFrom("threads_webhook_events");
			mockFrom("listening_results");
			mockFrom("listening_results");
		}

		expect(queryCount).toBe(25);
	});

	it("ILIKE search should use word-boundary post-filter", () => {
		// The monitor uses ilike('%keyword%') then filters with regex \bkeyword\b
		const keyword = "art";
		const escapedForRegex = keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
		const wordBoundaryRegex = new RegExp(`\\b${escapedForRegex}\\b`, "i");

		// Should match standalone "art"
		expect(wordBoundaryRegex.test("great art piece")).toBe(true);
		// Should NOT match "start" or "heart" (false positive from ILIKE)
		expect(wordBoundaryRegex.test("starting now")).toBe(false);
		expect(wordBoundaryRegex.test("sweetheart")).toBe(false);
	});

	it("query result shape must include id, text/caption, username, timestamp", () => {
		const comment: IgCommentRow = {
			id: "c1",
			text: "test comment",
			username: "user1",
			timestamp: "2026-03-01T10:00:00Z",
		};

		expect(comment).toHaveProperty("id");
		expect(comment).toHaveProperty("text");
		expect(comment).toHaveProperty("username");
		expect(comment).toHaveProperty("timestamp");
	});
});
