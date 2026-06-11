import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("creator DNA migration", () => {
	it("adds creator DNA, account flavor, compatibility mapping, and shape usage", () => {
		const migration = readFileSync(
			"supabase/migrations/20260605213000_autoposter_creator_dna_v1.sql",
			"utf8",
		);

		expect(migration).toContain("public.creator_dna");
		expect(migration).toContain("public.account_flavor");
		expect(migration).toContain("public.creator_identity_shape_usage");
		expect(migration).toContain("creator_dna_id");
		expect(migration).toContain("account_flavor_id");
		expect(migration).toContain("creator_dna_one_active_per_group");
		expect(migration).toContain("account_flavor_one_active_per_account");
		expect(migration).toContain("shape_id");
		expect(migration).toContain("ENABLE ROW LEVEL SECURITY");
	});
});
