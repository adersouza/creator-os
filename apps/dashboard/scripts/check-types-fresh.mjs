#!/usr/bin/env node

/**
 * Fails when the canonical generated Supabase types are older than the latest
 * migration. This catches schema drift before code starts relying on stale
 * table/column metadata.
 */

import { execFileSync } from "child_process";
import { existsSync, readdirSync, statSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const typesPath = resolve(root, "src/types/supabase.ts");
const migrationsDir = resolve(root, "supabase/migrations");

function formatMtime(ms) {
	return new Date(ms).toISOString();
}

function freshnessTime(path) {
	const absolutePath = resolve(root, path);
	try {
		const status = execFileSync("git", ["status", "--porcelain", "--", path], {
			cwd: root,
			encoding: "utf8",
			stdio: ["ignore", "pipe", "ignore"],
		}).trim();
		if (status && existsSync(absolutePath)) return statSync(absolutePath).mtimeMs;

		const timestamp = execFileSync(
			"git",
			["log", "-1", "--format=%ct", "--", path],
			{ cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
		).trim();
		if (timestamp) return Number(timestamp) * 1000;
	} catch {
		// Fall back to filesystem mtimes outside git worktrees.
	}
	return statSync(absolutePath).mtimeMs;
}

function migrationVersionTime(name, path) {
	const version = name.split("_", 1)[0] ?? "";
	const match = version.match(/^(\d{4})(\d{2})(\d{2})(?:(\d{2})(\d{2})(\d{2}))?$/);
	if (!match) return freshnessTime(path);

	const [, year, month, day, hour = "00", minute = "00", second = "00"] = match;
	return Date.UTC(
		Number(year),
		Number(month) - 1,
		Number(day),
		Number(hour),
		Number(minute),
		Number(second),
	);
}

const typesFreshnessTime = freshnessTime(typesPath);
const migrationFiles = readdirSync(migrationsDir, { withFileTypes: true })
	.filter((entry) => entry.isFile() && entry.name.endsWith(".sql"))
	.map((entry) => {
		const path = `supabase/migrations/${entry.name}`;
		return { name: entry.name, path, freshnessMs: migrationVersionTime(entry.name, path) };
	});

if (migrationFiles.length === 0) {
	console.log("No migration files found; generated types freshness check skipped.");
	process.exit(0);
}

const latestMigration = migrationFiles.reduce((latest, file) =>
	file.freshnessMs > latest.freshnessMs ? file : latest,
);

if (latestMigration.freshnessMs > typesFreshnessTime) {
	console.error(
		[
			"Generated Supabase types are older than the latest migration.",
			`  types:     src/types/supabase.ts (${formatMtime(typesFreshnessTime)})`,
			`  migration: ${latestMigration.name} (${formatMtime(latestMigration.freshnessMs)})`,
			"",
			"Regenerate types with `npm run types:db` and commit src/types/supabase.ts.",
		].join("\n"),
	);
	process.exit(1);
}

console.log(
	`Generated Supabase types are fresh (${formatMtime(typesFreshnessTime)} >= ${latestMigration.name}).`,
);
