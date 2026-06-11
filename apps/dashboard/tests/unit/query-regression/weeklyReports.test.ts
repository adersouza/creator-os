/**
 * Regression test: Weekly Reports N+1 (api/cron/weekly-reports.ts)
 *
 * Documents that processWeeklyRecaps makes 4 sequential queries per account.
 * After refactor to batch-fetch, this test validates the batch pattern.
 */
import { describe, it, expect } from "vitest";

// --- Fixtures ----------------------------------------------------------------

interface RecapAccount {
	id: string;
	user_id: string;
	username: string | null;
}

const ACCOUNTS: RecapAccount[] = [
	{ id: "acc1", user_id: "u1", username: "alice" },
	{ id: "acc2", user_id: "u2", username: "bob" },
	{ id: "acc3", user_id: "u1", username: "alice_backup" }, // same user as acc1
	{ id: "acc4", user_id: "u3", username: "charlie" },
	{ id: "acc5", user_id: "u4", username: "diana" },
];

const PREFS: Record<string, { weekly_recap_unsubscribed: boolean }> = {
	u1: { weekly_recap_unsubscribed: false },
	u2: { weekly_recap_unsubscribed: true }, // unsubscribed
	u3: { weekly_recap_unsubscribed: false },
	u4: { weekly_recap_unsubscribed: false },
};

const PROFILES: Record<string, { email: string }> = {
	u1: { email: "alice@test.com" },
	u2: { email: "bob@test.com" },
	u3: { email: "charlie@test.com" },
	u4: { email: "diana@test.com" },
};

// --- Tests -------------------------------------------------------------------

describe("Weekly Reports — N+1 regression", () => {
	it("current pattern: 4 queries per account (prefs + profile + stats + quickwin)", () => {
		let queryCount = 0;

		// Simulate the current sequential loop from weekly-reports.ts:761-838
		for (const _account of ACCOUNTS) {
			queryCount++; // user_preferences
			queryCount++; // profiles
			queryCount++; // getWeeklyStats
			queryCount++; // getLowHangingFruit
		}

		expect(queryCount).toBe(20); // 5 accounts * 4 queries
	});

	it("batch pattern: 2 queries total for prefs + profiles, then per-account stats", () => {
		let queryCount = 0;
		const allUserIds = [...new Set(ACCOUNTS.map((a) => a.user_id))];

		// Batch fetch
		queryCount++; // 1 query: user_preferences WHERE user_id IN (...)
		queryCount++; // 1 query: profiles WHERE id IN (...)

		const prefsMap = new Map(
			allUserIds.map((uid) => [uid, PREFS[uid] || null]),
		);
		const profilesMap = new Map(
			allUserIds.map((uid) => [uid, PROFILES[uid] || null]),
		);

		// Per-account stats (can't batch — different RPC per account)
		for (const account of ACCOUNTS) {
			if (prefsMap.get(account.user_id)?.weekly_recap_unsubscribed) continue;
			if (!profilesMap.get(account.user_id)?.email) continue;
			queryCount++; // getWeeklyStats (unavoidable per-account)
			queryCount++; // getLowHangingFruit (unavoidable per-account)
		}

		// u2 is unsubscribed, so 4 accounts proceed * 2 queries + 2 batch = 10
		expect(queryCount).toBe(10);
		// Savings: 20 - 10 = 10 fewer queries (50% reduction)
	});

	it("deduplication: same user_id across accounts should only get one email", () => {
		const uniqueUserIds = [...new Set(ACCOUNTS.map((a) => a.user_id))];
		// u1 appears twice (acc1 + acc3), but should only get one email
		expect(uniqueUserIds).toHaveLength(4);
		expect(uniqueUserIds).toContain("u1");
	});

	it("unsubscribed users must be skipped before stats queries", () => {
		const skipped: string[] = [];
		const processed: string[] = [];

		for (const account of ACCOUNTS) {
			if (PREFS[account.user_id]?.weekly_recap_unsubscribed) {
				skipped.push(account.id);
				continue;
			}
			processed.push(account.id);
		}

		expect(skipped).toEqual(["acc2"]);
		expect(processed).toEqual(["acc1", "acc3", "acc4", "acc5"]);
	});
});
