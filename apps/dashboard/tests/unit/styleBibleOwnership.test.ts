/**
 * Tests for the account-ownership guard in POST /api/ai/style-bible.
 *
 * The guard added to the route:
 *   if (effectiveAccountId) {
 *     const { data: ownedAccount } = await supabase
 *       .from("accounts").select("id")
 *       .eq("id", effectiveAccountId).eq("user_id", user.id).maybeSingle();
 *     if (!ownedAccount) return apiError(res, 403, ...);
 *   }
 *
 * We test the predicate logic directly using a mock db client.
 */

import { describe, expect, it } from "vitest";

// ---------------------------------------------------------------------------
// The guard predicate extracted for isolated testing
// ---------------------------------------------------------------------------

async function checkAccountOwnership(
	db: {
		from: (t: string) => {
			select: (c: string) => {
				eq: (c: string, v: string) => {
					eq: (c: string, v: string) => {
						maybeSingle: () => Promise<{ data: { id: string } | null; error: null }>;
					};
				};
			};
		};
	},
	effectiveAccountId: string | null,
	userId: string,
): Promise<"pass" | "deny"> {
	if (!effectiveAccountId) return "pass"; // no accountId → global style bible, skip check
	const { data } = await db
		.from("accounts")
		.select("id")
		.eq("id", effectiveAccountId)
		.eq("user_id", userId)
		.maybeSingle();
	return data !== null ? "pass" : "deny";
}

// ---------------------------------------------------------------------------
// Mock db factory
//
// Returns a row only when the second .eq() value equals `ownerUserId`.
// Simulates: "this account is owned by ownerUserId; nobody else can claim it."
// ---------------------------------------------------------------------------

function buildDb(ownedById: string | null) {
	return {
		from: (_t: string) => ({
			select: (_c: string) => ({
				eq: (_c: string, _v: string) => ({
					eq: (_c2: string, callerUserId: string) => ({
						maybeSingle: async () => ({
							data:
								ownedById && callerUserId === ownedById
									? { id: "acc-123" }
									: null,
							error: null,
						}),
					}),
				}),
			}),
		}),
	};
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("style-bible account ownership guard", () => {
	it("passes when effectiveAccountId is null (global / workspace-level bible)", async () => {
		const db = buildDb(null);
		expect(await checkAccountOwnership(db as any, null, "any-user")).toBe("pass");
	});

	it("passes when the account is owned by the requesting user", async () => {
		const db = buildDb("owner-user");
		expect(await checkAccountOwnership(db as any, "acc-123", "owner-user")).toBe("pass");
	});

	it("denies when accountId belongs to a DIFFERENT user (IDOR attempt)", async () => {
		// db returns null for any userId that is not "owner-user"
		const db = buildDb("owner-user");
		expect(await checkAccountOwnership(db as any, "acc-123", "attacker")).toBe("deny");
	});

	it("denies when accountId does not exist at all", async () => {
		// db always returns null regardless of userId
		const db = buildDb(null);
		expect(await checkAccountOwnership(db as any, "nonexistent-id", "owner-user")).toBe("deny");
	});

	it("passes when effectiveAccountId is empty string (treated as null)", async () => {
		const db = buildDb("owner-user");
		expect(await checkAccountOwnership(db as any, "", "owner-user")).toBe("pass");
	});
});
