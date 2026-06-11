import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const sql = readFileSync(
	"supabase/migrations/20260606192006_add_posts_content_surface.sql",
	"utf8",
);

describe("posts content_surface migration", () => {
	it("adds a first-class constrained content_surface column", () => {
		expect(sql).toContain("ADD COLUMN IF NOT EXISTS content_surface TEXT");
		for (const value of ["'reel'", "'story'", "'feed_single'", "'feed_carousel'"]) {
			expect(sql).toContain(value);
		}
	});

	it("backfills content_surface from Campaign metadata and ig_media_type", () => {
		expect(sql).toContain("metadata #>> '{campaign_factory,content_surface}'");
		expect(sql).toContain("metadata #>> '{campaign_factory,handoff_manifest,content_surface}'");
		expect(sql).toContain("WHEN ig_media_type = 'REELS' THEN 'reel'");
		expect(sql).toContain("WHEN ig_media_type = 'STORIES' THEN 'story'");
		expect(sql).toContain("WHEN ig_media_type = 'IMAGE' THEN 'feed_single'");
		expect(sql).toContain("THEN 'feed_carousel'");
	});

	it("adds an operational index for surface-aware post reporting", () => {
		expect(sql).toContain("posts_content_surface_idx");
		expect(sql).toContain("user_id, platform, content_surface, status, scheduled_for");
	});
});
