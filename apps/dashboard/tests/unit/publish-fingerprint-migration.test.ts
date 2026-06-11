import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = join(__dirname, "../..");

function readMigration() {
	return readFileSync(
		join(
			repoRoot,
			"supabase/migrations/20260605014352_autoposter_publish_fingerprint_guard.sql",
		),
		"utf8",
	);
}

describe("publish fingerprint guard migration", () => {
	it("adds duplicate fingerprint columns to queue and posts", () => {
		const sql = readMigration();

		expect(sql).toContain("ADD COLUMN IF NOT EXISTS normalized_text_hash TEXT");
		expect(sql).toContain("ADD COLUMN IF NOT EXISTS media_fingerprint TEXT");
		expect(sql).toContain("ADD COLUMN IF NOT EXISTS publish_fingerprint TEXT");
		expect(sql).toContain("ADD COLUMN IF NOT EXISTS duplicate_window_hours");
		expect(sql).toContain("ADD COLUMN IF NOT EXISTS duplicate_of_queue_item_id TEXT");
	});

	it("indexes recent duplicate lookup paths", () => {
		const sql = readMigration();

		expect(sql).toContain("idx_auto_post_queue_publish_fingerprint_recent");
		expect(sql).toContain("workspace_id, account_id, platform, normalized_text_hash, media_fingerprint");
		expect(sql).toContain("idx_posts_publish_fingerprint_recent");
	});

	it("adds duplicate result types to the publish attempt ledger", () => {
		const sql = readMigration();

		expect(sql).toContain("'duplicate_fingerprint_blocked'");
		expect(sql).toContain("'duplicate_fingerprint_needs_review'");
	});
});
