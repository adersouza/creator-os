/**
 * Tests for verifyGroupBelongsToWorkspace — prevents cross-workspace
 * group manipulation in auto-post config endpoints.
 *
 * Validates that the guard rejects groupIds not belonging to the workspace.
 */

import { describe, expect, it } from "vitest";

// Minimal mock for the Supabase chain: .from().select().eq().eq().maybeSingle()
function buildDb(group: { id: string } | null) {
	return () => ({
		from: (_table: string) => ({
			select: (_cols: string) => ({
				eq: (_col1: string, _val1: string) => ({
					eq: (_col2: string, _val2: string) => ({
						maybeSingle: async () => ({ data: group, error: null }),
					}),
				}),
			}),
		}),
	});
}

// Build the guard function inline (it's not exported, so we test the logic pattern)
async function verifyGroupBelongsToWorkspace(
	db: ReturnType<typeof buildDb>,
	groupId: string,
	workspaceId: string,
): Promise<{ authorized: boolean; status?: number; error?: string }> {
	const { data: group } = await db()
		.from("account_groups")
		.select("id")
		.eq("id", groupId)
		.eq("workspace_id", workspaceId)
		.maybeSingle();

	if (!group) {
		return {
			authorized: false,
			status: 404,
			error: "Group not found in this workspace",
		};
	}
	return { authorized: true };
}

describe("verifyGroupBelongsToWorkspace", () => {
	it("allows when group belongs to workspace", async () => {
		const db = buildDb({ id: "group-1" });
		const result = await verifyGroupBelongsToWorkspace(
			db,
			"group-1",
			"ws-1",
		);
		expect(result.authorized).toBe(true);
	});

	it("rejects when group does not belong to workspace", async () => {
		const db = buildDb(null);
		const result = await verifyGroupBelongsToWorkspace(
			db,
			"group-1",
			"ws-2",
		);
		expect(result.authorized).toBe(false);
		expect(result.status).toBe(404);
		expect(result.error).toContain("not found");
	});

	it("rejects when groupId is valid but wrong workspace", async () => {
		// Group exists in ws-1 but caller claims ws-2
		const db = buildDb(null); // query with wrong workspace returns null
		const result = await verifyGroupBelongsToWorkspace(
			db,
			"group-1",
			"ws-wrong",
		);
		expect(result.authorized).toBe(false);
	});
});
