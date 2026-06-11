import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const migration = readFileSync(
	join(
		process.cwd(),
		"supabase/migrations/20260605074500_autoposter_strategy_outcome_tracking.sql",
	),
	"utf8",
);

describe("autoposter strategy outcome tracking migration", () => {
	it("adds recommendation id and bucket to queue and posts", () => {
		expect(migration).toContain("strategy_recommendation_id UUID");
		expect(migration).toContain("strategy_bucket TEXT");
		expect(migration).toContain("public.auto_post_queue");
		expect(migration).toContain("public.posts");
	});

	it("constrains strategy buckets", () => {
		expect(migration).toContain(
			"CHECK (strategy_bucket IN ('proven', 'exploration', 'weird', 'none'))",
		);
	});

	it("tracks recommendation outcome health", () => {
		for (const column of [
			"outcome_sample_count",
			"below_baseline_count",
			"last_outcome_checked_at",
			"downgraded_at",
			"expired_early_at",
		]) {
			expect(migration).toContain(column);
		}
	});

	it("copies queue strategy fields into posts through a trigger", () => {
		expect(migration).toContain(
			"CREATE OR REPLACE FUNCTION public.copy_autoposter_strategy_outcome_fields",
		);
		expect(migration).toContain(
			"trg_posts_copy_autoposter_strategy_outcome_fields",
		);
		expect(migration).toContain("NEW.strategy_recommendation_id");
	});
});
