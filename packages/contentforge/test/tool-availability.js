import { spawnSync } from "child_process";

function forcedMissingTools() {
  return new Set((process.env.CONTENTFORGE_FORCE_MISSING_TOOLS || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean));
}

export function hasTool(command) {
  if (forcedMissingTools().has(command)) return false;
  // Tools disagree on the flag: ffmpeg wants -version, tesseract exits 1 on
  // -version and wants --version. Accept either so installed tools are never
  // misreported as missing.
  for (var flags of [["-version"], ["--version"]]) {
    var result = spawnSync(command, flags, {
      encoding: "utf8",
      stdio: ["ignore", "ignore", "ignore"],
    });
    if (result.status === 0) return true;
  }
  return false;
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
