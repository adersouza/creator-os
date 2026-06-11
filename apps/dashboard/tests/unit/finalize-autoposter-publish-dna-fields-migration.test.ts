import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const sql = readFileSync(
	resolve(
		process.cwd(),
		"supabase/migrations/20260605191546_finalize_autoposter_publish_dna_fields.sql",
	),
	"utf8",
);

describe("finalize_autoposter_publish DNA field migration", () => {
	it("copies DNA scoring fields from queue rows into posts during finalization", () => {
		expect(sql).toContain("CREATE OR REPLACE FUNCTION public.finalize_autoposter_publish");
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
			expect(sql).toContain(column);
			expect(sql).toContain(`v_queue.${column}`);
		}
	});
});
