import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const sql = readFileSync(
	"supabase/migrations/20260605052726_autoposter_account_health_scoring.sql",
	"utf8",
);

describe("autoposter account health migration", () => {
	it("adds cached health fields to account_autoposter_state", () => {
		expect(sql).toContain("account_health_score");
		expect(sql).toContain("account_health_reason");
		expect(sql).toContain("last_health_recomputed_at");
		expect(sql).toContain("idx_aas_group_health_score");
	});
});
