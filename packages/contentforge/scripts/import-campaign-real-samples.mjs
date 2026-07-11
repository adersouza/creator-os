import { copyFile, mkdir, readdir, readFile, writeFile } from "fs/promises";
import path from "path";

const DEST = path.resolve("test/fixtures/campaign-factory/real");
const MANIFEST = path.resolve("test/fixtures/campaign-factory/manifests/real_samples.json");
const SOURCE_TYPES = new Set(["iphone", "android", "campaign_factory", "third_party_editor", "unknown"]);
const PLATFORM_RESULTS = new Set(["unknown", "yes", "no"]);

function sampleName(sourcePath, index) {
  var ext = path.extname(sourcePath).toLowerCase() || ".mp4";
  return "real_sample_" + String(index + 1).padStart(2, "0") + ext;
}

function optionValue(args, name, fallback) {
  var prefix = name + "=";
  var match = args.find((arg) => arg.startsWith(prefix));
  if (!match) return fallback;
  return match.slice(prefix.length);
}

function optionList(args, name) {
  var value = optionValue(args, name, "");
  return value ? value.split(",").map((item) => item.trim()).filter(Boolean) : [];
}

async function readManifest() {
  try {
    return JSON.parse(await readFile(MANIFEST, "utf8"));
  } catch {
    return {
      schema: "contentforge.campaign_factory_real_samples.v1",
      samples: [],
    };
  }
}

async function writeManifest(manifest) {
  await mkdir(path.dirname(MANIFEST), { recursive: true });
  await writeFile(MANIFEST, JSON.stringify(manifest, null, 2) + "\n");
}

async function importSamples(paths, options) {
  await mkdir(DEST, { recursive: true });
  var manifest = await readManifest();
  var byFile = new Map((manifest.samples || []).map((sample) => [sample.file, sample]));
  var existingFiles = await readdir(DEST).catch(function () { return []; });
  var usedIndexes = new Set([...byFile.keys(), ...existingFiles].map(function (file) {
    var match = file.match(/^real_sample_(\d+)/);
    return match ? Number.parseInt(match[1], 10) : null;
  }).filter(Number.isFinite));
  var nextIndex = 1;
  var copied = [];
  for (var i = 0; i < paths.length; i++) {
    var source = path.resolve(paths[i]);
    while (usedIndexes.has(nextIndex)) nextIndex++;
    var dest = path.join(DEST, sampleName(source, nextIndex - 1));
    usedIndexes.add(nextIndex);
    await copyFile(source, dest);
    var file = path.basename(dest);
    byFile.set(file, {
      file,
      sourceType: options.sourceType,
      expectedUploadReady: options.expectedUploadReady,
      expectedWarningCodes: options.expectedWarningCodes,
      expectedBlockingCodes: options.expectedBlockingCodes,
      operatorNotes: options.operatorNotes,
      acceptedByPlatform: options.acceptedByPlatform,
    });
    copied.push(dest);
  }
  manifest.samples = [...byFile.values()].sort((a, b) => a.file.localeCompare(b.file));
  await writeManifest(manifest);
  return copied;
}

var args = process.argv.slice(2);
var inputs = args.filter((arg) => !arg.startsWith("--"));
if (inputs.length === 0) {
  console.error("Usage: npm run fixtures:campaign-factory:real -- [--sourceType=iphone|android|campaign_factory|third_party_editor|unknown] [--expectedUploadReady=true|false] [--expectedWarningCodes=a,b] [--expectedBlockingCodes=a,b] [--acceptedByPlatform=unknown|yes|no] [--operatorNotes=text] /path/to/sample.mp4");
  process.exit(1);
}

var sourceType = optionValue(args, "--sourceType", "unknown");
var acceptedByPlatform = optionValue(args, "--acceptedByPlatform", "unknown");
var expectedUploadReady = optionValue(args, "--expectedUploadReady", "true") !== "false";
if (!SOURCE_TYPES.has(sourceType)) {
  console.error("Invalid --sourceType: " + sourceType);
  process.exit(1);
}
if (!PLATFORM_RESULTS.has(acceptedByPlatform)) {
  console.error("Invalid --acceptedByPlatform: " + acceptedByPlatform);
  process.exit(1);
}

importSamples(inputs, {
  sourceType,
  expectedUploadReady,
  expectedWarningCodes: optionList(args, "--expectedWarningCodes"),
  expectedBlockingCodes: optionList(args, "--expectedBlockingCodes"),
  operatorNotes: optionValue(args, "--operatorNotes", ""),
  acceptedByPlatform,
})
  .then((copied) => {
    console.log("Imported local real samples:");
    for (var file of copied) console.log(" - " + file);
    console.log("Updated manifest: " + MANIFEST);
  })
  .catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
