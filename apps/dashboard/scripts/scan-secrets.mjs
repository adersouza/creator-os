import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, statSync } from "node:fs";

const patterns = [
  {
    name: "Juno33 API key",
    pattern: "juno_ak_[A-Za-z0-9]{32,}",
  },
];

const allowedPaths = new Set([
  ".mcp.example.json",
  "scripts/scan-secrets.mjs",
  "api/mcp.ts",
]);

const violations = [];

const trackedFiles = execFileSync("git", ["ls-files"], { encoding: "utf8" })
  .split("\n")
  .filter(Boolean);

for (const { name, pattern } of patterns) {
  const regex = new RegExp(pattern, "g");
  for (const file of trackedFiles) {
    if (allowedPaths.has(file) || !existsSync(file)) continue;
    if (statSync(file).size > 5 * 1024 * 1024) continue;

    let content = "";
    try {
      content = readFileSync(file, "utf8");
    } catch {
      continue;
    }

    const lines = content.split("\n");
    for (let index = 0; index < lines.length; index += 1) {
      regex.lastIndex = 0;
      if (regex.test(lines[index])) {
        violations.push(`${file}:${index + 1}: contains ${name}`);
      }
    }
  }
}

if (violations.length) {
  console.error("Secret scan failed:\n" + violations.join("\n"));
  process.exit(1);
}

console.log("Secret scan passed.");
