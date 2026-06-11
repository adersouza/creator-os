/**
 * GDPR Export Coverage Tests
 *
 * 1. Migration scanner: every user-data table must be in the export worker
 * 2. Export dispatch: export.ts must return 202 (not inline 200)
 * 3. Export worker: must exist with QStash signature verification
 */

import { existsSync, readFileSync, readdirSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

// ============================================================================
// Helpers
// ============================================================================

const MIGRATIONS_DIR = join(__dirname, "../../supabase/migrations");
const EXPORT_ROUTE = join(__dirname, "../../api/_lib/handlers/user/export.ts");
const EXPORT_WORKER = join(__dirname, "../../api/_lib/handlers/jobs/export-worker.ts");
const EXPORT_STATUS = join(__dirname, "../../api/_lib/handlers/user/export-status.ts");

function getAllMigrationFiles(): string[] {
	try {
		return readdirSync(MIGRATIONS_DIR)
			.filter((f) => f.endsWith(".sql") && !f.startsWith("_") && !f.startsWith("."))
			.map((f) => join(MIGRATIONS_DIR, f));
	} catch {
		return [];
	}
}


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
			const startIdx = match.index;
			const blockEnd = sql.indexOf(");", startIdx);
			if (blockEnd === -1) continue;
			const block = sql.slice(startIdx, blockEnd + 2);

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

function extractExportWorkerTables(): Set<string> {
	const tables = new Set<string>();
	if (!existsSync(EXPORT_WORKER)) return tables;
	const code = readFileSync(EXPORT_WORKER, "utf-8");

	// Match bare string table names in arrays
	const stringPattern = /^\s*"(\w+)",?\s*$/gm;
	let match: RegExpExecArray | null;
	// biome-ignore lint/suspicious/noAssignInExpressions: regex iteration
	while ((match = stringPattern.exec(code)) !== null) {
		tables.add(match[1]);
	}

	// Match .from("table_name") calls
	const fromPattern = /\.from\(\s*"(\w+)"\s*\)/g;
	// biome-ignore lint/suspicious/noAssignInExpressions: regex iteration
	while ((match = fromPattern.exec(code)) !== null) {
		tables.add(match[1]);
	}

	return tables;
}

// Tables excluded from export (system/ephemeral, no user PII)
// - data_export_jobs: ephemeral job tracking, expires after 24h
// - cron_runs / cron_locks: system tables
// - stripe_processed_events: idempotency-only (event_id, event_type, timestamps) —
//     confirmed no user_id column (verified 2026-03-08). Migration scanner won't
//     flag it but kept here for documentation.
const EXPORT_EXCLUSIONS = new Set([
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

describe("GDPR Export Coverage", () => {
	it("export-worker.ts must exist", () => {
		expect(existsSync(EXPORT_WORKER)).toBe(true);
	});

	it("export-status.ts must exist", () => {
		expect(existsSync(EXPORT_STATUS)).toBe(true);
	});

	it("export.ts must dispatch to background (return 202, not inline 200)", () => {
		const code = readFileSync(EXPORT_ROUTE, "utf-8");
		// Must NOT contain inline JSON.stringify + res.send pattern
		expect(code).not.toContain('res.status(200).send(JSON.stringify');
		// Must contain 202 response
		expect(code).toContain("202");
		// Must reference QStash or background dispatch
		expect(code).toMatch(/qstash|QStash|export-worker/i);
	});

	it("export-worker must verify QStash signature", () => {
		const code = readFileSync(EXPORT_WORKER, "utf-8");
		expect(code).toContain("verifyQStashSignature");
	});

	it("export-worker derives user_id from data_export_jobs instead of trusting body userId", () => {
		const code = readFileSync(EXPORT_WORKER, "utf-8");
		expect(code).toContain('.from("data_export_jobs")');
		expect(code).toContain('.select("id, user_id")');
		expect(code).toContain("hintedUserId");
		expect(code).toContain("Ignoring mismatched body userId");
		expect(code).not.toContain("Missing jobId or userId");
	});

	it("every user-data table must be queryable by export-worker", () => {
		const migrationFiles = getAllMigrationFiles();
		const userDataTables = extractUserDataTables(migrationFiles);
		const exportTables = extractExportWorkerTables();

		const missing: string[] = [];
		for (const table of userDataTables) {
			if (EXPORT_EXCLUSIONS.has(table)) continue;
			if (!exportTables.has(table)) {
				missing.push(table);
			}
		}

		if (missing.length > 0) {
			throw new Error(
				`GDPR export gap: ${missing.length} table(s) with user data are NOT in export-worker.ts:\n` +
					missing.map((t) => `  - ${t}`).join("\n") +
					"\n\nAdd them to TABLES_BY_USER_ID or the cascading query section.",
			);
		}
	});
});
