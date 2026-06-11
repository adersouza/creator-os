import { existsSync } from "fs";
import path from "path";

export function getPythonCommand() {
  if (process.env.CONTENTFORGE_PYTHON) return process.env.CONTENTFORGE_PYTHON;
  var venvPython = path.join(process.cwd(), ".venv", "bin", "python");
  if (existsSync(venvPython)) return venvPython;
  if (existsSync("/usr/local/bin/python3.11")) return "/usr/local/bin/python3.11";
  if (existsSync("/opt/homebrew/bin/python3.11")) return "/opt/homebrew/bin/python3.11";
  if (existsSync("/opt/homebrew/bin/python3")) return "/opt/homebrew/bin/python3";
  if (existsSync("/usr/local/bin/python3")) return "/usr/local/bin/python3";
  return "python3";
}
