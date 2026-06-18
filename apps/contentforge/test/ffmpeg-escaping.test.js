import test from "node:test";
import assert from "node:assert/strict";
import { escapeDrawtext as escapePipelineDrawtext } from "../lib/ffmpeg.js";
import { escapeDrawtext as escapeMediaToolDrawtext } from "../lib/media-tools.js";

var RAW = "one,two; 90% 'quoted' [tag]: C:\\tmp\\file\nnext";
var EXPECTED = "one\\,two\\; 90\\% \\'quoted\\' \\[tag\\]\\: C\\:\\\\tmp\\\\file\\nnext";

test("pipeline drawtext escaping covers filter separators and expansion characters", function () {
  assert.equal(escapePipelineDrawtext(RAW), EXPECTED);
});

test("media-tools drawtext escaping matches pipeline escaping", function () {
  assert.equal(escapeMediaToolDrawtext(RAW), EXPECTED);
});
