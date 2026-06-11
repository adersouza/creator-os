import { describe, expect, it } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import { refuseProductionTarget } from "../../scripts/staging-scale-smoke";

const ROOT = path.resolve(__dirname, "../..");

function read(relativePath: string) {
	return fs.readFileSync(path.join(ROOT, relativePath), "utf8");
}

describe("staging scale smoke", () => {
	it("refuses production-looking targets and allows explicit staging/local targets", () => {
		expect(refuseProductionTarget("https://juno33.com")).toMatch(/production/i);
		expect(refuseProductionTarget("https://production.supabase.co")).toMatch(/production/i);
		expect(refuseProductionTarget("https://abc.supabase.co")).toMatch(/unlabelled/i);
		expect(refuseProductionTarget("https://juno33-staging.supabase.co")).toBeNull();
		expect(refuseProductionTarget("http://localhost:3000")).toBeNull();
	});

	it("allows an explicit Supabase staging branch ref without weakening production checks", () => {
		process.env.JUNO33_STAGING_SUPABASE_REF = "roobkkfvxqdlwlxcvbro";
		try {
			expect(refuseProductionTarget("https://roobkkfvxqdlwlxcvbro.supabase.co")).toBeNull();
			expect(refuseProductionTarget("https://apsrvwxfoomhtswlhczo.supabase.co")).toMatch(/unlabelled/i);
			expect(refuseProductionTarget("https://juno33.com")).toMatch(/production/i);
		} finally {
			delete process.env.JUNO33_STAGING_SUPABASE_REF;
		}
	});

	it("keeps staging seed/smoke opt-in and reuses the scale fixture", () => {
		const script = read("scripts/staging-scale-smoke.ts");
		const packageJson = read("package.json");
		const seedBlock = script.slice(script.indexOf('process.env[SEED_FLAG] === "1"'));

		expect(script).toContain("JUNO33_STAGING_SMOKE");
		expect(script).toContain("JUNO33_STAGING_SEED");
		expect(script).toContain("STAGING_SUPABASE_URL");
		expect(script).toContain("STAGING_SUPABASE_SERVICE_ROLE_KEY");
		expect(seedBlock).toContain('required("STAGING_SUPABASE_SERVICE_ROLE_KEY")');
		expect(script).toContain("JUNO33_STAGING_APP_URL");
		expect(script).toContain("createScaleFixture");
		expect(script).toContain("/api/operator?action=snapshot");
		expect(script).toContain("/api/reliability?action=slo-summary");
		expect(script).toContain("/calendar?view=portfolio");
		expect(script).toContain("/approval-queue?status=pending");
		expect(script).toContain("/reliability");
		expect(packageJson).toContain("smoke:staging-scale");
	});
});
