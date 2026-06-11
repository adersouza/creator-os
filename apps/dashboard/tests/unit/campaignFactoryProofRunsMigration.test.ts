import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = join(__dirname, "../..");

function readMigration() {
	return readFileSync(
		join(
			repoRoot,
			"supabase/migrations/20260604211000_campaign_factory_proof_runs_quarantine.sql",
		),
		"utf8",
	);
}

describe("Campaign Factory proof run migration", () => {
	it("creates durable proof run and quarantine tables", () => {
		const sql = readMigration();

		expect(sql).toContain("CREATE TABLE IF NOT EXISTS public.proof_runs");
		expect(sql).toContain("CREATE TABLE IF NOT EXISTS public.quarantined_assets");
		expect(sql).toContain("user_id TEXT NOT NULL REFERENCES public.profiles(id)");
		expect(sql).toContain("metrics_eligible BOOLEAN NOT NULL DEFAULT FALSE");
		expect(sql).toContain("excluded_from_metrics BOOLEAN NOT NULL DEFAULT TRUE");
		expect(sql).toContain("UNIQUE(user_id, asset_id)");
	});

	it("captures the proof lifecycle states and enables RLS", () => {
		const sql = readMigration();

		for (const status of [
			"publishable_candidate",
			"exported",
			"platform_draft_validated",
			"published",
			"metrics_eligible",
			"failed",
			"quarantined",
			"retired",
		]) {
			expect(sql).toContain(`'${status}'`);
		}
		expect(sql).toContain("ALTER TABLE IF EXISTS public.proof_runs ENABLE ROW LEVEL SECURITY");
		expect(sql).toContain(
			"ALTER TABLE IF EXISTS public.quarantined_assets ENABLE ROW LEVEL SECURITY",
		);
		expect(sql).toContain("GRANT ALL ON public.proof_runs TO service_role");
		expect(sql).toContain("GRANT ALL ON public.quarantined_assets TO service_role");
	});
});
