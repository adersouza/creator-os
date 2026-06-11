#!/usr/bin/env node

/**
 * Audit Supabase queries against generated types.
 *
 * Parses src/types/supabase.ts to extract table→columns mapping,
 * then scans api/ for three patterns:
 *   1. .from("table")...select("col1, col2")
 *   2. .from("table")...insert({ col1: ..., col2: ... })
 *   3. .from("table")...update({ col1: ..., col2: ... })
 *
 * Flags any column that doesn't exist on that table.
 *
 * Usage:  node scripts/audit-select-columns.mjs
 * Exit 1 if any invalid columns found (CI-safe).
 */

import { existsSync, readFileSync, readdirSync, writeFileSync } from "fs";
import { resolve, dirname, extname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

// ---------------------------------------------------------------------------
// 1. Parse generated types to build table → Set<column> map
// ---------------------------------------------------------------------------
const typesPath = resolve(root, "src/types/supabase.ts");
const typesContent = readFileSync(typesPath, "utf-8");
const baselinePath = resolve(root, "scripts/audit-select-columns-baseline.json");

const tableColumns = new Map();

// Match:   table_name: {\n  Row: {\n    col1: type\n    col2: type ...
const tableRegex = /^\s{6}(\w+):\s*\{\s*\n\s+Row:\s*\{([^}]+)\}/gm;
let match;
while ((match = tableRegex.exec(typesContent)) !== null) {
  const tableName = match[1];
  const rowBlock = match[2];
  const cols = new Set();
  for (const line of rowBlock.split("\n")) {
    const colMatch = line.match(/^\s+(\w+)\s*:/);
    if (colMatch) cols.add(colMatch[1]);
  }
  if (cols.size > 0) tableColumns.set(tableName, cols);
}

// Also parse Insert/Update types — some tables allow extra columns on write
// that aren't in Row (rare, but be safe). Merge them into the same set.
const insertUpdateRegex = /^\s{6}(\w+):\s*\{[\s\S]*?(?:Insert|Update):\s*\{([^}]+)\}/gm;
while ((match = insertUpdateRegex.exec(typesContent)) !== null) {
  const tableName = match[1];
  const block = match[2];
  const existing = tableColumns.get(tableName) || new Set();
  for (const line of block.split("\n")) {
    const colMatch = line.match(/^\s+(\w+)\s*[?:]?\s*:/);
    if (colMatch) existing.add(colMatch[1]);
  }
  if (existing.size > 0) tableColumns.set(tableName, existing);
}

console.log(`Loaded ${tableColumns.size} tables from generated types.`);

// ---------------------------------------------------------------------------
// 2. Recursively collect .ts files in api/
// ---------------------------------------------------------------------------
function walkDir(dir) {
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === ".git") continue;
      files.push(...walkDir(full));
    } else if (extname(entry.name) === ".ts") {
      files.push(full);
    }
  }
  return files;
}

const tsFiles = walkDir(resolve(root, "api"));

// ---------------------------------------------------------------------------
// 3. Scan each file for .from("table") followed by .select/.insert/.update
// ---------------------------------------------------------------------------
const issues = [];

function issueKey(issue) {
  return `${issue.file}:${issue.operation}:${issue.table}:${issue.column}`;
}

for (const filePath of tsFiles) {
  const content = readFileSync(filePath, "utf-8");

  const fromRegex = /\.from\(\s*["'](\w+)["']\s*\)/g;
  let fm;
  while ((fm = fromRegex.exec(content)) !== null) {
    const tableName = fm[1];
    const knownCols = tableColumns.get(tableName);
    if (!knownCols) continue; // table not in generated types

    // Look ahead up to 500 chars for .select(), .insert(), or .update()
    const afterFrom = content.substring(fm.index + fm[0].length, fm.index + fm[0].length + 800);

    // --- Check .select("cols") ---
    const selectMatch = afterFrom.match(/^\s*\n?\s*\.(?:select)\(\s*\n?\s*["'`]([^"'`]+)["'`]/);
    if (selectMatch) {
      const selectStr = selectMatch[1];
      // Strip relation sub-selects like rel(sub1, sub2) and Supabase join
      // modifiers like rel!inner(sub1, sub2) before checking base-table columns.
      const stripped = selectStr.replace(/\w+(?:!\w+)?\s*\([^)]*\)/g, "");
      const selectedCols = stripped
        .split(",")
        .map((c) => c.trim().split(":")[0].split(".")[0]) // handle renames like col:alias
        .filter((c) => c && !c.includes("(") && !c.includes(")") && c !== "*");

      for (const col of selectedCols) {
        if (col.endsWith("!") || col.includes("!")) continue; // Supabase join syntax
        if (!knownCols.has(col)) {
          const lineNum = content.substring(0, fm.index).split("\n").length;
          const relPath = filePath.replace(root + "/", "");
          issues.push({ file: relPath, line: lineNum, table: tableName, column: col, operation: "select" });
        }
      }
    }

    // --- Check .insert({ ... }) and .update({ ... }) ---
    // Match .insert({ or .update({ with optional type assertion before the opening brace
    const writeMatch = afterFrom.match(/^\s*\n?\s*\.(insert|update)\(\s*(?:\n\s*)?(\{)/);
    if (writeMatch) {
      const operation = writeMatch[1];
      const braceStart = fm.index + fm[0].length + afterFrom.indexOf(writeMatch[0]) + writeMatch[0].length - 1;

      // Extract the object literal by counting braces
      let depth = 0;
      let objEnd = braceStart;
      for (let i = braceStart; i < content.length && i < braceStart + 1500; i++) {
        if (content[i] === "{") depth++;
        else if (content[i] === "}") {
          depth--;
          if (depth === 0) {
            objEnd = i + 1;
            break;
          }
        }
      }

      const objStr = content.substring(braceStart, objEnd);

      // Extract top-level keys from the object literal.
      // Match `key:` or `key :` at the start of a line (after whitespace),
      // but not inside nested objects/strings.
      // Simple approach: only match keys at depth 1 (one level of braces)
      let keyDepth = 0;
      let stringQuote = null;
      let escaped = false;
      const keys = [];
      // Track brace depth within the object to only capture top-level keys
      for (let i = 0; i < objStr.length; i++) {
        const char = objStr[i];

        if (stringQuote) {
          if (escaped) {
            escaped = false;
          } else if (char === "\\") {
            escaped = true;
          } else if (char === stringQuote) {
            stringQuote = null;
          }
          continue;
        }

        if (char === "\"" || char === "'" || char === "`") {
          stringQuote = char;
          continue;
        }

        if (char === "{") keyDepth++;
        else if (char === "}") keyDepth--;

        // Only look for keys at depth 1 (top level of the object)
        if (keyDepth === 1) {
          // Check if we're at a key position
          const remaining = objStr.substring(i);
          const keyMatch = remaining.match(/^(\w+)\s*:/);
          if (keyMatch) {
            const key = keyMatch[1];
            // Skip false positives: JS keywords, biome-ignore tokens, single chars,
            // numbers, ternary values, and Supabase query options
            const SKIP_KEYS = new Set([
              "count", "head", "ascending", "foreignTable", "referencedTable",
              "noExplicitAny", "noNonNullAssertion", "noConsole", // biome-ignore tokens
              "true", "false", "null", "undefined", "string", "number", // JS literals/types
              "length", "toString", "valueOf", // JS builtins
            ]);
            const isLikelyFalsePositive =
              SKIP_KEYS.has(key) ||
              key.length <= 1 || // single-char vars from ternaries
              /^\d+$/.test(key) || // pure numbers
              /^[A-Z]/.test(key); // PascalCase = class/type names, not columns
            if (!isLikelyFalsePositive) {
              keys.push(key);
            }
            i += keyMatch[0].length - 1; // advance past the match
          }
        }
      }

      for (const col of keys) {
        if (!knownCols.has(col)) {
          const lineNum = content.substring(0, fm.index).split("\n").length;
          const relPath = filePath.replace(root + "/", "");
          issues.push({ file: relPath, line: lineNum, table: tableName, column: col, operation });
        }
      }
    }
  }
}

// ---------------------------------------------------------------------------
// 4. Report
// ---------------------------------------------------------------------------
const uniqueIssueKeys = Array.from(new Set(issues.map(issueKey))).sort();

if (process.argv.includes("--update-baseline")) {
  writeFileSync(
    baselinePath,
    `${JSON.stringify(uniqueIssueKeys, null, 2)}\n`,
    "utf-8",
  );
  console.log(`Wrote ${uniqueIssueKeys.length} baseline issue key(s).`);
  process.exit(0);
}

const baseline = existsSync(baselinePath)
  ? new Set(JSON.parse(readFileSync(baselinePath, "utf-8")))
  : new Set();
const baselineIssueCount = issues.filter((issue) =>
  baseline.has(issueKey(issue)),
).length;
const newIssues = issues.filter((issue) => !baseline.has(issueKey(issue)));

if (newIssues.length === 0) {
  if (baselineIssueCount > 0) {
    console.log(
      `Ignored ${baselineIssueCount} baseline issue(s); no new column drift found.`,
    );
  }
  console.log("✅ No new .select()/.insert()/.update() column drift found.");
  process.exit(0);
}

// Group by operation type for clearer output
const selectIssues = newIssues.filter((i) => i.operation === "select");
const insertIssues = newIssues.filter((i) => i.operation === "insert");
const updateIssues = newIssues.filter((i) => i.operation === "update");

console.error(
  `\n❌ Found ${newIssues.length} new column(s) not in generated types:\n`,
);

if (baselineIssueCount > 0) {
  console.error(`  Ignored ${baselineIssueCount} baseline issue(s).\n`);
}

if (selectIssues.length > 0) {
  console.error(`  SELECT issues (${selectIssues.length}):`);
  for (const { file, line, table, column } of selectIssues) {
    console.error(`    ${file}:${line}  →  "${column}" not on "${table}"`);
  }
}

if (insertIssues.length > 0) {
  console.error(`\n  INSERT issues (${insertIssues.length}):`);
  for (const { file, line, table, column } of insertIssues) {
    console.error(`    ${file}:${line}  →  "${column}" not on "${table}"`);
  }
}

if (updateIssues.length > 0) {
  console.error(`\n  UPDATE issues (${updateIssues.length}):`);
  for (const { file, line, table, column } of updateIssues) {
    console.error(`    ${file}:${line}  →  "${column}" not on "${table}"`);
  }
}

console.error(
  "\nFix: remove the column, add it via migration, or regenerate types with `supabase gen types`.\n",
);
process.exit(1);
