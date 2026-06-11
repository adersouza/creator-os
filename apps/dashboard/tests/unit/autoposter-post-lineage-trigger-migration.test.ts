import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const migration = readFileSync(
	join(
		process.cwd(),
		"supabase/migrations/20260605202000_autoposter_post_lineage_trigger.sql",
	),
	"utf8",
);

describe("autoposter post lineage trigger migration", () => {
	it("copies queue lineage from metadata autoPostQueueId", () => {
		expect(migration).toContain("copy_autoposter_post_lineage_fields");
		expect(migration).toContain("NEW.metadata->>'autoPostQueueId'");
		expect(migration).toContain("NEW.auto_post_queue_id");
		expect(migration).toContain("NEW.dna_fit_score");
		expect(migration).toContain("NEW.hook_type");
		expect(migration).toContain("NEW.strategy_bucket");
		expect(migration).toContain("NEW.active_arc_id");
		expect(migration).toContain("UPDATE public.posts p");
	});
});
