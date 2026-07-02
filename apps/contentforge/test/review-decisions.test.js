import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { GET as reviewGet, POST as reviewPost } from "../app/api/review-decisions/route.js";
import { recordReviewDecision } from "../lib/review-decisions.js";
import { RUNS_DIR } from "../lib/paths.js";

function runPaths(runId) {
  var root = path.join(RUNS_DIR, runId);
  return {
    root,
    finalDir: path.join(root, "final"),
  };
}

async function seedRun(runId, files, variantResults = []) {
  var paths = runPaths(runId);
  await rm(paths.root, { recursive: true, force: true });
  await mkdir(paths.finalDir, { recursive: true });
  for (var file of files) {
    await writeFile(path.join(paths.finalDir, file), "variant");
  }
  await writeFile(path.join(paths.finalDir, "variant_pack.json"), JSON.stringify({
    schema: "contentforge.variant_pack.v2",
    runId,
    results: variantResults,
  }, null, 2));
  return paths;
}

function jsonRequest(body) {
  return new Request("http://localhost/api/review-decisions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

test("review decisions persist approvals and emit approved manifest", async function () {
  var runId = "a11ce001";
  var paths = await seedRun(runId, ["ready.mp4", "review.mp4"], [
    { file: "ready.mp4", recommended: true, operatorState: "ready", recommendationReason: "clean" },
    { file: "review.mp4", recommended: false, operatorState: "review", recommendationReason: "needs_human" },
  ]);
  try {
    var first = await recordReviewDecision({ runId, file: "ready.mp4", decision: "approved" });
    assert.equal(first.record.overrideOfRecommendation, false);
    assert.equal(first.approvedManifest.approvedCount, 1);

    var second = await recordReviewDecision({ runId, file: "review.mp4", decision: "approved", chosen: true });
    assert.equal(second.record.overrideOfRecommendation, true);
    assert.equal(second.approvedManifest.approvedCount, 2);
    assert.equal(second.approvedManifest.chosenFile, "review.mp4");

    var manifest = JSON.parse(await readFile(path.join(paths.finalDir, "approved_variants_manifest.json"), "utf8"));
    assert.equal(manifest.schema, "contentforge.approved_variants_manifest.v1");
    assert.deepEqual(manifest.variants.map((item) => item.file), ["review.mp4", "ready.mp4"]);
    assert.equal(manifest.variants[0].chosen, true);
    assert.equal(manifest.variants[0].overrideOfRecommendation, true);
  } finally {
    await rm(paths.root, { recursive: true, force: true });
  }
});

test("review decisions remove rejected variants from approved manifest", async function () {
  var runId = "a11ce002";
  var paths = await seedRun(runId, ["candidate.mp4"], [
    { file: "candidate.mp4", recommended: true, operatorState: "ready" },
  ]);
  try {
    await recordReviewDecision({ runId, file: "candidate.mp4", decision: "approved", chosen: true });
    var rejected = await recordReviewDecision({ runId, file: "candidate.mp4", decision: "rejected" });
    assert.equal(rejected.record.overrideOfRecommendation, true);
    assert.equal(rejected.approvedManifest.approvedCount, 0);
    assert.equal(rejected.approvedManifest.chosenFile, null);
  } finally {
    await rm(paths.root, { recursive: true, force: true });
  }
});

test("review decisions reject missing targets", async function () {
  var runId = "a11ce003";
  var paths = await seedRun(runId, ["candidate.mp4"]);
  try {
    await assert.rejects(
      () => recordReviewDecision({ runId, file: "../missing.mp4", decision: "approved" }),
      /Review target not found|Missing file/
    );
    await assert.rejects(
      () => recordReviewDecision({ runId, file: "missing.mp4", decision: "approved" }),
      /Review target not found/
    );
  } finally {
    await rm(paths.root, { recursive: true, force: true });
  }
});

test("review decision API records decisions and returns approved manifest", async function () {
  var runId = "a11ce004";
  var paths = await seedRun(runId, ["candidate.mp4"], [
    { file: "candidate.mp4", recommended: true, operatorState: "ready" },
  ]);
  try {
    var postResponse = await reviewPost(jsonRequest({
      runId,
      file: "candidate.mp4",
      decision: "approved",
      chosen: true,
    }));
    var postBody = await postResponse.json();
    assert.equal(postResponse.status, 200);
    assert.equal(postBody.record.chosen, true);

    var getResponse = await reviewGet(new Request("http://localhost/api/review-decisions?runId=" + runId + "&format=approved-manifest"));
    var getBody = await getResponse.json();
    assert.equal(getResponse.status, 200);
    assert.equal(getBody.approvedCount, 1);
    assert.equal(getBody.chosenFile, "candidate.mp4");
  } finally {
    await rm(paths.root, { recursive: true, force: true });
  }
});

