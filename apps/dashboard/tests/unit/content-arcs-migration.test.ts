import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const migration = readFileSync(
	join(
		process.cwd(),
		"supabase/migrations/20260605200000_autoposter_content_arcs_v1.sql",
	),
	"utf8",
);

describe("autoposter content arcs migration", () => {
	it("creates durable arc and beat tables", () => {
		expect(migration).toContain(
			"CREATE TABLE IF NOT EXISTS public.account_content_arcs",
		);
		expect(migration).toContain("CREATE TABLE IF NOT EXISTS public.arc_beats");
		expect(migration).toContain("current_beat_index");
		expect(migration).toContain("next_suggested_beat");
		expect(migration).toContain("cooldown_until");
		expect(migration).toContain("payoff_status");
	});

	it("adds active arc lineage to queue rows and canonical posts", () => {
		for (const table of ["public.auto_post_queue", "public.posts"]) {
			expect(migration).toContain(`ALTER TABLE IF EXISTS ${table}`);
		}
		expect(migration).toContain("ADD COLUMN IF NOT EXISTS active_arc_id UUID");
		expect(migration).toContain("ADD COLUMN IF NOT EXISTS arc_beat_id UUID");
	});

	it("copies arc lineage during autoposter finalization", () => {
		expect(migration).toContain(
			"CREATE OR REPLACE FUNCTION public.finalize_autoposter_publish",
		);
		expect(migration).toContain("v_queue.active_arc_id");
		expect(migration).toContain("v_queue.arc_beat_id");
		expect(migration).toContain("auto_post_queue_id");
	});
});
