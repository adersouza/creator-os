import { readFile, writeFile } from "fs/promises";
import path from "path";

const MANIFEST = process.env.CONTENTFORGE_REAL_SAMPLE_MANIFEST ||
  path.resolve("test/fixtures/campaign-factory/manifests/real_samples.json");

function argValue(name, fallback = null) {
  var prefix = name + "=";
  var match = process.argv.slice(2).find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : fallback;
}

function argList(name) {
  var value = argValue(name, "");
  return value ? value.split(",").map((item) => item.trim()).filter(Boolean) : [];
}

var file = argValue("--file");
if (!file) {
  console.error("Usage: npm run fixtures:campaign-factory:feedback -- --file=real_sample_01.mp4 [--acceptedByPlatform=yes|no|unknown] [--expectedUploadReady=true|false] [--expectedWarningCodes=a,b] [--expectedBlockingCodes=a,b] [--operatorNotes=text]");
  process.exit(1);
}

var manifest = JSON.parse(await readFile(MANIFEST, "utf8"));
var samples = manifest.samples || [];
var sample = samples.find((item) => item.file === file);
if (!sample) {
  console.error("Sample not found in manifest: " + file);
  process.exit(1);
}

var expectedUploadReady = argValue("--expectedUploadReady");
if (expectedUploadReady !== null) sample.expectedUploadReady = expectedUploadReady !== "false";
var acceptedByPlatform = argValue("--acceptedByPlatform");
if (acceptedByPlatform !== null) sample.acceptedByPlatform = acceptedByPlatform;
var sourceType = argValue("--sourceType");
if (sourceType !== null) sample.sourceType = sourceType;
var notes = argValue("--operatorNotes");
if (notes !== null) sample.operatorNotes = notes;
var warningCodes = argList("--expectedWarningCodes");
if (warningCodes.length) sample.expectedWarningCodes = warningCodes;
var blockingCodes = argList("--expectedBlockingCodes");
if (blockingCodes.length) sample.expectedBlockingCodes = blockingCodes;
var falsePositiveCodes = argList("--falsePositiveCodes");
var falseNegativeCodes = argList("--falseNegativeCodes");
if (falsePositiveCodes.length || falseNegativeCodes.length) {
  sample.operatorFeedback = {
    updatedAt: new Date().toISOString(),
    falsePositiveCodes,
    falseNegativeCodes,
  };
}

await writeFile(MANIFEST, JSON.stringify(manifest, null, 2) + "\n");
console.log(JSON.stringify(sample, null, 2));
