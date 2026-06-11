#!/usr/bin/env node
/**
 * HIG materials lint — catches the one hard rule from
 * juno33_hig_materials.md § Vibrancy × thickness matrix:
 *
 *     "Don't use `quaternary` label on `thin` or `ultra-thin` — contrast too low."
 *
 * Scope: JSX elements whose className contains both `material-(thin|ultra-thin)`
 * and `text-(label|vib)-quaternary` on the SAME element.
 *
 * Does NOT catch descendant violations (would need AST). For those, rely on
 * code review — but defaulting <Card> to `regular` (src/components/ui/Card.tsx)
 * already makes the descendant case vanishingly rare.
 *
 * Exit 0 on clean, 1 on any violation. Wire into CI or a pre-commit hook.
 */
import { readFileSync } from 'node:fs';
import { globSync } from 'node:fs';
import { execSync } from 'node:child_process';

const files = execSync(
  `find src -type f \\( -name '*.tsx' -o -name '*.ts' \\)`,
  { cwd: new URL('..', import.meta.url), encoding: 'utf8' },
)
  .trim()
  .split('\n')
  .filter(Boolean);

// Match a className="..." or className={...'...'} where the string contains
// material-thin / material-ultra-thin. Pragmatic — doesn't parse cn() calls,
// which is fine because the same-element case is what we're guarding against.
const CLASS_RE = /className\s*=\s*(?:"([^"]*)"|'([^']*)'|\{[^}]*?["']([^"']*)["'][^}]*?\})/g;
const BANNED_MATERIAL = /\bmaterial-(?:thin|ultra-thin)\b/;
const BANNED_TEXT = /\btext-(?:label|vib)-quaternary\b/;

let violations = 0;
const root = new URL('..', import.meta.url).pathname;

for (const rel of files) {
  const path = root + rel;
  let src;
  try {
    src = readFileSync(path, 'utf8');
  } catch {
    continue;
  }
  if (!BANNED_MATERIAL.test(src)) continue; // fast reject

  for (const m of src.matchAll(CLASS_RE)) {
    const cls = m[1] ?? m[2] ?? m[3] ?? '';
    if (BANNED_MATERIAL.test(cls) && BANNED_TEXT.test(cls)) {
      const before = src.slice(0, m.index);
      const line = before.split('\n').length;
      console.error(
        `${rel}:${line} — HIG violation: \`material-thin\`/\`ultra-thin\` ` +
        `cannot carry quaternary label text (contrast too low). ` +
        `Move text to primary/secondary/tertiary, or promote material to regular/thick.`,
      );
      violations++;
    }
  }
}

if (violations > 0) {
  console.error(`\n${violations} violation(s). See juno33_hig_materials.md § Vibrancy × thickness matrix.`);
  process.exit(1);
}
console.log('HIG materials lint: clean.');
