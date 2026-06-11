import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const migration = readFileSync(
	join(
		process.cwd(),
		"supabase/migrations/20260605055149_competitor_corpus_metric_quality.sql",
	),
	"utf8",
);

const followupMigration = readFileSync(
	join(
		process.cwd(),
		"supabase/migrations/20260605061550_competitor_pattern_truth_followup.sql",
	),
	"utf8",
);

describe("competitor corpus metric quality migration", () => {
	it("adds metric quality/source and pattern classification fields", () => {
		for (const column of [
			"metric_source",
			"metric_quality",
			"hook_type",
			"topic_label",
			"emotional_frame",
			"cta_style",
			"content_length_bucket",
			"controversy_level",
			"reply_mechanism",
			"account_size_bucket",
			"benchmark_classified_at",
		]) {
			expect(migration).toContain(column);
		}

		expect(migration).toContain("'stats_unavailable'");
		expect(migration).toContain("'partial_engagement'");
		expect(migration).toContain("'valid_engagement'");
	});

	it("creates append-only competitor post metric snapshots", () => {
		expect(migration).toContain(
			"CREATE TABLE IF NOT EXISTS public.competitor_post_metric_snapshots",
		);
		expect(migration).toContain("follower_count_at_scrape");
		expect(migration).toContain("raw_metrics JSONB");
		expect(migration).toContain("ENABLE ROW LEVEL SECURITY");
	});

	it("adds metric truth follow-up fields without building fake impression benchmarks", () => {
		for (const column of [
			"last_metric_checked_at",
			"format_type",
			"media_style",
			"posting_hour",
		]) {
			expect(followupMigration).toContain(column);
		}

		expect(followupMigration).toContain("'scraper_estimated'");
		expect(followupMigration).toContain(
			"official_threads_competitor_stats_unavailable",
		);
		expect(followupMigration).toContain(
			"scraper_estimated_engagement_without_views",
		);
		expect(followupMigration).not.toContain("competitor impressions");
	});
});
