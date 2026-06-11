#!/usr/bin/env node
// CI guard: catches broken `lazy(() => import('./foo').then(m => m.Foo))` paths.
//
// Two things can silently break and only crash at runtime:
//   1. The import path resolves to a file that doesn't exist.
//   2. The named export being destructured isn't actually exported.
//
// TS can miss (1) when the tsconfig paths glob hides the file, and misses (2)
// when the target file has type-only imports that fail at runtime. This
// script walks the source tree, pulls every `lazy(() => import(...))` call,
// and verifies the path + named export both resolve.
//
// Exit 0 = clean. Exit 1 = at least one broken lazy import.

import { readFileSync, statSync, readdirSync } from 'node:fs';
import { dirname, resolve, extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const SRC = join(ROOT, 'src');

const EXTS = ['.ts', '.tsx', '.js', '.jsx'];

// Resolve a TS import specifier to an on-disk file. Handles:
//   - direct paths:              './Foo'      -> './Foo.tsx'
//   - index files:               './foo'      -> './foo/index.ts'
//   - path alias `@/` -> src/:   '@/pages/X'  -> 'src/pages/X.tsx'
function resolveImport(fromFile, specifier) {
  let base;
  if (specifier.startsWith('@/')) {
    base = join(SRC, specifier.slice(2));
  } else if (specifier.startsWith('./') || specifier.startsWith('../')) {
    base = resolve(dirname(fromFile), specifier);
  } else {
    // bare package import — TypeScript/Vite resolve these; not our concern
    return 'BARE_IMPORT';
  }

  if (extname(base) && fileExists(base)) return base;

  for (const ext of EXTS) {
    if (fileExists(base + ext)) return base + ext;
  }
  for (const ext of EXTS) {
    const idx = join(base, `index${ext}`);
    if (fileExists(idx)) return idx;
  }
  return null;
}

function fileExists(p) {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

// Quick-and-dirty named-export check. We regex-grep the target file for
// `export function Foo`, `export const Foo`, `export class Foo`, or
// `export { Foo }` / `export { Foo as X }`. Misses computed exports but
// catches the 99% case: named-component exports from page/widget files.
function hasNamedExport(filePath, name) {
  const src = readFileSync(filePath, 'utf8');
  const patterns = [
    new RegExp(`export\\s+(?:async\\s+)?function\\s+${name}\\b`),
    new RegExp(`export\\s+(?:const|let|var)\\s+${name}\\b`),
    new RegExp(`export\\s+class\\s+${name}\\b`),
    new RegExp(`export\\s*\\{[^}]*\\b${name}\\b[^}]*\\}`),
  ];
  return patterns.some((p) => p.test(src));
}

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walk(full));
    } else if (EXTS.includes(extname(entry.name))) {
      out.push(full);
    }
  }
  return out;
}

// Pattern: lazy(() => import('./path').then(m => ({ default: m.Name })))
// Also catches: lazy(() => import('./path'))  -> default export expected
const LAZY_RE = /lazy\s*\(\s*\(\s*\)\s*=>\s*import\(\s*['"]([^'"]+)['"]\s*\)(?:\s*\.then\(\s*(?:[^)]*?)\s*=>\s*\(\s*\{\s*default\s*:\s*[a-zA-Z_$][\w$]*\.([a-zA-Z_$][\w$]*)\s*\}\s*\))?/g;

const problems = [];

for (const file of walk(SRC)) {
  const src = readFileSync(file, 'utf8');
  let m;
  while ((m = LAZY_RE.exec(src)) !== null) {
    const [, importPath, exportName] = m;
    const resolved = resolveImport(file, importPath);
    if (!resolved) {
      problems.push({ file, importPath, reason: 'file not found' });
      continue;
    }
    if (resolved === 'BARE_IMPORT') {
      // Bare package imports (e.g. '@paper-design/shaders-react') are
      // resolved by Vite/TS at build time — skip the on-disk check.
      continue;
    }
    if (exportName && exportName !== 'default' && !hasNamedExport(resolved, exportName)) {
      problems.push({
        file,
        importPath,
        reason: `'${exportName}' is not exported from ${resolved.replace(ROOT + '/', '')}`,
      });
    }
  }
}

if (problems.length === 0) {
  console.log('ok: all lazy() imports resolve');
  process.exit(0);
}

console.error(`ERROR: ${problems.length} broken lazy() import${problems.length === 1 ? '' : 's'}:`);
for (const p of problems) {
  console.error(`  ${p.file.replace(ROOT + '/', '')} -> '${p.importPath}': ${p.reason}`);
}
process.exit(1);
