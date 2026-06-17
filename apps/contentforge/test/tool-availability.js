import { spawnSync } from "child_process";

function forcedMissingTools() {
  return new Set((process.env.CONTENTFORGE_FORCE_MISSING_TOOLS || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean));
}

export function hasTool(command) {
  if (forcedMissingTools().has(command)) return false;
  var result = spawnSync(command, ["-version"], {
    encoding: "utf8",
    stdio: ["ignore", "ignore", "ignore"],
  });
  return result.status === 0;
}

export function missingTools(tools) {
  return tools.filter((tool) => !hasTool(tool));
}

export function skipWhenMissingTools(t, tools) {
  var missing = missingTools(tools);
  if (missing.length > 0) {
    t.skip("missing required media tool(s): " + missing.join(", "));
    return true;
  }
  return false;
}
