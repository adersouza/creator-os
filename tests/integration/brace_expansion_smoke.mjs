import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const pnpmStore = path.join(root, "node_modules", ".pnpm");
const minimatchEntry = fs
  .readdirSync(pnpmStore, { withFileTypes: true })
  .filter((entry) => entry.isDirectory() && entry.name.startsWith("minimatch@10."))
  .map((entry) => path.join(pnpmStore, entry.name, "node_modules", "minimatch"))
  .sort()
  .at(-1);

assert.ok(minimatchEntry, "minimatch 10 dependency is installed");
const minimatchRequire = createRequire(path.join(minimatchEntry, "package.json"));
const { minimatch } = minimatchRequire(minimatchEntry);
const bracePackagePath = minimatchRequire.resolve("brace-expansion/package.json");
const bracePackage = JSON.parse(fs.readFileSync(bracePackagePath, "utf8"));

assert.ok(
  Number(bracePackage.version.split(".")[0]) >= 5,
  "minimatch 10 must resolve the supported brace-expansion 5 line",
);
assert.equal(minimatch("clip.ts", "*.{js,ts}"), true);
assert.equal(minimatch("clip.py", "*.{js,ts}"), false);

const { expand } = minimatchRequire("brace-expansion");
assert.deepEqual(expand("asset-{one,two}.mp4"), [
  "asset-one.mp4",
  "asset-two.mp4",
]);
const bounded = expand("{a,b}{c,d}{e,f}", { max: 100, maxLength: 8 });
assert.ok(
  bounded.reduce((total, value) => total + value.length, 0) <= 8,
  "maintenance backport must enforce the aggregate expansion-length bound",
);

console.log(
  `brace-expansion ${bracePackage.version} compatibility smoke passed through minimatch 10`,
);
