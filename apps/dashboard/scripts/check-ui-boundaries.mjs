#!/usr/bin/env node
// CI guard: product routes must consume Juno-owned wrappers, not generated
// shadcn registry source. Generated source can live in src/components/shadcn,
// but pages/routes should import through src/components/ui or layout wrappers.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = resolve(fileURLToPath(new URL(".", import.meta.url)));
const ROOT = resolve(__dirname, "..");
const SRC = join(ROOT, "src");
const CHECK_DIRS = [join(SRC, "pages"), join(SRC, "routes")];
const EXTS = new Set([".ts", ".tsx", ".js", ".jsx"]);

const RAW_SHADCN_IMPORT_RE =
	/from\s+["'][^"']*(?:@\/src\/components\/shadcn|@\/components\/shadcn|components\/shadcn)[^"']*["']/;

function existsDirectory(path) {
	try {
		return statSync(path).isDirectory();
	} catch {
		return false;
	}
}

function walk(dir) {
	const out = [];
	if (!existsDirectory(dir)) return out;

	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		if (entry.name.startsWith(".") || entry.name === "node_modules") continue;
		const full = join(dir, entry.name);
		if (entry.isDirectory()) {
			out.push(...walk(full));
		} else if (EXTS.has(extname(entry.name))) {
			out.push(full);
		}
	}
	return out;
}

const violations = [];

for (const dir of CHECK_DIRS) {
	for (const file of walk(dir)) {
		const source = readFileSync(file, "utf8");
		const lines = source.split(/\r?\n/);
		lines.forEach((line, index) => {
			if (RAW_SHADCN_IMPORT_RE.test(line)) {
				violations.push({
					file: relative(ROOT, file),
					line: index + 1,
					source: line.trim(),
				});
			}
		});
	}
}

if (violations.length === 0) {
	console.log("ok: route files do not import raw shadcn source");
	process.exit(0);
}

console.error(
	`ERROR: ${violations.length} route-level raw shadcn import${
		violations.length === 1 ? "" : "s"
	}:`,
);
for (const violation of violations) {
	console.error(
		`  ${violation.file}:${violation.line} ${violation.source}`,
	);
}
console.error(
	"Import app-owned wrappers from src/components/ui or src/components/layout instead.",
);
process.exit(1);
