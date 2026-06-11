import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = join(__dirname, "../..");

function readMigration() {
	return readFileSync(
		join(
			repoRoot,
			"supabase/migrations/20260604123000_finalize_autoposter_publish.sql",
		),
		"utf8",
	);
}

function readUniqueIndexMigration() {
	return readFileSync(
		join(
			repoRoot,
			"supabase/migrations/20260604130000_posts_threads_post_id_unique.sql",
		),
		"utf8",
	);
}

describe("finalize_autoposter_publish migration", () => {
	it("atomically verifies publishing ownership before finalizing", () => {
		const sql = readMigration();

		expect(sql).toContain("CREATE OR REPLACE FUNCTION public.finalize_autoposter_publish");
		expect(sql).toContain("FOR UPDATE");
		expect(sql).toContain("v_queue.status <> 'publishing'");
		expect(sql).toContain("v_queue.claim_token IS DISTINCT FROM p_claim_token");
	});

	it("is idempotent for an already recorded Threads post", () => {
		const sql = readMigration();

		expect(sql).toContain("WHERE threads_post_id = p_threads_post_id");
		expect(sql).toContain("AND user_id = v_owner_id");
		expect(sql).toContain("v_queue.status = 'published'");
		expect(sql).toContain("inserted := FALSE");
	});

	it("creates the local post and marks the queue published in the same RPC", () => {
		const sql = readMigration();

		expect(sql).toContain("INSERT INTO public.posts");
		expect(sql).toContain("RETURNING id INTO v_post_id");
		expect(sql).toContain("UPDATE public.auto_post_queue");
		expect(sql).toContain("status = 'published'");
		expect(sql).toContain("claim_token = NULL");
		expect(sql).toContain("PERFORM public.increment_group_posts_today");
		expect(sql).toContain("FROM public.check_and_increment_rate_limit");
	});

	it("adds durable reconciliation fields and statuses", () => {
		const sql = readMigration();

		expect(sql).toContain("external_published_at TIMESTAMPTZ");
		expect(sql).toContain("finalize_error TEXT");
		expect(sql).toContain("'needs_reconciliation'");
		expect(sql).toContain("'external_published_local_finalize_failed'");
	});

	it("can rebuild a missing posts row from reconciliation evidence", () => {
		const sql = readMigration();

		expect(sql).toContain("CREATE OR REPLACE FUNCTION public.reconcile_autoposter_publish");
		expect(sql).toContain("'needs_reconciliation'");
		expect(sql).toContain("v_queue.threads_post_id IS NULL");
		expect(sql).toContain("INSERT INTO public.posts");
		expect(sql).toContain("'auto-poster-reconciled'");
		expect(sql).toContain("v_queue.external_published_at");
		expect(sql).toContain("GRANT EXECUTE ON FUNCTION public.reconcile_autoposter_publish");
	});

	it("enforces one local post per Threads post id at the database layer", () => {
		const sql = readUniqueIndexMigration();

		expect(sql).toContain("CREATE UNIQUE INDEX IF NOT EXISTS posts_threads_post_id_unique");
		expect(sql).toContain("ON public.posts(threads_post_id)");
		expect(sql).toContain("WHERE threads_post_id IS NOT NULL");
	});
});
