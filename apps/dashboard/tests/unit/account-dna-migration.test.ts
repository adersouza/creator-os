import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const migration = readFileSync(
	join(
		process.cwd(),
		"supabase/migrations/20260605071126_autoposter_account_dna.sql",
	),
	"utf8",
);

describe("autoposter account DNA migration", () => {
	it("creates the durable account DNA tables", () => {
		for (const table of [
			"public.account_dna",
			"public.account_dna_examples",
			"public.account_dna_rules",
			"public.account_uniqueness_metrics",
		]) {
			expect(migration).toContain(`CREATE TABLE IF NOT EXISTS ${table}`);
		}
	});

	it("adds DNA score fields to generated candidates and posts", () => {
		for (const table of ["public.auto_post_queue", "public.posts"]) {
			expect(migration).toContain(`ALTER TABLE IF EXISTS ${table}`);
		}

		for (const column of [
			"dna_id",
			"dna_version",
			"dna_fit_score",
			"voice_fit_score",
			"topic_fit_score",
			"mood_fit_score",
			"uniqueness_score",
			"sibling_collision_score",
			"genericness_score",
			"dna_decision",
			"dna_reasons",
		]) {
			expect(migration).toContain(column);
		}
	});

	it("keeps one active DNA profile per account and constrains decisions", () => {
		expect(migration).toContain("account_dna_one_active_per_account");
		expect(migration).toContain("status = 'active'");
		expect(migration).toContain("auto_post_queue_dna_decision_check");
		expect(migration).toContain("posts_dna_decision_check");
		expect(migration).toContain("'pass_unscored'");
		expect(migration).toContain("'regenerate'");
		expect(migration).toContain("'needs_review'");
		expect(migration).toContain("'block'");
	});
});
