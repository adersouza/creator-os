/**
 * GDPR Deletion Coverage — Migration Scanner Test
 *
 * Scans all Supabase migrations for tables with user_id/owner_id FK to profiles(id),
 * then asserts every one appears in the account deletion route.
 * This test breaks automatically when a new user-data table is added without
 * updating the deletion logic.
 */

import { readFileSync, readdirSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

// ============================================================================
// Extract tables from migrations
// ============================================================================

const MIGRATIONS_DIR = join(__dirname, "../../supabase/migrations");

function getAllMigrationFiles(): string[] {
	try {
		return readdirSync(MIGRATIONS_DIR)
			.filter((f) => f.endsWith(".sql") && !f.startsWith("_") && !f.startsWith("."))
			.map((f) => join(MIGRATIONS_DIR, f));
	} catch {
		return [];
	}
}


/**
 * Parses migration SQL to find tables with a user_id or owner_id column
 * that REFERENCES profiles(id).
 */
function extractUserDataTables(files: string[]): Set<string> {
	const tables = new Set<string>();
	const createTableRegex =
		/CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?(\w+)\s*\(/gi;

	for (const file of files) {
		const sql = readFileSync(file, "utf-8");
		let match: RegExpExecArray | null;
		// biome-ignore lint/suspicious/noAssignInExpressions: regex iteration
		while ((match = createTableRegex.exec(sql)) !== null) {
			const tableName = match[1];
			// Extract the CREATE TABLE block (until the closing paren + semicolon)
			const startIdx = match.index;
			const blockEnd = sql.indexOf(");", startIdx);
			if (blockEnd === -1) continue;
			const block = sql.slice(startIdx, blockEnd + 2);

			// Check if block has user_id or owner_id referencing profiles
			if (
				/(?:user_id|owner_id)\s+TEXT\s+.*?REFERENCES\s+(?:public\.)?profiles\s*\(\s*id\s*\)/i.test(
					block,
				)
			) {
				tables.add(tableName);
			}
		}
	}
	return tables;
}

// ============================================================================
// Extract tables from delete.ts
// ============================================================================

const DELETE_ROUTE = join(__dirname, "../../api/_lib/handlers/user/delete.ts");
const DELETION_CASCADE = join(__dirname, "../../api/_lib/handlers/user/deletionCascade.ts");
const META_DELETION_PROCESSOR = join(__dirname, "../../api/meta/process-deletion.ts");

function extractDeleteRouteTables(): Set<string> {
	const tables = new Set<string>();
	// Scan both delete.ts (handler) and deletionCascade.ts (shared cascade logic)
	const code = readFileSync(DELETE_ROUTE, "utf-8") + "\n" + readFileSync(DELETION_CASCADE, "utf-8");

	// Match table names in { table: "xxx", key: "..." } patterns
	const objectPattern = /table:\s*"(\w+)"/g;
	let match: RegExpExecArray | null;
	// biome-ignore lint/suspicious/noAssignInExpressions: regex iteration
	while ((match = objectPattern.exec(code)) !== null) {
		tables.add(match[1]);
	}

	// Match table names in string array patterns (ACCOUNT_ID_TABLES etc)
	// These are bare strings like "auto_reply_logs",
	const stringArrayPattern = /^\s*"(\w+)",?\s*$/gm;
	// biome-ignore lint/suspicious/noAssignInExpressions: regex iteration
	while ((match = stringArrayPattern.exec(code)) !== null) {
		tables.add(match[1]);
	}

	// Match safeDelete calls: safeDelete(supabase, "table_name", ...)
	const safeDeletePattern = /safeDelete\(\s*supabase\s*,\s*"(\w+)"/g;
	// biome-ignore lint/suspicious/noAssignInExpressions: regex iteration
	while ((match = safeDeletePattern.exec(code)) !== null) {
		tables.add(match[1]);
	}

	// Match .from("table_name") calls used for lookup queries
	const fromPattern = /\.from\(\s*"(\w+)"\s*\)/g;
	// biome-ignore lint/suspicious/noAssignInExpressions: regex iteration
	while ((match = fromPattern.exec(code)) !== null) {
		tables.add(match[1]);
	}

	return tables;
}

// ============================================================================
// Tables that are legitimately excluded
// ============================================================================

/**
 * Tables that reference profiles(id) but are handled differently:
 * - profiles: deleted as the final step (auth.admin.deleteUser)
 * - data_export_jobs: ephemeral, auto-expires, no PII beyond user_id
 * - cron_runs / cron_locks: system tables, no user PII
 * - stripe_processed_events: idempotency-only (event_id, event_type, timestamps) —
 *     no user_id column, so the migration scanner won't flag it. Kept here for
 *     documentation: confirmed schema has no user PII (verified 2026-03-08).
 */
const LEGITIMATE_EXCLUSIONS = new Set([
	"data_export_jobs",
	"data_deletion_requests",
	"cron_runs",
	"cron_locks",
	"stripe_processed_events",
	// Tables dropped in migration 20260306144605_kill_dead_features_v2.sql
	"ab_tests",
	"watermark_configs",
	"engagement_pods",
	"pod_members",
]);

// ============================================================================
// Tests
// ============================================================================

describe("GDPR Deletion Coverage", () => {
	const migrationFiles = getAllMigrationFiles();
	const userDataTables = extractUserDataTables(migrationFiles);
	const deleteRouteTables = extractDeleteRouteTables();

	it("should find user-data tables in migrations", () => {
		expect(userDataTables.size).toBeGreaterThan(0);
	});

	it("should find tables in delete route", () => {
		expect(deleteRouteTables.size).toBeGreaterThan(0);
	});

	it("every table with user_id/owner_id → profiles(id) must appear in delete.ts", () => {
		const missing: string[] = [];
		for (const table of userDataTables) {
			if (LEGITIMATE_EXCLUSIONS.has(table)) continue;
			if (!deleteRouteTables.has(table)) {
				missing.push(table);
			}
		}

		if (missing.length > 0) {
			throw new Error(
				`GDPR gap: ${missing.length} table(s) with user data are NOT in api/_lib/handlers/user/delete.ts:\n` +
					missing.map((t) => `  - ${t}`).join("\n") +
					"\n\nAdd them to USER_ID_TABLES, PARENT_TABLES, or the Phase 4 cascading logic.",
			);
		}
	});

	it("delete route should handle known critical tables", () => {
		const criticalTables = [
			"profiles",
			"accounts",
			"instagram_accounts",
			"posts",
			"account_groups",
			"listening_alerts",
			"unified_links",
			"workspaces",
			"post_reflections",
			"workspace_invites",
		];
		for (const table of criticalTables) {
			expect(deleteRouteTables.has(table)).toBe(true);
		}
	});

	it("Meta deletion processor derives destructive IDs from stored request row", () => {
		const code = readFileSync(META_DELETION_PROCESSOR, "utf-8");
		expect(code).toContain("data_deletion_requests");
		expect(code).toContain("confirmation_code, user_id, meta_user_id");
		expect(code).toContain("hintedUserId");
		expect(code).toContain("hintedMetaUserId");
		expect(code).toContain("Deletion request identity mismatch");
		expect(code).not.toContain("Missing confirmationCode or userId");
	});
});
