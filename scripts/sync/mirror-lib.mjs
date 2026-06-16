// Shared logic for mirror sync + parity check.
// Source of truth = split repos (live runtime). Monorepo mirrors are generated,
// never hand-edited. See scripts/sync/README.md and REMEDIATION_MASTER_PLAN.md WS1.

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  mkdirSync,
  readFileSync,
  writeFileSync,
  existsSync,
  readdirSync,
  statSync,
  lstatSync,
  rmSync,
} from "node:fs";
import { dirname, join, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const PROVENANCE_FILE = "MIRROR_PROVENANCE.json";

export function loadConfig() {
  const raw = readFileSync(join(REPO_ROOT, "mirror-sources.json"), "utf8");
  const cfg = JSON.parse(raw);
  const excludeDefault = cfg.excludeDefault ?? [];
  for (const m of cfg.mirrors) {
    m.exclude = [...excludeDefault, ...(m.exclude ?? [])];
    m.include = m.include ?? ["**/*"];
  }
  return cfg;
}

// Compile a glob-ish pattern to a predicate over a posix relative path.
// Supports: trailing-slash dir names (any segment), "**/name/", "*.ext",
// "*.ext*" (substring), and literal prefixes.
function patternToTest(pattern) {
  if (pattern.endsWith("/")) {
    const name = pattern.slice(0, -1).replace(/^\*\*\//, "");
    if (name.startsWith("*.")) {
      const suffix = name.slice(1);
      return (p) => p.split("/").some((segment) => segment.endsWith(suffix));
    }
    return (p) => p.split("/").includes(name);
  }
  if (pattern.startsWith("*.") && pattern.endsWith("*")) {
    const needle = pattern.slice(1, -1); // ".sqlite" from "*.sqlite*"
    return (p) => p.includes(needle);
  }
  if (pattern.startsWith("*.")) {
    const ext = pattern.slice(1); // ".mp4"
    return (p) => p.endsWith(ext);
  }
  if (pattern === "**/*") return () => true;
  return (p) => p === pattern || p.startsWith(pattern.replace(/\/$/, "") + "/");
}

function buildFilter(globs) {
  const tests = globs.map(patternToTest);
  return (p) => tests.some((t) => t(p));
}

export function listSourceFiles(mirror) {
  const repo = resolve(REPO_ROOT, mirror.sourceRepoPath);
  const out = execFileSync(
    "git",
    ["-C", repo, "ls-tree", "-r", "--name-only", mirror.sourceCommit],
    { encoding: "utf8", maxBuffer: 256 * 1024 * 1024 },
  );
  const all = out.split("\n").map((s) => s.trim()).filter(Boolean);
  const isExcluded = buildFilter(mirror.exclude);
  const isIncluded =
    mirror.include.includes("**/*") ? () => true : buildFilter(mirror.include);
  return all.filter((p) => isIncluded(p) && !isExcluded(p)).sort();
}

export function readSourceFile(mirror, path) {
  const repo = resolve(REPO_ROOT, mirror.sourceRepoPath);
  return execFileSync("git", ["-C", repo, "show", `${mirror.sourceCommit}:${path}`], {
    maxBuffer: 256 * 1024 * 1024,
  }); // Buffer (binary-safe)
}

function sha256(buf) {
  return createHash("sha256").update(buf).digest("hex");
}

function cleanMirrorTree(destBase, isExcluded) {
  if (!existsSync(destBase)) return;
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      const rel = relative(destBase, full);
      if (isExcluded(rel)) continue;
      const ls = lstatSync(full);
      if (ls.isDirectory()) {
        walk(full);
        try {
          if (readdirSync(full).length === 0) rmSync(full, { recursive: true, force: true });
        } catch {
          // Ignore cleanup races with generated artifacts.
        }
      } else {
        rmSync(full, { force: true });
      }
    }
  };
  walk(destBase);
}

// Materialize a mirror's source content into destRoot/<mirrorPath>.
// Returns { files: [{path, hash}], provenance }.
export function materialize(mirror, destRoot) {
  const files = listSourceFiles(mirror);
  const destBase = join(destRoot, mirror.mirrorPath);
  cleanMirrorTree(destBase, buildFilter(mirror.exclude));
  const manifest = [];
  for (const p of files) {
    const buf = readSourceFile(mirror, p);
    const target = join(destBase, p);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, buf);
    manifest.push({ path: p, hash: sha256(buf) });
  }
  const provenance = {
    schema: "creator-os.mirror_provenance.v1",
    sourceRepo: mirror.sourceRepoPath,
    sourceCommit: mirror.sourceCommit,
    mirrorPath: mirror.mirrorPath,
    fileCount: manifest.length,
    note: "GENERATED read-only mirror. Do not hand-edit. Run scripts/sync/mirror-sync.mjs.",
  };
  writeFileSync(
    join(destBase, PROVENANCE_FILE),
    JSON.stringify(provenance, null, 2) + "\n",
  );
  return { files: manifest, provenance };
}

// Hash an on-disk tree (the committed mirror), ignoring the provenance file's
// own volatility is unnecessary — provenance is deterministic, so include it.
export function hashTree(absDir, isExcluded = () => false) {
  const map = new Map();
  if (!existsSync(absDir)) return map;
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      const rel = relative(absDir, full);
      if (isExcluded(rel)) continue;
      let ls;
      try {
        ls = lstatSync(full);
      } catch {
        continue; // unreadable entry — skip
      }
      if (ls.isSymbolicLink()) {
        // Do not follow symlinks (may dangle); record the link path as a marker.
        map.set(rel, "symlink:" + sha256(Buffer.from(full)));
        continue;
      }
      if (ls.isDirectory()) walk(full);
      else if (ls.isFile()) {
        try {
          map.set(rel, sha256(readFileSync(full)));
        } catch {
          continue;
        }
      }
    }
  };
  walk(absDir);
  return map;
}

// Compare expected (from source) vs actual (committed mirror on disk).
// Returns { missing, extra, changed } arrays of relative paths.
export function diffMirror(mirror, tempRoot) {
  const expectedDir = join(tempRoot, mirror.mirrorPath);
  const actualDir = join(REPO_ROOT, mirror.mirrorPath);
  const expected = hashTree(expectedDir);
  const actual = hashTree(actualDir, buildFilter(mirror.exclude));
  const missing = [];
  const changed = [];
  const extra = [];
  for (const [p, h] of expected) {
    if (!actual.has(p)) missing.push(p);
    else if (actual.get(p) !== h) changed.push(p);
  }
  for (const p of actual.keys()) if (!expected.has(p)) extra.push(p);
  return {
    missing: missing.sort(),
    changed: changed.sort(),
    extra: extra.sort(),
  };
}
