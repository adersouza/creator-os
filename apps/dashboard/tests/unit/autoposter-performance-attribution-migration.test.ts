import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const migration = readFileSync(
	join(
		process.cwd(),
		"supabase/migrations/20260605070000_autoposter_own_pattern_attribution.sql",
	),
	"utf8",
);

describe("autoposter own performance attribution migration", () => {
	it("adds durable pattern attribution columns to queue and posts", () => {
		for (const table of ["public.auto_post_queue", "public.posts"]) {
			expect(migration).toContain(`ALTER TABLE ${table}`);
		}

		for (const column of [
			"hook_type",
			"topic_label",
			"format_type",
			"emotional_frame",
			"reply_mechanism",
			"content_length_bucket",
			"media_style",
			"posting_hour",
			"prompt_version",
			"template_id",
			"model_provider",
			"source_pattern_id",
		]) {
			expect(migration).toContain(column);
		}
	});

	it("backfills existing rows and keeps posting_hour bounded", () => {
		expect(migration).toContain("auto_post_queue_posting_hour_check");
		expect(migration).toContain("posts_posting_hour_check");
		expect(migration).toContain("EXTRACT(HOUR FROM");
		expect(migration).not.toContain("competitor impressions");
	});

	it("copies queue attribution into posts during finalization and reconciliation", () => {
		expect(migration).toContain(
			"CREATE OR REPLACE FUNCTION public.finalize_autoposter_publish",
		);
		expect(migration).toContain(
			"CREATE OR REPLACE FUNCTION public.reconcile_autoposter_publish",
		);
		expect(migration).toContain("v_queue.hook_type");
		expect(migration).toContain("v_queue.prompt_version");
		expect(migration).toContain("COALESCE(v_queue.source_pattern_id, v_queue.source_id)");
		expect(migration).toContain("auto_post_queue_id");
	});
});
