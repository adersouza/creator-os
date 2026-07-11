import { existsSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";

var PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

export function getPythonCommand() {
  if (process.env.CONTENTFORGE_PYTHON) return process.env.CONTENTFORGE_PYTHON;
  var candidates = [
    process.env.VIRTUAL_ENV ? path.join(process.env.VIRTUAL_ENV, "bin", "python") : null,
    path.join(PROJECT_ROOT, ".venv", "bin", "python"),
    path.join(process.cwd(), ".venv", "bin", "python"),
    "/usr/local/bin/python3.11",
    "/opt/homebrew/bin/python3.11",
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
  ];
  for (var candidate of candidates) {
    if (candidate && existsSync(candidate)) return candidate;
  }
  return "python3";
}
