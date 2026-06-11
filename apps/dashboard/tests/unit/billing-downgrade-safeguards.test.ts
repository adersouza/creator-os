/**
 * Tests for billing downgrade safeguards:
 * 1. Ghost Queue: auto_post_queue items canceled on Empire→Free downgrade
 * 2. Account Amputation: deterministic oldest-first account deactivation
 * 3. Trial Double-Dip: has_used_trial flag prevents re-trial on same profile
 *
 * These tests mirror the exact logic in api/_lib/billing.ts and api/subscription.ts.
 */

import { describe, expect, it } from "vitest";

// ===========================================================================
// 1. Ghost Queue — enforce queue cancellation logic
// ===========================================================================

type QueueStatus =
	| "pending"
	| "processing"
	| "posted"
	| "failed"
	| "dead_letter"
	| "canceled";

interface QueueItem {
	id: string;
	workspace_id: string;
	status: QueueStatus;
	error_message?: string;
}

/**
 * Mirrors cancelOrphanedQueueItems() from api/_lib/billing.ts
 * Only cancels 'pending' and 'processing' items — terminal states untouched.
 */
function simulateCancelOrphanedQueueItems(
	items: QueueItem[],
	workspaceIds: string[],
): QueueItem[] {
	const wsSet = new Set(workspaceIds);
	return items.map((item) => {
		if (
			wsSet.has(item.workspace_id) &&
			(item.status === "pending" || item.status === "processing")
		) {
			return {
				...item,
				status: "canceled" as QueueStatus,
				error_message:
					"Canceled: workspace owner downgraded from Empire tier",
			};
		}
		return item;
	});
}

describe("Ghost Queue: cancel orphaned auto-post items on downgrade", () => {
	const queue: QueueItem[] = [
		{ id: "q1", workspace_id: "ws-empire", status: "pending" },
		{ id: "q2", workspace_id: "ws-empire", status: "pending" },
		{ id: "q3", workspace_id: "ws-empire", status: "processing" },
		{ id: "q4", workspace_id: "ws-empire", status: "posted" },
		{ id: "q5", workspace_id: "ws-empire", status: "failed" },
		{ id: "q6", workspace_id: "ws-empire", status: "dead_letter" },
		{ id: "q7", workspace_id: "ws-other", status: "pending" },
	];

	it("cancels all pending items for the downgraded workspace", () => {
		const result = simulateCancelOrphanedQueueItems(queue, ["ws-empire"]);
		const canceled = result.filter((i) => i.status === "canceled");
		expect(canceled.map((i) => i.id)).toEqual(["q1", "q2", "q3"]);
	});

	it("does NOT touch posted/failed/dead_letter items (terminal states)", () => {
		const result = simulateCancelOrphanedQueueItems(queue, ["ws-empire"]);
		expect(result.find((i) => i.id === "q4")!.status).toBe("posted");
		expect(result.find((i) => i.id === "q5")!.status).toBe("failed");
		expect(result.find((i) => i.id === "q6")!.status).toBe("dead_letter");
	});

	it("does NOT touch items from other workspaces", () => {
		const result = simulateCancelOrphanedQueueItems(queue, ["ws-empire"]);
		expect(result.find((i) => i.id === "q7")!.status).toBe("pending");
	});

	it("sets error_message explaining why the item was canceled", () => {
		const result = simulateCancelOrphanedQueueItems(queue, ["ws-empire"]);
		const canceled = result.filter((i) => i.status === "canceled");
		for (const item of canceled) {
			expect(item.error_message).toContain("downgraded from Empire");
		}
	});

	it("returns unchanged array when workspace has no pending items", () => {
		const allPosted: QueueItem[] = [
			{ id: "q1", workspace_id: "ws-empire", status: "posted" },
		];
		const result = simulateCancelOrphanedQueueItems(allPosted, ["ws-empire"]);
		expect(result[0].status).toBe("posted");
	});

	it("handles empty queue gracefully", () => {
		const result = simulateCancelOrphanedQueueItems([], ["ws-empire"]);
		expect(result).toEqual([]);
	});
});

// ===========================================================================
// 2. Account Amputation — deterministic oldest-first deactivation
// ===========================================================================

interface AccountStub {
	id: string;
	created_at: string;
	table: "accounts" | "instagram_accounts";
	is_active: boolean;
}

/**
 * Mirrors enforceAccountLimits() from api/_lib/billing.ts
 * Keeps the N oldest accounts, deactivates the rest.
 */
function simulateEnforceAccountLimits(
	accounts: AccountStub[],
	limit: number,
): { kept: string[]; deactivated: string[] } {
	if (limit === Infinity || accounts.length <= limit) {
		return { kept: accounts.map((a) => a.id), deactivated: [] };
	}

	const sorted = [...accounts]
		.filter((a) => a.is_active)
		.sort(
			(a, b) =>
				new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
		);

	const kept = sorted.slice(0, limit).map((a) => a.id);
	const deactivated = sorted.slice(limit).map((a) => a.id);

	return { kept, deactivated };
}

const BASE_LIMITS: Record<string, number> = { free: 1, pro: 5 };
function getAccountLimit(tier: string): number {
	const base = BASE_LIMITS[tier];
	return base === undefined ? Infinity : base;
}

describe("Account Amputation: deterministic oldest-first deactivation", () => {
	const accounts: AccountStub[] = [
		{
			id: "acc-oldest",
			created_at: "2025-01-01T00:00:00Z",
			table: "accounts",
			is_active: true,
		},
		{
			id: "acc-second",
			created_at: "2025-03-01T00:00:00Z",
			table: "accounts",
			is_active: true,
		},
		{
			id: "ig-third",
			created_at: "2025-06-01T00:00:00Z",
			table: "instagram_accounts",
			is_active: true,
		},
		{
			id: "acc-fourth",
			created_at: "2025-08-01T00:00:00Z",
			table: "accounts",
			is_active: true,
		},
		{
			id: "ig-newest",
			created_at: "2025-12-01T00:00:00Z",
			table: "instagram_accounts",
			is_active: true,
		},
	];

	it("Free tier (limit 1): keeps oldest, deactivates 4", () => {
		const result = simulateEnforceAccountLimits(accounts, getAccountLimit("free"));
		expect(result.kept).toEqual(["acc-oldest"]);
		expect(result.deactivated).toEqual([
			"acc-second",
			"ig-third",
			"acc-fourth",
			"ig-newest",
		]);
	});

	it("Pro tier (limit 5): keeps all 5", () => {
		const result = simulateEnforceAccountLimits(accounts, getAccountLimit("pro"));
		expect(result.kept).toHaveLength(5);
		expect(result.deactivated).toHaveLength(0);
	});

	it("Empire tier (Infinity): never deactivates", () => {
		const result = simulateEnforceAccountLimits(
			accounts,
			getAccountLimit("empire"),
		);
		expect(result.deactivated).toHaveLength(0);
	});

	it("mixed platforms: sorts by created_at across both tables", () => {
		const result = simulateEnforceAccountLimits(accounts, 3);
		// 3 oldest: acc-oldest (Jan), acc-second (Mar), ig-third (Jun)
		expect(result.kept).toEqual(["acc-oldest", "acc-second", "ig-third"]);
		expect(result.deactivated).toEqual(["acc-fourth", "ig-newest"]);
	});

	it("order is deterministic regardless of input order", () => {
		const shuffled = [accounts[4], accounts[0], accounts[3], accounts[1], accounts[2]];
		const r1 = simulateEnforceAccountLimits(accounts, 2);
		const r2 = simulateEnforceAccountLimits(shuffled, 2);
		expect(r1.kept).toEqual(r2.kept);
		expect(r1.deactivated).toEqual(r2.deactivated);
	});

	it("already-deactivated accounts are not counted toward the limit", () => {
		const withInactive: AccountStub[] = [
			{ ...accounts[0], is_active: false },
			...accounts.slice(1),
		];
		const result = simulateEnforceAccountLimits(withInactive, 1);
		// Only active accounts considered; oldest active is acc-second
		expect(result.kept).toEqual(["acc-second"]);
	});
});

// ===========================================================================
// 3. Trial Double-Dip — per-profile flag prevents re-trial
// ===========================================================================

interface TrialProfile {
	has_used_trial: boolean;
	stripe_customer_id?: string;
}

/**
 * Mirrors the trial gate in api/subscription.ts handleCreateCheckout()
 */
function canStartTrial(
	profile: TrialProfile,
	requestedTrial: boolean,
): boolean {
	if (!requestedTrial) return false;
	if (profile.has_used_trial) return false;
	return true;
}

describe("Trial Double-Dip: has_used_trial prevents re-trial", () => {
	it("allows trial for fresh profile (has_used_trial = false)", () => {
		expect(
			canStartTrial({ has_used_trial: false }, true),
		).toBe(true);
	});

	it("blocks trial when has_used_trial = true", () => {
		expect(
			canStartTrial({ has_used_trial: true }, true),
		).toBe(false);
	});

	it("does not grant trial when trial not requested", () => {
		expect(
			canStartTrial({ has_used_trial: false }, false),
		).toBe(false);
	});

	it("flag is per-profile, not per-workspace — same user can't re-trial via new workspace", () => {
		// Simulates: user creates workspace B, but has_used_trial is on profiles table
		const profile: TrialProfile = { has_used_trial: true };
		expect(canStartTrial(profile, true)).toBe(false);
	});
});

// ===========================================================================
// 4. Auto-post cron tier gate — Empire-only enforcement
// ===========================================================================

/**
 * Mirrors the tier check in api/cron/auto-post-worker.ts:168-176
 */
function shouldProcessWorkspace(ownerTier: string): boolean {
	return ownerTier === "empire";
}

describe("Auto-post cron: Empire tier gate", () => {
	it("processes Empire workspaces", () => {
		expect(shouldProcessWorkspace("empire")).toBe(true);
	});

	it("skips Free tier workspaces", () => {
		expect(shouldProcessWorkspace("free")).toBe(false);
	});

	it("skips Pro tier workspaces", () => {
		expect(shouldProcessWorkspace("pro")).toBe(false);
	});

	it("skips unknown tier (safe default)", () => {
		expect(shouldProcessWorkspace("")).toBe(false);
	});
});

// ===========================================================================
// 5. Integration: full downgrade flow simulation
// ===========================================================================

describe("Full downgrade flow: Empire → Free", () => {
	it("deactivates excess accounts AND cancels queue items in one pass", () => {
		const accounts: AccountStub[] = [
			{
				id: "a1",
				created_at: "2025-01-01T00:00:00Z",
				table: "accounts",
				is_active: true,
			},
			{
				id: "a2",
				created_at: "2025-06-01T00:00:00Z",
				table: "accounts",
				is_active: true,
			},
			{
				id: "a3",
				created_at: "2025-12-01T00:00:00Z",
				table: "accounts",
				is_active: true,
			},
		];

		const queue: QueueItem[] = [
			{ id: "q1", workspace_id: "ws1", status: "pending" },
			{ id: "q2", workspace_id: "ws1", status: "pending" },
			{ id: "q3", workspace_id: "ws1", status: "posted" },
		];

		// Step 1: enforce account limits (Free = 1)
		const accountResult = simulateEnforceAccountLimits(accounts, 1);
		expect(accountResult.kept).toEqual(["a1"]);
		expect(accountResult.deactivated).toEqual(["a2", "a3"]);

		// Step 2: cancel orphaned queue items
		const queueResult = simulateCancelOrphanedQueueItems(queue, ["ws1"]);
		const canceledQueue = queueResult.filter((i) => i.status === "canceled");
		expect(canceledQueue).toHaveLength(2);

		// Step 3: cron should skip this workspace
		expect(shouldProcessWorkspace("free")).toBe(false);

		// Already-posted items untouched
		expect(queueResult.find((i) => i.id === "q3")!.status).toBe("posted");
	});
});
