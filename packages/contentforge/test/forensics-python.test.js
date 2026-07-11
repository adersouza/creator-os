import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "child_process";
import path from "path";

var FORENSICS = path.resolve("lib/forensics_check.py");

function runPython(source) {
  return new Promise(function (resolve, reject) {
    execFile("python3", ["-c", source], {
      cwd: path.resolve("."),
      timeout: 15000,
      maxBuffer: 1024 * 1024,
    }, function (error, stdout, stderr) {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolve(stdout.trim());
    });
  });
}

test("forensics Benford helper uses leading significant digits", async function () {
  var output = await runPython(`
import importlib.util, json
spec = importlib.util.spec_from_file_location("forensics_check", ${JSON.stringify(FORENSICS)})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(json.dumps(mod.first_significant_digits([1, 9, 10, 19, 205, -987, 0, "bad"])))
`);

  assert.deepEqual(JSON.parse(output), [1, 9, 1, 1, 2, 9]);
});

test("forensics unavailable dependency output is advisory-shaped", async function () {
  var output = await runPython(`
import importlib.util, json
spec = importlib.util.spec_from_file_location("forensics_check", ${JSON.stringify(FORENSICS)})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
check = mod.advisory_check({"name": "sample", "pass": None})
print(json.dumps(check, sort_keys=True))
`);

  assert.deepEqual(JSON.parse(output), {
    advisory: true,
    confidence: "heuristic",
    name: "sample",
    pass: null,
  });
});

test("forensics video parser reports malformed ffprobe output as advisory error", async function () {
  var output = await runPython(`
import importlib.util, json
from unittest.mock import patch
spec = importlib.util.spec_from_file_location("forensics_check", ${JSON.stringify(FORENSICS)})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
class Proc:
    stdout = "{bad"
def fake_run(*args, **kwargs):
    return Proc()
with patch.object(mod.subprocess, "run", fake_run):
    report = mod.analyze_video("sample.mp4")
print(json.dumps(report["checks"][0], sort_keys=True))
`);
  var check = JSON.parse(output);

  assert.equal(check.name, "gop_error");
  assert.equal(check.advisory, true);
  assert.equal(check.confidence, "heuristic");
  assert.match(check.label, /Advisory/);
});
