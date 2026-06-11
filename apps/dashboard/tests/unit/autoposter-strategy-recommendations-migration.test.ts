import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const migration = readFileSync(
	join(
		process.cwd(),
		"supabase/migrations/20260605073000_autoposter_strategy_recommendations.sql",
	),
	"utf8",
);

describe("autoposter strategy recommendations migration", () => {
	it("creates durable strategy recommendation storage", () => {
		expect(migration).toContain(
			"CREATE TABLE IF NOT EXISTS public.autoposter_strategy_recommendations",
		);
		for (const column of [
			"workspace_id",
			"group_id",
			"account_id",
			"pattern_type",
			"pattern_value",
			"recommendation",
			"confidence",
			"reason",
			"metric_basis",
			"expires_at",
		]) {
			expect(migration).toContain(column);
		}
	});

	it("constrains actions, confidence, and active lookup scope", () => {
		expect(migration).toContain(
			"CHECK (recommendation IN ('increase', 'decrease', 'test', 'avoid'))",
		);
		expect(migration).toContain("CHECK (confidence >= 0 AND confidence <= 1)");
		expect(migration).toContain("idx_autoposter_strategy_active_scope");
		expect(migration).toContain("autoposter_strategy_recommendations_unique");
	});

	it("enables RLS while allowing service role management", () => {
		expect(migration).toContain(
			"ALTER TABLE public.autoposter_strategy_recommendations ENABLE ROW LEVEL SECURITY",
		);
		expect(migration).toContain("TO service_role");
		expect(migration).toContain("workspace_members");
	});
});
