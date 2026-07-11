import { applyLocalMediaCleanup, inspectLocalMediaCleanup } from "../lib/local-media-cleanup.js";

function argValue(name, fallback) {
  var prefix = name + "=";
  var match = process.argv.find(function (arg) { return arg.startsWith(prefix); });
  return match ? match.slice(prefix.length) : fallback;
}

var options = {
  olderThanDays: Number.parseFloat(argValue("--older-than-days", "14")),
  maxBytes: Number.parseFloat(argValue("--max-bytes", "0")),
};
var apply = process.argv.includes("--yes");
var report = apply
  ? await applyLocalMediaCleanup(options)
  : await inspectLocalMediaCleanup(options);

console.log(JSON.stringify(report, null, 2));
