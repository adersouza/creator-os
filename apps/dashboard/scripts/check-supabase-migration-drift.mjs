#!/usr/bin/env node
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const MIGRATIONS_DIR = join(ROOT, "supabase", "migrations");

const args = process.argv.slice(2);
const remotePath =
	args.find((arg) => arg.startsWith("--remote-history="))?.split("=", 2)[1] ??
	process.env.SUPABASE_MIGRATION_HISTORY;

function fail(message, details = []) {
	console.error(`ERROR: ${message}`);
	for (const detail of details) console.error(`  ${detail}`);
	process.exit(1);
}

function warn(message, details = []) {
	console.warn(`WARN: ${message}`);
	for (const detail of details) console.warn(`  ${detail}`);
}

if (!existsSync(MIGRATIONS_DIR)) {
	fail(`migration directory not found: ${MIGRATIONS_DIR}`);
}

const local = readdirSync(MIGRATIONS_DIR)
	.filter((file) => file.endsWith(".sql"))
	.sort()
	.map((file) => {
		const match = /^(\d+)_([^.]+)\.sql$/.exec(file);
		if (!match) {
			fail("migration filename does not match <version>_<name>.sql", [file]);
		}
		return { file, version: match[1], name: match[2] };
	});

const byVersion = new Map();
for (const migration of local) {
	const existing = byVersion.get(migration.version) ?? [];
	existing.push(migration.file);
	byVersion.set(migration.version, existing);
}

const duplicateVersions = [...byVersion.entries()]
	.filter(([, files]) => files.length > 1)
	.map(([version, files]) => `${version}: ${files.join(", ")}`);

if (duplicateVersions.length > 0) {
	fail("duplicate local Supabase migration versions found", duplicateVersions);
}

console.log(`ok: ${local.length} local migration files have unique versions`);

if (!remotePath) {
	console.log(
		"info: set SUPABASE_MIGRATION_HISTORY or pass --remote-history=path/to/history.json to compare against a remote project",
	);
	process.exit(0);
}

if (!existsSync(remotePath)) {
	fail(`remote migration history file not found: ${remotePath}`);
}

let remote;
try {
	remote = JSON.parse(readFileSync(remotePath, "utf8"));
} catch (error) {
	fail(`could not parse remote migration history JSON: ${error.message}`);
}

if (!Array.isArray(remote)) {
	fail("remote migration history JSON must be an array of { version, name } objects");
}

const normalizedRemote = remote.map((migration, index) => {
	if (!migration || typeof migration.version !== "string") {
		fail("remote migration has no string version", [`index ${index}`]);
	}
	return {
		version: migration.version,
		name: typeof migration.name === "string" ? migration.name : "",
	};
});

const localByVersion = new Map(local.map((migration) => [migration.version, migration]));
const remoteByVersion = new Map(
	normalizedRemote.map((migration) => [migration.version, migration]),
);

const duplicateRemoteVersions = normalizedRemote
	.map((migration) => migration.version)
	.filter((version, index, versions) => versions.indexOf(version) !== index);

if (duplicateRemoteVersions.length > 0) {
	fail("duplicate remote Supabase migration versions found", [
		...new Set(duplicateRemoteVersions),
	]);
}

const remoteOnly = normalizedRemote.filter(
	(migration) => !localByVersion.has(migration.version),
);
const localOnly = local.filter((migration) => !remoteByVersion.has(migration.version));
const maxRemoteVersion = normalizedRemote
	.map((migration) => migration.version)
	.sort()
	.at(-1);
const localHistoryGaps = maxRemoteVersion
	? localOnly.filter((migration) => migration.version <= maxRemoteVersion)
	: [];
const pendingLocal = maxRemoteVersion
	? localOnly.filter((migration) => migration.version > maxRemoteVersion)
	: localOnly;
const nameMismatches = normalizedRemote
	.map((remoteMigration) => {
		const localMigration = localByVersion.get(remoteMigration.version);
		if (!localMigration || localMigration.name === remoteMigration.name) return null;
		return `${remoteMigration.version}: local ${basename(localMigration.file)} vs remote ${remoteMigration.name}`;
	})
	.filter(Boolean);

if (remoteOnly.length > 0 || nameMismatches.length > 0 || localHistoryGaps.length > 0) {
	const details = [
		...remoteOnly
			.slice(0, 20)
			.map((migration) => `${migration.version}_${migration.name}`),
		...(remoteOnly.length > 20 ? [`...${remoteOnly.length - 20} more remote-only migrations`] : []),
		...nameMismatches.slice(0, 20),
		...(nameMismatches.length > 20
			? [`...${nameMismatches.length - 20} more name mismatches`]
			: []),
		...localHistoryGaps
			.slice(0, 20)
			.map((migration) => `${basename(migration.file)} missing from remote history before/at ${maxRemoteVersion}`),
		...(localHistoryGaps.length > 20
			? [`...${localHistoryGaps.length - 20} more local history gaps`]
			: []),
	];
	fail("local migrations do not match remote migration history", details);
}

if (pendingLocal.length > 0) {
	warn(
		"local migrations are not present in remote history; this is expected only for pending migrations",
		[
			...pendingLocal.slice(0, 20).map((migration) => basename(migration.file)),
			...(pendingLocal.length > 20 ? [`...${pendingLocal.length - 20} more local-only migrations`] : []),
		],
	);
}

console.log(
	`ok: remote history matches local versions for ${normalizedRemote.length} remote migrations`,
);
