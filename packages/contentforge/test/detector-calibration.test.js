import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "fs/promises";
import path from "path";
import {
  buildDetectorVerdicts,
  buildReadinessSummary,
} from "../lib/similarity.js";
import { campaignFactoryThresholds } from "../lib/campaign-factory-audit-config.js";

const FIXTURE_PATH = path.resolve("test/fixtures/detector-calibration/media_pairs.json");
const PDQ_SCRIPT_PATH = path.resolve("lib/pdq_check.py");
const SSCD_SCRIPT_PATH = path.resolve("lib/sscd_check.py");
const TEMPORAL_SCRIPT_PATH = path.resolve("lib/temporal_pdq.py");

async function loadPairs() {
  return JSON.parse(await readFile(FIXTURE_PATH, "utf8"));
}

function rawPdqVerdict(distance) {
  return distance <= 31 ? "match" : "distinct";
}

function rawSscdVerdict(similarity) {
  if (similarity >= 0.75) return "copy";
  if (similarity >= 0.50) return "similar";
  return "distinct";
}

function rawTemporalVerdict(similarity) {
  if (similarity >= 0.90) return "exact_match";
  if (similarity >= 0.70) return "likely_match";
  return "distinct";
}

function campaignResultsForPair(pair) {
  if (pair.detector === "pdq") {
    var distance = pair.measurement.hammingDistance;
    return {
      pdq: {
        results: [{ name: pair.target, distance, safe: distance > 31, error: null }],
        stats: {
          total: 1,
          safeCount: distance > 31 ? 1 : 0,
          avgDistance: distance,
          minDistance: distance,
          maxDistance: distance,
          threshold: 31,
          safeTarget: 40,
          crossCollisions: 0,
          crossSafeTargetViolations: 0,
        },
      },
    };
  }

  if (pair.detector === "sscd") {
    var similarity = pair.measurement.cosineSimilarity;
    return {
      sscd: {
        results: [{ name: pair.target, similarity, verdict: rawSscdVerdict(similarity), error: null }],
        stats: {
          total: 1,
          passCount: similarity < 0.50 ? 1 : 0,
          warnCount: similarity >= 0.50 && similarity < 0.75 ? 1 : 0,
          failCount: similarity >= 0.75 ? 1 : 0,
          avgSimilarity: similarity,
          minSimilarity: similarity,
          maxSimilarity: similarity,
          crossVariantCollisions: 0,
          crossVariantSafeTargetViolations: 0,
          thresholds: { pass: 0.50, warn: 0.75 },
        },
      },
    };
  }

  throw new Error("Unsupported campaign detector: " + pair.detector);
}

test("detector calibration fixture manifest pins known edge media pairs", async function () {
  var manifest = await loadPairs();
  assert.equal(manifest.schema, "contentforge.detector_calibration_pairs.v1");
  assert.equal(manifest.pairs.length >= 8, true);

  for (var pair of manifest.pairs) {
    assert.equal(typeof pair.id, "string");
    assert.match(pair.source, /\.(png|mp4)$/);
    assert.match(pair.target, /\.(png|mp4)$/);
    assert.equal(typeof pair.expected.rawVerdict, "string");
  }
});

test("raw detector thresholds hold at recorded collision and distinct edges", async function () {
  var { pairs } = await loadPairs();

  for (var pair of pairs) {
    var actual;
    if (pair.detector === "pdq") actual = rawPdqVerdict(pair.measurement.hammingDistance);
    if (pair.detector === "sscd") actual = rawSscdVerdict(pair.measurement.cosineSimilarity);
    if (pair.detector === "tmk") actual = rawTemporalVerdict(pair.measurement.temporalSimilarity);
    assert.equal(actual, pair.expected.rawVerdict, pair.id);
  }
});

test("campaign profile keeps PDQ and SSCD stricter than raw copy thresholds", async function () {
  var { pairs } = await loadPairs();
  var thresholds = campaignFactoryThresholds();
  assert.equal(thresholds.pdqSafeDistance, 40);
  assert.equal(thresholds.sscdSafeSimilarity, 0.50);

  for (var pair of pairs.filter((item) => item.detector === "pdq" || item.detector === "sscd")) {
    var results = campaignResultsForPair(pair);
    var verdicts = buildDetectorVerdicts(results, "campaign_factory_v1");
    var summary = buildReadinessSummary(results, verdicts, {
      auditProfile: "campaign_factory_v1",
    });
    var detectorVerdict = verdicts[pair.detector];

    assert.equal(detectorVerdict, pair.expected.campaignVerdict, pair.id + " campaign verdict");
    assert.equal(summary.uploadReady, pair.expected.campaignUploadReady, pair.id + " uploadReady");
    if (!pair.expected.campaignUploadReady) {
      assert.equal(summary.blockingCodes.includes(pair.detector + "_failed"), true, pair.id + " blocking code");
    }
  }
});

test("python detector scripts expose calibrated thresholds without drift", async function () {
  var [pdqSource, sscdSource, temporalSource] = await Promise.all([
    readFile(PDQ_SCRIPT_PATH, "utf8"),
    readFile(SSCD_SCRIPT_PATH, "utf8"),
    readFile(TEMPORAL_SCRIPT_PATH, "utf8"),
  ]);

  assert.match(pdqSource, /safe\s*=\s*dist\s*>\s*31/);
  assert.match(pdqSource, /"threshold":\s*31/);
  assert.match(pdqSource, /"safeTarget":\s*40/);
  assert.match(pdqSource, /d\s*<=\s*31/);
  assert.match(pdqSource, /d\s*<=\s*40/);

  assert.match(sscdSource, /if\s+sim\s*>=\s*0\.75:/);
  assert.match(sscdSource, /elif\s+sim\s*>=\s*0\.50:/);
  assert.match(sscdSource, /"thresholds":\s*\{"pass":\s*0\.50,\s*"warn":\s*0\.75\}/);
  assert.match(sscdSource, /sim\s*>=\s*0\.75/);
  assert.match(sscdSource, /sim\s*>=\s*0\.50/);

  assert.match(temporalSource, /if\s+sim\s*>=\s*0\.90:/);
  assert.match(temporalSource, /elif\s+sim\s*>=\s*0\.70:/);
  assert.match(temporalSource, /"thresholds":\s*\{"filter":\s*0\.70,\s*"exact":\s*0\.90\}/);
});
