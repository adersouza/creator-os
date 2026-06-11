import { createClient } from "@supabase/supabase-js";
import dotenv from "dotenv";
import { createScaleFixture } from "../e2e/helpers/scaleFixtures";

dotenv.config({ path: ".env" });
dotenv.config({ path: ".env.local" });

const REQUIRED_FLAG = "JUNO33_STAGING_SMOKE";
const SEED_FLAG = "JUNO33_STAGING_SEED";

export function refuseProductionTarget(url: string | undefined | null): string | null {
	const value = String(url || "").trim().toLowerCase();
	if (!value) return "Missing staging Supabase URL";
	if (value.includes("juno33.com")) return "Refusing production app domain";
	if (value.includes("127.0.0.1") || value.includes("localhost")) return null;
	const allowedSupabaseRef = String(process.env.JUNO33_STAGING_SUPABASE_REF || "").trim().toLowerCase();
	if (allowedSupabaseRef && value === `https://${allowedSupabaseRef}.supabase.co`) return null;
	if (/(prod|production)/.test(value)) return "Refusing URL that looks like production";
	if (/(staging|stage|preview|dev|test|local)/.test(value)) return null;
	return "Refusing unlabelled Supabase target; use a staging/dev/test project URL";
}

function required(name: string): string {
	const value = process.env[name];
	if (!value) throw new Error(`${name} is required for staging scale smoke`);
	return value;
}

async function main() {
	if (process.env[REQUIRED_FLAG] !== "1") {
		throw new Error(`${REQUIRED_FLAG}=1 is required. This script is opt-in and must never run against production.`);
	}

	const supabaseUrl = required("STAGING_SUPABASE_URL");
	const appUrl = required("JUNO33_STAGING_APP_URL").replace(/\/$/, "");
	const refusal = refuseProductionTarget(supabaseUrl) ?? refuseProductionTarget(appUrl);
	if (refusal) throw new Error(refusal);

	const fixture = createScaleFixture();
	console.log(`[staging-scale-smoke] Fixture: ${fixture.accounts.length} accounts, ${fixture.groups.length} groups.`);

	if (process.env[SEED_FLAG] === "1") {
		const serviceRoleKey = required("STAGING_SUPABASE_SERVICE_ROLE_KEY");
		const supabase = createClient(supabaseUrl, serviceRoleKey, {
			auth: { persistSession: false, autoRefreshToken: false },
		});
		await guardedSeedFixture(supabase, fixture);
		console.log("[staging-scale-smoke] Seeded staging fixture rows.");
	} else {
		console.log(`[staging-scale-smoke] Dry-run seed only. Set ${SEED_FLAG}=1 to write staging fixture rows.`);
	}

	const endpoints = [
		"/api/operator?action=snapshot",
		"/api/reliability?action=slo-summary",
		"/approval-queue?status=pending",
		"/calendar?view=portfolio",
		"/inbox",
		"/reports",
		"/reliability",
		"/dashboard",
	];
	for (const endpoint of endpoints) {
		const response = await fetch(`${appUrl}${endpoint}`, {
			headers: endpoint.startsWith("/api/") ? { Accept: "application/json" } : {},
		});
		if (response.status >= 500) {
			throw new Error(`Smoke failed for ${endpoint}: HTTP ${response.status}`);
		}
		console.log(`[staging-scale-smoke] ${endpoint} -> ${response.status}`);
	}
}

async function guardedSeedFixture(
	supabase: ReturnType<typeof createClient>,
	fixture: ReturnType<typeof createScaleFixture>,
) {
	const baseRows = [
		{ table: "account_groups", rows: fixture.groups.map(({ account_ids, ...group }) => ({ ...group, user_id: fixture.user.id })) },
		{ table: "accounts", rows: fixture.threadsAccounts.map(({ platform, ...account }) => account) },
		{ table: "instagram_accounts", rows: fixture.instagramAccounts.map(({ platform, ...account }) => account) },
		{ table: "posts", rows: fixture.posts },
	];

	for (const batch of baseRows) {
		const { error } = await supabase.from(batch.table).upsert(batch.rows, { onConflict: "id" });
		if (error) throw new Error(`Failed seeding ${batch.table}: ${error.message}`);
	}
}

if (import.meta.url === `file://${process.argv[1]}`) {
	main().catch((error) => {
		console.error(error instanceof Error ? error.message : error);
		process.exit(1);
	});
}
