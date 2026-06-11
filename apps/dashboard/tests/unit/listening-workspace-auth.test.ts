import { describe, expect, it, vi, beforeEach } from "vitest";

/**
 * Tests that the listening alerts endpoint validates workspace
 * membership before allowing a user to create alerts in a workspace.
 *
 * Without this check, User A can inject alerts into User B's workspace
 * by sending { workspace_id: "<victim-workspace>" } in the POST body.
 */

let mockWorkspaceMember: { role: string } | null = null;
let mockWorkspaceOwner: { owner_id: string } | null = null;

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabase: () => ({
		from: (table: string) => {
			if (table === "workspace_members") {
				return {
					select: () => ({
						eq: () => ({
							eq: () => ({
								maybeSingle: () =>
									Promise.resolve({ data: mockWorkspaceMember }),
							}),
						}),
					}),
				};
			}
			if (table === "workspaces") {
				return {
					select: () => ({
						eq: () => ({
							maybeSingle: () =>
								Promise.resolve({ data: mockWorkspaceOwner }),
						}),
					}),
				};
			}
			return {
				select: () => ({ eq: () => ({ maybeSingle: () => Promise.resolve({ data: null }) }) }),
			};
		},
	}),
}));

const { verifyWorkspaceAccess } = await import(
	"../../api/_lib/workspaceAccess.js"
);

describe("workspace access for listening alerts", () => {
	beforeEach(() => {
		mockWorkspaceMember = null;
		mockWorkspaceOwner = null;
	});

	it("denies access when user is not a workspace member or owner", async () => {
		mockWorkspaceMember = null;
		mockWorkspaceOwner = { owner_id: "other-user" };

		const { getSupabase } = await import("../../api/_lib/supabase.js");
		const allowed = await verifyWorkspaceAccess(
			getSupabase(),
			"attacker-user",
			"victim-workspace",
		);
		expect(allowed).toBe(false);
	});

	it("allows access when user is workspace member", async () => {
		mockWorkspaceMember = { role: "member" };

		const { getSupabase } = await import("../../api/_lib/supabase.js");
		const allowed = await verifyWorkspaceAccess(
			getSupabase(),
			"member-user",
			"my-workspace",
		);
		expect(allowed).toBe(true);
	});

	it("allows access when user is workspace owner", async () => {
		mockWorkspaceMember = null;
		mockWorkspaceOwner = { owner_id: "owner-user" };

		const { getSupabase } = await import("../../api/_lib/supabase.js");
		const allowed = await verifyWorkspaceAccess(
			getSupabase(),
			"owner-user",
			"my-workspace",
		);
		expect(allowed).toBe(true);
	});

	it("denies access when workspace does not exist", async () => {
		mockWorkspaceMember = null;
		mockWorkspaceOwner = null;

		const { getSupabase } = await import("../../api/_lib/supabase.js");
		const allowed = await verifyWorkspaceAccess(
			getSupabase(),
			"any-user",
			"nonexistent-workspace",
		);
		expect(allowed).toBe(false);
	});
});
