import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const migration = readFileSync(
	join(
		process.cwd(),
		"supabase/migrations/20260605201000_fix_rate_limit_status_rpc.sql",
	),
	"utf8",
);

describe("rate-limit status RPC migration", () => {
	it("uses the current rate_limit_tracking column names", () => {
		expect(migration).toContain("CREATE OR REPLACE FUNCTION public.get_rate_limit_status");
		expect(migration).toContain("v_record.posts_this_hour");
		expect(migration).toContain("v_record.posts_today");
		expect(migration).toContain("v_record.hour_window_start");
		expect(migration).toContain("v_record.day_window_start");
		expect(migration).not.toContain("hourly_count");
		expect(migration).not.toContain("daily_count");
	});
});
