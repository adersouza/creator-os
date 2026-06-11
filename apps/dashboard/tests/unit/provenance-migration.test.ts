import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = join(__dirname, "../..");

function readMigration() {
	return readFileSync(
		join(
			repoRoot,
			"supabase/migrations/20260605022829_autoposter_required_queue_provenance.sql",
		),
		"utf8",
	);
}

describe("required queue provenance migration", () => {
	it("adds provenance fields to queue and posts", () => {
		const sql = readMigration();

		expect(sql).toContain("ADD COLUMN IF NOT EXISTS content_fingerprint TEXT");
		expect(sql).toContain("ADD COLUMN IF NOT EXISTS generation_id TEXT");
		expect(sql).toContain("ADD COLUMN IF NOT EXISTS source_id TEXT");
		expect(sql).toContain("ADD COLUMN IF NOT EXISTS provenance_status TEXT");
		expect(sql).toContain("ADD COLUMN IF NOT EXISTS provenance_error TEXT");
	});

	it("adds doctor-friendly missing provenance indexes", () => {
		const sql = readMigration();

		expect(sql).toContain("idx_auto_post_queue_provenance_status");
		expect(sql).toContain("idx_auto_post_queue_missing_provenance");
		expect(sql).toContain("idx_posts_provenance_status");
	});

	it("adds provenance result types to publish attempts", () => {
		const sql = readMigration();

		expect(sql).toContain("'provenance_missing_blocked'");
		expect(sql).toContain("'provenance_missing_needs_review'");
		expect(sql).toContain("'provenance_manual_allowed'");
	});
});
