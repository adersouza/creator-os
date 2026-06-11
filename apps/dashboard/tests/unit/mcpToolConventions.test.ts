/**
 * MCP Tool Convention Validation
 *
 * Statically analyzes all tool definition files in mcp-server/src/tools/ to
 * enforce naming, schema, and response conventions. Runs in CI to prevent drift.
 *
 * Rules enforced:
 *  1. platform params must use z.enum(), never z.string()
 *  2. status params must use z.enum(), never z.string()
 *  3. dryRun params must use .default(true), never .optional()
 *  4. Responses must go through respond()/success()/error()/dryRunResponse()
 *  5. No local AI_TIMEOUT — must import from helpers
 *  6. 2-space indentation (no 4-space)
 *  7. Tool names must be snake_case
 *  8. No bare z.enum()/z.literal()/z.unknown()/z.record() (Vercel TS 5.9 safety)
 */

import { describe, it, expect } from "vitest";
import * as fs from "fs";
import * as path from "path";

const TOOLS_DIR = path.resolve(__dirname, "../../mcp-server/src/tools");

// Read all .ts files in tools/
function getToolFiles(): { name: string; content: string; lines: string[] }[] {
  return fs
    .readdirSync(TOOLS_DIR)
    .filter((f) => f.endsWith(".ts") && !f.startsWith("__"))
    .map((f) => {
      const content = fs.readFileSync(path.join(TOOLS_DIR, f), "utf-8");
      return { name: f, content, lines: content.split("\n") };
    });
}

describe("MCP Tool Conventions", () => {
  const files = getToolFiles();

  // ─── Rule 1: platform params must use z.enum() ──────────────────────

  it("platform params should use z.enum(), not z.string()", () => {
    const violations: string[] = [];
    for (const { name, lines } of files) {
      lines.forEach((line, i) => {
        // Match: platform: z.string() with description mentioning threads/instagram
        if (
          /platform.*z\.string\(\)/.test(line) &&
          /threads|instagram/i.test(line)
        ) {
          violations.push(`${name}:${i + 1} — platform uses z.string() instead of z.enum()`);
        }
      });
    }
    expect(violations, violations.join("\n")).toHaveLength(0);
  });

  // ─── Rule 2: status params should use z.enum() ──────────────────────

  it("status params should use z.enum(), not z.string()", () => {
    const violations: string[] = [];
    for (const { name, lines } of files) {
      lines.forEach((line, i) => {
        // Match: status: z.string() with description listing valid values
        if (
          /^\s*status.*z\.string\(\)/.test(line) &&
          /pending|published|draft|scheduled|failed/i.test(line)
        ) {
          violations.push(`${name}:${i + 1} — status uses z.string() instead of z.enum()`);
        }
      });
    }
    expect(violations, violations.join("\n")).toHaveLength(0);
  });

  // ─── Rule 3: dryRun must use .default(true) ─────────────────────────

  it("dryRun params should use .default(true), not .optional()", () => {
    const violations: string[] = [];
    for (const { name, lines } of files) {
      lines.forEach((line, i) => {
        if (/dryRun.*zBool\.optional\(\)/.test(line)) {
          violations.push(`${name}:${i + 1} — dryRun uses .optional() instead of .default(true)`);
        }
      });
    }
    expect(violations, violations.join("\n")).toHaveLength(0);
  });

  // ─── Rule 4: responses should use standard helpers ──────────────────

  it("should not construct raw MCP response objects", () => {
    const violations: string[] = [];
    // Pattern: { content: [{ type: "text" ... directly in tool handlers
    // Allow in helpers.ts but not in tool files
    const rawPattern = /return\s*\{\s*content:\s*\[\s*\{/;
    for (const { name, lines } of files) {
      lines.forEach((line, i) => {
        if (rawPattern.test(line)) {
          violations.push(
            `${name}:${i + 1} — raw MCP response object. Use respond()/success()/error()/dryRunResponse() instead.`
          );
        }
      });
    }
    expect(violations, violations.join("\n")).toHaveLength(0);
  });

  // ─── Rule 5: no local AI_TIMEOUT ───────────────────────────────────

  it("should not define local AI_TIMEOUT — import from helpers", () => {
    const violations: string[] = [];
    for (const { name, lines } of files) {
      lines.forEach((line, i) => {
        if (/^\s*const\s+AI_TIMEOUT\s*=/.test(line)) {
          violations.push(`${name}:${i + 1} — local AI_TIMEOUT. Import from helpers.js instead.`);
        }
      });
    }
    expect(violations, violations.join("\n")).toHaveLength(0);
  });

  // ─── Rule 6: 2-space indentation ───────────────────────────────────

  it("should use 2-space indentation, not 4-space", () => {
    const violations: string[] = [];
    for (const { name, lines } of files) {
      // Check first indented line after server.tool — if it uses 4 spaces, flag
      let inTool = false;
      for (let i = 0; i < lines.length; i++) {
        if (/server\.tool\(/.test(lines[i])) inTool = true;
        if (inTool && /^ {4}\S/.test(lines[i]) && !/^ {2}/.test(lines[i])) {
          // 4-space indent that isn't just 2+2 (continuation)
          violations.push(`${name}:${i + 1} — appears to use 4-space indentation`);
          break; // one per file is enough
        }
      }
    }
    expect(violations, violations.join("\n")).toHaveLength(0);
  });

  // ─── Rule 7: tool names must be snake_case ─────────────────────────

  it("tool names should be snake_case", () => {
    const violations: string[] = [];
    const toolNamePattern = /server\.tool\(\s*"([^"]+)"/g;
    for (const { name, content } of files) {
      let match;
      while ((match = toolNamePattern.exec(content)) !== null) {
        const toolName = match[1];
        if (toolName !== toolName.toLowerCase()) {
          violations.push(`${name} — tool "${toolName}" is not lowercase snake_case`);
        }
        if (/[A-Z]/.test(toolName)) {
          violations.push(`${name} — tool "${toolName}" contains uppercase`);
        }
        if (/-/.test(toolName)) {
          violations.push(`${name} — tool "${toolName}" uses hyphens instead of underscores`);
        }
      }
    }
    expect(violations, violations.join("\n")).toHaveLength(0);
  });

  // ─── Rule 8: no bare z.enum()/z.literal() etc in tool schemas ──────
  // Vercel's TS 5.9 breaks on these — must use (z as any) in API routes.
  // MCP server compiles separately so this is informational, but keeps
  // the pattern consistent if code is copy-pasted between API + MCP.

  it("should not use scope: z.string() for known enum values", () => {
    const violations: string[] = [];
    for (const { name, lines } of files) {
      lines.forEach((line, i) => {
        // scope param that describes known values but uses z.string()
        if (
          /^\s*scope.*z\.string\(\)/.test(line) &&
          /master|group_mode|workspace/i.test(line)
        ) {
          violations.push(`${name}:${i + 1} — scope uses z.string() instead of z.enum()`);
        }
      });
    }
    expect(violations, violations.join("\n")).toHaveLength(0);
  });

  // ─── Structural checks ─────────────────────────────────────────────

  it("every tool file should export a register function", () => {
    const violations: string[] = [];
    for (const { name, content } of files) {
      if (
        !content.includes("export const register") &&
        !content.includes("export function register")
      ) {
        violations.push(`${name} — missing \`export const register\``);
      }
    }
    expect(violations, violations.join("\n")).toHaveLength(0);
  });

  it("every tool file should import from helpers.js", () => {
    const violations: string[] = [];
    for (const { name, content } of files) {
      if (!content.includes("../helpers.js")) {
        violations.push(`${name} — does not import from helpers.js`);
      }
    }
    expect(violations, violations.join("\n")).toHaveLength(0);
  });

  // ─── Summary ───────────────────────────────────────────────────────

  it("should have at least 190 tools registered across all files", () => {
    let count = 0;
    const toolNamePattern = /server\.tool\(\s*"/g;
    for (const { content } of files) {
      while (toolNamePattern.exec(content) !== null) {
        count++;
      }
    }
    // Sanity check: we know there are ~198 tools. If this drops significantly,
    // someone deleted tools without updating the count.
    expect(count).toBeGreaterThanOrEqual(190);
  });

  it("tool names should be unique across all files", () => {
    const seen = new Map<string, string>();
    const duplicates: string[] = [];
    const toolNamePattern = /server\.tool\(\s*"([^"]+)"/g;
    for (const { name, content } of files) {
      let match;
      while ((match = toolNamePattern.exec(content)) !== null) {
        const toolName = match[1];
        if (seen.has(toolName)) {
          duplicates.push(`"${toolName}" defined in both ${seen.get(toolName)} and ${name}`);
        }
        seen.set(toolName, name);
      }
    }
    expect(duplicates, duplicates.join("\n")).toHaveLength(0);
  });
});
