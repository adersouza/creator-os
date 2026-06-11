/**
 * Tests for canApprovePost — the cross-tenant IDOR guard on post approval.
 *
 * Covers every branch of the authorization logic without a real database.
 * The db client is replaced with a minimal mock so each assertion is deterministic.
 */

import { describe, expect, it } from "vitest";
import { canApprovePost } from "../../api/_lib/postAuthorization.js";

// ---------------------------------------------------------------------------
// Mock db factories
// ---------------------------------------------------------------------------

/**
 * buildDb — used for the no-accountId tests (fail-closed path).
 * These tests don't reach any db calls (the function returns false immediately),
 * so the mock content doesn't matter — it's here for the fast-path ownership test.
 */
function buildDb({
	overlap,
}: {
	ownerWorkspaces?: { workspace_id: string }[];
	overlap: { workspace_id: string } | null;
}) {
	return {
		from: (_table: string) => ({
			select: (_cols: string) => ({
				eq: (_col: string, _val: string) => ({
					in: (_col2: string, _vals: string[]) => ({
						in: (_col3: string, _vals2: string[]) => ({
							limit: (_n: number) => ({
								maybeSingle: () => Promise.resolve({ data: overlap, error: null }),
							}),
						}),
					}),
					maybeSingle: () => Promise.resolve({ data: null, error: null }),
				}),
			}),
		}),
	};
}

/**
 * buildAccountScopedDb — used for tests that pass an accountId.
 *
 * Call chain for the accountId path:
 *   from("accounts")          → { group_id } | null
 *   from("account_groups")    → { workspace_id } | null
 *   from("workspace_members") → overlap check
 */
function buildAccountScopedDb({
	accountGroupId,
	groupWorkspaceId,
	overlap,
}: {
	accountGroupId: string | null;
	groupWorkspaceId: string | null;
	overlap: { workspace_id: string } | null;
}) {
	const singleChain = (value: unknown) => ({
		select: (_cols: string) => ({
			eq: (_col: string, _val: string) => ({
				maybeSingle: () => Promise.resolve({ data: value, error: null }),
			}),
		}),
	});

	const overlapChain = () => ({
		select: (_cols: string) => ({
			eq: (_col: string, _val: string) => ({
				in: (_col2: string, _vals: string[]) => ({
					in: (_col3: string, _vals2: string[]) => ({
						limit: (_n: number) => ({
							maybeSingle: () => Promise.resolve({ data: overlap, error: null }),
						}),
					}),
				}),
			}),
		}),
	});

	return {
		from: (table: string) => {
			if (table === "accounts") return singleChain(accountGroupId ? { group_id: accountGroupId } : null);
			if (table === "instagram_accounts") return singleChain(null);
			if (table === "account_groups") return singleChain(groupWorkspaceId ? { workspace_id: groupWorkspaceId } : null);
			if (table === "workspace_members") return overlapChain();
			throw new Error(`Unexpected table: ${table}`);
		},
	};
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("canApprovePost", () => {
	it("allows when requester owns the post (fast path — no db calls)", async () => {
		const db = buildDb({ ownerWorkspaces: [], overlap: null });
		expect(await canApprovePost(db as any, "user-A", "user-A")).toBe(true);
	});

	it("fails closed when no accountId is provided (cross-workspace IDOR guard)", async () => {
		// Even if the requester would be admin in a shared workspace,
		// omitting accountId must never grant approval.
		const db = buildDb({ overlap: { workspace_id: "workspace-1" } });
		expect(await canApprovePost(db as any, "user-A", "user-B")).toBe(false);
	});

	it("allows when requester is admin in the account's workspace", async () => {
		const db = buildAccountScopedDb({
			accountGroupId: "group-1",
			groupWorkspaceId: "workspace-1",
			overlap: { workspace_id: "workspace-1" },
		});
		expect(await canApprovePost(db as any, "user-A", "user-B", "account-1")).toBe(true);
	});

	it("denies when requester is not admin in the account's workspace (cross-tenant IDOR)", async () => {
		const db = buildAccountScopedDb({
			accountGroupId: "group-1",
			groupWorkspaceId: "workspace-1",
			overlap: null,
		});
		expect(await canApprovePost(db as any, "user-A", "user-B", "account-1")).toBe(false);
	});

	it("fails closed when accountId cannot be resolved to a group", async () => {
		const db = buildAccountScopedDb({
			accountGroupId: null,
			groupWorkspaceId: null,
			overlap: null,
		});
		expect(await canApprovePost(db as any, "user-A", "user-B", "account-orphan")).toBe(false);
	});

	it("denies when owner is in workspaces but no accountId provided", async () => {
		const db = buildDb({ overlap: null });
		expect(await canApprovePost(db as any, "user-A", "user-B")).toBe(false);
	});
});
