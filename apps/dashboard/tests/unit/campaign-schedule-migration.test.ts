import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const sql = readFileSync(
	"supabase/migrations/20260605061213_campaign_aware_scheduling_manager_v1.sql",
	"utf8",
);

describe("campaign-aware scheduling migration", () => {
	it("adds first-class Campaign Factory and QStash columns to posts", () => {
		for (const column of [
			"campaign_factory_asset_id",
			"campaign_factory_distribution_plan_id",
			"campaign_factory_post_key",
			"campaign_factory_content_fingerprint",
			"campaign_factory_caption_hash",
			"qstash_message_id",
			"qstash_dispatched_at",
			"qstash_dispatch_status",
			"qstash_failure_reason",
			"platform_draft_validated",
		]) {
			expect(sql).toContain(column);
		}
	});

	it("enforces active Campaign duplicate prevention", () => {
		expect(sql).toContain("posts_campaign_distribution_plan_active_uniq");
		expect(sql).toContain("user_id, campaign_factory_distribution_plan_id");
		expect(sql).toContain("posts_campaign_asset_account_time_active_uniq");
		expect(sql).toContain("user_id, instagram_account_id, campaign_factory_asset_id, scheduled_for");
		expect(sql).toContain("status IN ('draft', 'scheduled', 'publishing', 'published')");
	});

	it("creates owner-scoped schedule batch tables", () => {
		expect(sql).toContain("CREATE TABLE IF NOT EXISTS public.campaign_schedule_batches");
		expect(sql).toContain("CREATE TABLE IF NOT EXISTS public.campaign_schedule_batch_items");
		expect(sql).toContain("ALTER TABLE IF EXISTS public.campaign_schedule_batches ENABLE ROW LEVEL SECURITY");
		expect(sql).toContain("ALTER TABLE IF EXISTS public.campaign_schedule_batch_items ENABLE ROW LEVEL SECURITY");
		expect(sql).toContain("GRANT ALL ON public.campaign_schedule_batches TO service_role");
	});

	it("adds nullable Campaign variant lineage columns and backfills from metadata", () => {
		for (const column of [
			"campaign_factory_concept_id",
			"campaign_factory_variant_family_id",
			"campaign_factory_variant_id",
			"campaign_factory_parent_asset_id",
		]) {
			expect(sql).toContain(column);
		}
		expect(sql).toContain("idx_posts_campaign_variant_family_account");
		expect(sql).toContain("metadata->'campaign_factory'->>'variant_family_id'");
		expect(sql).toContain("metadata->'campaign_factory'->>'variant_id'");
	});
});
