import { describe, expect, it } from "vitest";
import * as fs from "fs";
import * as path from "path";

const ROOT = path.resolve(__dirname, "../..");
const API_DIR = path.join(ROOT, "api");
const TOOLS_DIR = path.join(ROOT, "mcp-server/src/tools");

const INTERNAL_OR_PUBLIC_ROUTES = new Set([
  "auto-post-publish",
  "auto-reply",
  "auto-reply-harvest",
  "autopilot-replay",
  "check-deletion-status",
  "cross-reply-publish",
  "csp-report",
  "dispatch-manual-queue",
  "favicon",
  "jobs",
  "mcp",
  "notifications",
  "qstash-failure",
  "queue-fill",
  "reliability",
  "scheduled-post-publish",
  "sentry-tunnel",
  "shared-report",
  "sitemap",
  "telemetry",
  "webhook",
  "webhooks",
]);

const IGNORED_API_DIRS = new Set([
  "_lib",
  "auth",
  "cron",
  "go",
  "health",
  "link-page",
  "meta",
  "node_modules",
  "types",
]);

function walkApiFiles(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (IGNORED_API_DIRS.has(entry.name)) continue;
      walkApiFiles(path.join(dir, entry.name), out);
    } else if (entry.isFile() && entry.name.endsWith(".ts")) {
      out.push(path.join(dir, entry.name));
    }
  }
  return out;
}

function agentFacingApiRoutes(): string[] {
  return [...new Set(walkApiFiles(API_DIR)
    .map((file) => path.relative(API_DIR, file).replace(/\.ts$/, "").split(path.sep)[0])
    .filter((route) => !INTERNAL_OR_PUBLIC_ROUTES.has(route)))]
    .sort();
}

function mcpApiRoutes(): string[] {
  const routes = new Set<string>();
  for (const file of fs.readdirSync(TOOLS_DIR).filter((name) => name.endsWith(".ts"))) {
    const content = fs.readFileSync(path.join(TOOLS_DIR, file), "utf8");
    for (const match of content.matchAll(/api\(\s*(?:`([^`]+)`|"([^"]+)"|'([^']+)')/g)) {
      const literal = (match[1] || match[2] || match[3] || "")
        .replace(/\$\{[^}]+\}/g, "{var}")
        .split("?")[0]
        .replace(/^\//, "");
      const topLevel = literal.split("/")[0];
      if (topLevel) routes.add(topLevel);
    }
  }
  return [...routes].sort();
}

function allApiRouteNames(): Set<string> {
  const routes = new Set<string>();
  for (const file of walkApiFiles(API_DIR)) {
    const route = path.relative(API_DIR, file).replace(/\.ts$/, "");
    routes.add(route);
    routes.add(route.split(path.sep)[0]);
  }
  return routes;
}

function mcpApiLiterals(): Array<{ file: string; path: string; route: string }> {
  const literals: Array<{ file: string; path: string; route: string }> = [];
  for (const file of fs.readdirSync(TOOLS_DIR).filter((name) => name.endsWith(".ts"))) {
    const content = fs.readFileSync(path.join(TOOLS_DIR, file), "utf8");
    for (const match of content.matchAll(/api\(\s*(?:`([^`]+)`|"([^"]+)"|'([^']+)')/g)) {
      const literal = match[1] || match[2] || match[3] || "";
      const route = literal
        .replace(/\$\{[^}]+\}/g, "{var}")
        .split("?")[0]
        .replace(/^\//, "");
      literals.push({ file, path: literal, route });
    }
  }
  return literals;
}

describe("MCP API route coverage", () => {
  it("covers every agent-facing top-level API route or explicitly classifies it as internal/public", () => {
    const mcpRoutes = new Set(mcpApiRoutes());
    const missing = agentFacingApiRoutes().filter((route) => !mcpRoutes.has(route));

    expect(missing, `Missing MCP wrappers for API routes:\n${missing.join("\n")}`).toEqual([]);
  });

  it("does not point MCP tools at missing API routes", () => {
    const apiRoutes = allApiRouteNames();
    const missing = mcpApiLiterals().filter(({ route }) => {
      const topLevel = route.split("/")[0];
      return !apiRoutes.has(route) && !apiRoutes.has(topLevel);
    });

    expect(
      missing,
      `MCP tools call missing API routes:\n${missing.map((m) => `${m.file}: ${m.path}`).join("\n")}`,
    ).toEqual([]);
  });
});
