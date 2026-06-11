#!/usr/bin/env node

/**
 * Static replay-safety lint for Supabase migrations.
 *
 * By default this checks changed migration files only. Pass explicit file paths,
 * --all, or --base=<git-ref> to control the scan target.
 */

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const MIGRATIONS_DIR = join(ROOT, "supabase", "migrations");

const CATEGORY_HELP = {
	"alter-table":
		"Use ALTER TABLE IF EXISTS or wrap the statement in a to_regclass()/catalog guard.",
	"policy":
		"Use DROP POLICY IF EXISTS, or guard CREATE/ALTER POLICY with to_regclass() and pg_policies.",
	"alter-view": "Guard ALTER VIEW with to_regclass() or pg_class existence checks.",
	"function-grant":
		"Guard function grants/revokes/alters with to_regprocedure(), pg_proc, or oidvectortypes().",
	"publication":
		"Guard publication membership changes with pg_publication/pg_publication_tables checks.",
	"function-body":
		"Function bodies that depend on optional historical tables should guard with to_regclass() or ensure the table is created earlier in clean replay.",
};

function normalizePath(path) {
	return path.replaceAll("\\", "/");
}

function isMigrationFile(path) {
	return normalizePath(path).startsWith("supabase/migrations/") && path.endsWith(".sql");
}

function git(args, options = {}) {
	return execFileSync("git", args, {
		cwd: ROOT,
		encoding: "utf8",
		stdio: ["ignore", "pipe", options.ignoreErrors ? "ignore" : "pipe"],
	}).trim();
}

function gitMaybe(args) {
	try {
		return git(args, { ignoreErrors: true });
	} catch {
		return "";
	}
}

function uniqueSorted(paths) {
	return [...new Set(paths.map(normalizePath))]
		.filter(isMigrationFile)
		.filter((path) => existsSync(join(ROOT, path)))
		.sort();
}

export function getTargetFiles(args = process.argv.slice(2)) {
	const explicit = args.filter((arg) => !arg.startsWith("--"));
	if (explicit.length > 0) return uniqueSorted(explicit);

	if (args.includes("--all")) {
		return readdirSync(MIGRATIONS_DIR)
			.filter((file) => file.endsWith(".sql"))
			.map((file) => normalizePath(`supabase/migrations/${file}`))
			.sort();
	}

	const baseArg = args.find((arg) => arg.startsWith("--base="));
	const base = baseArg?.split("=", 2)[1];
	const changed = [];

	if (base) {
		changed.push(
			...gitMaybe(["diff", "--name-only", "--diff-filter=ACMR", `${base}...HEAD`, "--", "supabase/migrations"])
				.split("\n")
				.filter(Boolean),
		);
	} else {
		const upstream = gitMaybe(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]);
		const defaultBase = gitMaybe(["rev-parse", "--verify", "origin/main"]);
		const compareRef = upstream || (defaultBase ? "origin/main" : "");
		const mergeBase = compareRef ? gitMaybe(["merge-base", "HEAD", compareRef]) : "";
		const committedRange = mergeBase ? `${mergeBase}...HEAD` : "HEAD~1..HEAD";
		changed.push(
			...gitMaybe(["diff", "--name-only", "--diff-filter=ACMR", committedRange, "--", "supabase/migrations"])
				.split("\n")
				.filter(Boolean),
		);
	}

	changed.push(
		...gitMaybe(["diff", "--name-only", "--diff-filter=ACMR", "--", "supabase/migrations"])
			.split("\n")
			.filter(Boolean),
		...gitMaybe(["diff", "--cached", "--name-only", "--diff-filter=ACMR", "--", "supabase/migrations"])
			.split("\n")
			.filter(Boolean),
		...gitMaybe(["ls-files", "--others", "--exclude-standard", "--", "supabase/migrations"])
			.split("\n")
			.filter(Boolean),
	);

	return uniqueSorted(changed);
}

function stripComments(sql) {
	return sql
		.replace(/\/\*[\s\S]*?\*\//g, "")
		.split("\n")
		.filter((line) => !line.trim().startsWith("--"))
		.join("\n");
}

export function splitSqlStatements(sql) {
	const statements = [];
	let current = "";
	let quote = null;
	let dollarQuote = null;

	for (let i = 0; i < sql.length; i++) {
		const char = sql[i];
		const rest = sql.slice(i);

		if (dollarQuote) {
			current += char;
			if (rest.startsWith(dollarQuote)) {
				current += dollarQuote.slice(1);
				i += dollarQuote.length - 1;
				dollarQuote = null;
			}
			continue;
		}

		if (quote) {
			current += char;
			if (char === quote && sql[i - 1] !== "\\") quote = null;
			continue;
		}

		const dollarMatch = rest.match(/^\$[A-Za-z0-9_]*\$/);
		if (dollarMatch) {
			dollarQuote = dollarMatch[0];
			current += dollarQuote;
			i += dollarQuote.length - 1;
			continue;
		}

		if (char === "'" || char === '"') {
			quote = char;
			current += char;
			continue;
		}

		if (char === ";") {
			const trimmed = current.trim();
			if (trimmed) statements.push(trimmed);
			current = "";
			continue;
		}

		current += char;
	}

	const trimmed = current.trim();
	if (trimmed) statements.push(trimmed);
	return statements;
}

function lineForIndex(sql, index) {
	return sql.slice(0, index).split("\n").length;
}

function hasAny(statement, patterns) {
	return patterns.some((pattern) => pattern.test(statement));
}

function isAllowed(statement) {
	return /\breplay-lint:\s*allow\b/i.test(statement);
}

function tableGuarded(statement) {
	return hasAny(statement, [
		/\bif\s+exists\b/i,
		/\bto_regclass\s*\(/i,
		/\binformation_schema\.tables\b/i,
		/\bpg_class\b/i,
		/\bpg_tables\b/i,
	]);
}

function policyGuarded(statement) {
	return hasAny(statement, [
		/\bdrop\s+policy\s+if\s+exists\b/i,
		/\bto_regclass\s*\(/i,
		/\bpg_policies\b/i,
		/\binformation_schema\.tables\b/i,
		/\bpg_class\b/i,
	]);
}

function functionGuarded(statement) {
	return hasAny(statement, [
		/\bto_regprocedure\s*\(/i,
		/\bpg_proc\b/i,
		/\boidvectortypes\s*\(/i,
	]);
}

function publicationGuarded(statement) {
	return hasAny(statement, [
		/\bpg_publication\b/i,
		/\bpg_publication_tables\b/i,
		/\bexists\s*\(/i,
	]);
}

function addIssue(issues, category, statement, line) {
	issues.push({
		category,
		line,
		statement: statement.split("\n").map((part) => part.trim()).find(Boolean) ?? "",
		suggestion: CATEGORY_HELP[category],
	});
}

export function analyzeSql(sql) {
	const uncommented = stripComments(sql);
	const statements = splitSqlStatements(uncommented);
	const issues = [];
	let searchFrom = 0;

	for (const statement of statements) {
		const index = uncommented.indexOf(statement, searchFrom);
		searchFrom = index + statement.length;
		const line = lineForIndex(uncommented, Math.max(index, 0));

		if (isAllowed(statement)) continue;

		if (/\balter\s+table\s+(?!if\s+exists\b)/i.test(statement) && !tableGuarded(statement)) {
			addIssue(issues, "alter-table", statement, line);
		}

		const hasPolicyOperation =
			/\b(?:create|alter)\s+policy\b/i.test(statement) ||
			/\bdrop\s+policy\s+(?!if\s+exists\b)/i.test(statement);
		if (hasPolicyOperation && !policyGuarded(statement)) {
			addIssue(issues, "policy", statement, line);
		}

		if (/\balter\s+view\s+(?!if\s+exists\b)/i.test(statement) && !tableGuarded(statement)) {
			addIssue(issues, "alter-view", statement, line);
		}

		const hasFunctionGrant =
			/\b(?:grant|revoke)\s+execute\s+on\s+function\b/i.test(statement) ||
			/\balter\s+function\b/i.test(statement);
		if (hasFunctionGrant && !functionGuarded(statement)) {
			addIssue(issues, "function-grant", statement, line);
		}

		if (/\balter\s+publication\b/i.test(statement) && !publicationGuarded(statement)) {
			addIssue(issues, "publication", statement, line);
		}

		const createsFunction = /\bcreate\s+(?:or\s+replace\s+)?function\b/i.test(statement);
		const referencesPublicTable = /\b(?:from|join|update|into)\s+public\.[a-z_][\w$]*/i.test(statement);
		if (createsFunction && referencesPublicTable && !tableGuarded(statement)) {
			addIssue(issues, "function-body", statement, line);
		}
	}

	return issues;
}

export function lintFiles(files) {
	return files.flatMap((file) => {
		const issues = analyzeSql(readFileSync(join(ROOT, file), "utf8"));
		return issues.map((issue) => ({ file, ...issue }));
	});
}

function main() {
	const files = getTargetFiles();
	if (files.length === 0) {
		console.log("ok: no changed Supabase migration files to lint");
		return;
	}

	const issues = lintFiles(files);
	if (issues.length === 0) {
		console.log(`ok: ${files.length} changed Supabase migration file(s) passed replay lint`);
		return;
	}

	console.error(`ERROR: ${issues.length} Supabase migration replay lint issue(s) found:`);
	for (const issue of issues) {
		console.error(
			`  ${issue.file}:${issue.line} [${issue.category}] ${issue.statement}`,
		);
		console.error(`    ${issue.suggestion}`);
	}
	process.exit(1);
}

if (import.meta.url === `file://${process.argv[1]}`) main();
