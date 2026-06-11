import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = join(__dirname, "../..");

function readMigration() {
	return readFileSync(
		join(
			repoRoot,
			"supabase/migrations/20260605011935_autoposter_publish_attempts_doctor.sql",
		),
		"utf8",
	);
}

describe("publish_attempts migration", () => {
	it("creates the autoposter publish attempt ledger", () => {
		const sql = readMigration();

		expect(sql).toContain("CREATE TABLE IF NOT EXISTS public.publish_attempts");
		expect(sql).toContain("queue_item_id TEXT NOT NULL");
		expect(sql).toContain("claim_token UUID");
		expect(sql).toContain("attempt_number INTEGER NOT NULL");
		expect(sql).toContain("threads_post_id TEXT");
		expect(sql).toContain("metadata JSONB NOT NULL DEFAULT '{}'::jsonb");
	});

	it("tracks terminal publish and reconciliation results", () => {
		const sql = readMigration();

		expect(sql).toContain("'claim_failed'");
		expect(sql).toContain("'published'");
		expect(sql).toContain("'needs_reconciliation'");
		expect(sql).toContain("'reconciled'");
		expect(sql).toContain("'reconcile_failed'");
		expect(sql).toContain("'dead_letter'");
	});

	it("adds forensic indexes and owner-readable RLS", () => {
		const sql = readMigration();

		expect(sql).toContain("idx_publish_attempts_queue_item");
		expect(sql).toContain("idx_publish_attempts_account_started");
		expect(sql).toContain("idx_publish_attempts_threads_post_id");
		expect(sql).toContain("ALTER TABLE IF EXISTS public.publish_attempts ENABLE ROW LEVEL SECURITY");
		expect(sql).toContain("publish_attempts_owner_select");
		expect(sql).toContain("GRANT ALL ON public.publish_attempts TO service_role");
	});
});
