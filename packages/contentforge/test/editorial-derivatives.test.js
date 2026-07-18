import test from "node:test";
import assert from "node:assert/strict";
import path from "path";
import { mkdir, readFile, rm, writeFile } from "fs/promises";
import { tmpdir } from "os";
import {
  __setEditorialRuntimeForTests,
  assertEditorialArgs,
  buildKlingEditorialRecipes,
  runKlingEditorialDerivatives,
  verifyRenderedEvidence,
} from "../lib/editorial-derivatives.js";
import { getRunFinalDir } from "../lib/paths.js";

var SOURCE_MEDIA = {
  width: 1080,
  height: 1920,
  fps: 30,
  duration: 10,
  audioCodec: "aac",
};

test("materializes exact frame trims and conservative retiming recipes", function () {
  var recipes = buildKlingEditorialRecipes(SOURCE_MEDIA, 4);

  assert.equal(recipes.length, 4);
  assert.deepEqual(recipes.map((item) => item.familyName), [
    "head_trim",
    "tail_trim",
    "speed_up",
    "slow_down",
  ]);
  assert.deepEqual(recipes[0].operationDetails, {
    type: "trim_head_frames",
    frameCount: 4,
    seconds: 0.133333,
  });
  assert.equal(recipes[0].editOptions.trimStart, 0.133333);
  assert.equal(recipes[1].editOptions.trimDuration, 9.933333);
  assert.equal(recipes[2].editOptions.speed, 1.03);
  assert.equal(recipes[3].editOptions.speed, 0.97);
  assert.equal(new Set(recipes.map((item) => item.outputFilename)).size, 4);
  assert.equal(recipes.every((item) => item.operationSignals.temporalDifferent), true);
  assert.equal(recipes.every((item) => item.blockedOperations.includes("provider_generation")), true);
});

test("defaults to two derivatives and caps a source at four", function () {
  assert.equal(buildKlingEditorialRecipes(SOURCE_MEDIA).length, 2);
  assert.equal(buildKlingEditorialRecipes(SOURCE_MEDIA, 99).length, 4);
});

test("fails closed when source timing evidence is missing or too short", function () {
  assert.throws(
    () => buildKlingEditorialRecipes({ ...SOURCE_MEDIA, fps: 0 }, 1),
    /kling_editorial_source_fps_missing/
  );
  assert.throws(
    () => buildKlingEditorialRecipes({ ...SOURCE_MEDIA, duration: 0 }, 1),
    /kling_editorial_source_duration_missing/
  );
  assert.throws(
    () => buildKlingEditorialRecipes({ ...SOURCE_MEDIA, duration: 0.15 }, 1),
    /kling_editorial_source_too_short_for_head_trim/
  );
});

test("editorial args reject fingerprint-evasion and caption operations", function () {
  for (var operation of [
    "hflip",
    "noise=alls=2",
    "rotate=0.1",
    "hue=h=3",
    "colorbalance=rs=.1",
    "creation_time=2026-01-01",
    "handler_name=Camera",
    "drawtext=text=hook",
  ]) {
    assert.throws(
      () => assertEditorialArgs(["-vf", operation]),
      /kling_editorial_forbidden_ffmpeg_operation/
    );
  }
  assert.equal(assertEditorialArgs(["-vf", "setpts=0.9709*PTS", "-af", "atempo=1.0300"]), true);
});

test("verifies duration, dimensions, and fps against the declared recipe", function () {
  var recipe = buildKlingEditorialRecipes(SOURCE_MEDIA, 1)[0];
  assert.equal(verifyRenderedEvidence({
    recipe,
    sourceMedia: SOURCE_MEDIA,
    outputMedia: {
      width: 1080,
      height: 1920,
      fps: 30,
      duration: recipe.expectedDurationSeconds,
    },
  }), true);
  assert.throws(
    () => verifyRenderedEvidence({
      recipe,
      sourceMedia: SOURCE_MEDIA,
      outputMedia: { width: 1080, height: 1920, fps: 30, duration: 8 },
    }),
    /kling_editorial_duration_mismatch/
  );
  assert.throws(
    () => verifyRenderedEvidence({
      recipe,
      sourceMedia: SOURCE_MEDIA,
      outputMedia: { width: 720, height: 1280, fps: 30, duration: recipe.expectedDurationSeconds },
    }),
    /kling_editorial_dimensions_mismatch/
  );
  assert.throws(
    () => verifyRenderedEvidence({
      recipe,
      sourceMedia: SOURCE_MEDIA,
      outputMedia: { width: 1080, height: 1920, fps: 24, duration: recipe.expectedDurationSeconds },
    }),
    /kling_editorial_fps_mismatch/
  );
});

test("renders exact one-to-one artifacts with hashes, zero provider activity, and captions pending", async function () {
  var fixtureDir = path.join(tmpdir(), "contentforge-editorial-" + process.pid);
  var sourcePath = path.join(fixtureDir, "kling-source.mp4");
  var runId = "ed1a0001";
  var outputDir = getRunFinalDir(runId);
  await rm(fixtureDir, { recursive: true, force: true });
  await rm(path.dirname(outputDir), { recursive: true, force: true });
  await mkdir(fixtureDir, { recursive: true });
  await writeFile(sourcePath, "source-media");
  var executionArgs = [];
  __setEditorialRuntimeForTests({
    runIdFactory: () => runId,
    executor: async (args) => {
      executionArgs.push(args);
      await writeFile(args.at(-1), "rendered-" + executionArgs.length);
    },
    probe: async (filePath) => {
      if (filePath === sourcePath) return SOURCE_MEDIA;
      var filename = path.basename(filePath);
      var recipe = buildKlingEditorialRecipes(SOURCE_MEDIA, 2)
        .find((item) => item.outputFilename === filename);
      return {
        ...SOURCE_MEDIA,
        duration: recipe.expectedDurationSeconds,
      };
    },
  });
  try {
    var result = await runKlingEditorialDerivatives({
      sourcePath,
      sourceClientPath: "uploads/kling-source.mp4",
      variantCount: 2,
      sourceCaptionState: "uncaptioned_verified",
      sourceCaptionEvidence: "higgsfield_raw_generation_manifest:gen_123",
    });

    assert.equal(result.renderedArtifacts.length, 2);
    assert.equal(executionArgs.length, 2);
    assert.equal(result.providerActivity.providerCalls, 0);
    assert.equal(result.providerActivity.paidGenerationCalls, 0);
    assert.equal(result.captionStatus.status, "pending_reel_factory");
    assert.equal(result.captionStatus.burnedByThisStage, false);
    assert.equal(result.captionStatus.burnedIntoMedia, false);
    assert.equal(result.renderedArtifacts.every((item) => item.sourceSha256.length === 64), true);
    assert.equal(result.renderedArtifacts.every((item) => item.outputSha256.length === 64), true);
    assert.equal(new Set(result.renderedArtifacts.map((item) => item.outputSha256)).size, 2);
    assert.equal(
      result.renderedArtifacts.every((item) => item.ffmpegArgs.at(-1) === item.filePath),
      true
    );
    assert.equal(executionArgs.every((args) => args.join(" ").includes("hflip") === false), true);
    var state = JSON.parse(await readFile(path.join(outputDir, "run_config.json"), "utf8"));
    assert.equal(state.status, "completed");
    assert.equal(state.completedArtifacts.length, 2);
    assert.equal(state.providerActivity.providerCalls, 0);
  } finally {
    __setEditorialRuntimeForTests();
    await rm(fixtureDir, { recursive: true, force: true });
    await rm(path.dirname(outputDir), { recursive: true, force: true });
  }
});

test("requires explicit evidence that the source is uncaptioned", async function () {
  var fixtureDir = path.join(tmpdir(), "contentforge-editorial-caption-evidence-" + process.pid);
  var sourcePath = path.join(fixtureDir, "source.mp4");
  await mkdir(fixtureDir, { recursive: true });
  await writeFile(sourcePath, "source-media");
  try {
    await assert.rejects(
      () => runKlingEditorialDerivatives({
        sourcePath,
        variantCount: 1,
      }),
      /kling_editorial_uncaptioned_source_evidence_missing/
    );
  } finally {
    await rm(fixtureDir, { recursive: true, force: true });
  }
});

test("rejects duplicate output fingerprints and removes the untrusted collision", async function () {
  var fixtureDir = path.join(tmpdir(), "contentforge-editorial-duplicate-" + process.pid);
  var sourcePath = path.join(fixtureDir, "source.mp4");
  var runId = "ed1a0003";
  var outputDir = getRunFinalDir(runId);
  await rm(fixtureDir, { recursive: true, force: true });
  await rm(path.dirname(outputDir), { recursive: true, force: true });
  await mkdir(fixtureDir, { recursive: true });
  await writeFile(sourcePath, "source-media");
  __setEditorialRuntimeForTests({
    runIdFactory: () => runId,
    executor: async (args) => {
      await writeFile(args.at(-1), "same-rendered-output");
    },
    probe: async (filePath) => {
      if (filePath === sourcePath) return SOURCE_MEDIA;
      var recipe = buildKlingEditorialRecipes(SOURCE_MEDIA, 2)
        .find((item) => item.outputFilename === path.basename(filePath));
      return {
        ...SOURCE_MEDIA,
        duration: recipe.expectedDurationSeconds,
      };
    },
  });
  try {
    await assert.rejects(
      () => runKlingEditorialDerivatives({
        sourcePath,
        variantCount: 2,
        sourceCaptionState: "uncaptioned_verified",
        sourceCaptionEvidence: "test-fixture",
      }),
      /kling_editorial_duplicate_output_fingerprint/
    );
    var state = JSON.parse(await readFile(path.join(outputDir, "run_config.json"), "utf8"));
    assert.equal(state.status, "failed");
    assert.equal(state.completedArtifacts.length, 1);
    assert.equal(
      await readFile(state.completedArtifacts[0].filePath, "utf8"),
      "same-rendered-output"
    );
    await assert.rejects(
      () => readFile(path.join(outputDir, "kling_editorial_02_trim_tail_2_frames.mp4")),
      /ENOENT/
    );
  } finally {
    __setEditorialRuntimeForTests();
    await rm(fixtureDir, { recursive: true, force: true });
    await rm(path.dirname(outputDir), { recursive: true, force: true });
  }
});

test("interrupted execution leaves an honest recoverable run state", async function () {
  var fixtureDir = path.join(tmpdir(), "contentforge-editorial-interrupt-" + process.pid);
  var sourcePath = path.join(fixtureDir, "source.mp4");
  var runId = "ed1a0002";
  var outputDir = getRunFinalDir(runId);
  await rm(fixtureDir, { recursive: true, force: true });
  await rm(path.dirname(outputDir), { recursive: true, force: true });
  await mkdir(fixtureDir, { recursive: true });
  await writeFile(sourcePath, "source-media");
  var controller = new globalThis.AbortController();
  __setEditorialRuntimeForTests({
    runIdFactory: () => runId,
    executor: async (args) => {
      await writeFile(args.at(-1), "completed-first-output");
      controller.abort();
    },
    probe: async (filePath) => {
      if (filePath === sourcePath) return SOURCE_MEDIA;
      return {
        ...SOURCE_MEDIA,
        duration: buildKlingEditorialRecipes(SOURCE_MEDIA, 2)[0].expectedDurationSeconds,
      };
    },
  });
  try {
    await assert.rejects(
      () => runKlingEditorialDerivatives({
        sourcePath,
        variantCount: 2,
        sourceCaptionState: "uncaptioned_verified",
        sourceCaptionEvidence: "test-fixture",
        signal: controller.signal,
      }),
      /kling_editorial_aborted/
    );
    var state = JSON.parse(await readFile(path.join(outputDir, "run_config.json"), "utf8"));
    assert.equal(state.status, "interrupted");
    assert.equal(state.retryOrResumeSafe, true);
    assert.equal(state.completedArtifacts.length, 1);
    assert.equal(state.error, "kling_editorial_aborted");
  } finally {
    __setEditorialRuntimeForTests();
    await rm(fixtureDir, { recursive: true, force: true });
    await rm(path.dirname(outputDir), { recursive: true, force: true });
  }
});
