export function parseSrtTime(value) {
  var match = String(value || "").trim().match(/^(\d{2}):(\d{2}):(\d{2}),(\d{3})$/);
  if (!match) return null;
  return (parseInt(match[1], 10) * 3600) +
    (parseInt(match[2], 10) * 60) +
    parseInt(match[3], 10) +
    (parseInt(match[4], 10) / 1000);
}

export function parseSrt(text) {
  var blocks = String(text || "").replace(/\r/g, "").split(/\n{2,}/);
  var cues = [];
  for (var block of blocks) {
    var lines = block.split("\n").map(function (line) { return line.trim(); }).filter(Boolean);
    if (lines.length < 2) continue;
    var timingIndex = lines.findIndex(function (line) { return line.includes("-->"); });
    if (timingIndex < 0) continue;
    var parts = lines[timingIndex].split("-->").map(function (part) { return part.trim(); });
    var start = parseSrtTime(parts[0]);
    var end = parseSrtTime(parts[1]);
    if (start === null || end === null || end <= start) continue;
    cues.push({
      index: parseInt(lines[0], 10) || cues.length + 1,
      start,
      end,
      duration: end - start,
      text: lines.slice(timingIndex + 1).join(" "),
      lines: lines.slice(timingIndex + 1),
    });
  }
  return cues;
}

export function analyzeCaptions(text, mediaInfo = {}) {
  if (!text) {
    return {
      available: false,
      cues: [],
      checks: [
        { id: "captionFile", label: "Caption file", status: "warn", actual: "missing", expected: ".srt", message: "Optional SRT not attached" },
      ],
      summary: { cues: 0, warnings: 1, failures: 0 },
    };
  }

  var cues = parseSrt(text);
  var checks = [];
  checks.push({
    id: "captionFile",
    label: "Caption file",
    status: cues.length > 0 ? "pass" : "fail",
    actual: cues.length + " cues",
    expected: "valid SRT",
    message: cues.length > 0 ? "SRT parsed successfully" : "No valid caption cues found",
  });

  var longLines = cues.filter(function (cue) {
    return cue.lines.some(function (line) { return line.length > 42; });
  });
  checks.push({
    id: "captionLineLength",
    label: "Line length",
    status: longLines.length === 0 ? "pass" : "warn",
    actual: longLines.length + " long",
    expected: "42 chars or less",
    message: longLines.length === 0 ? "Caption lines are compact" : "Some caption lines may wrap heavily",
  });

  var denseCues = cues.filter(function (cue) {
    var words = cue.text.split(/\s+/).filter(Boolean).length;
    return cue.duration > 0 && words / cue.duration > 4;
  });
  checks.push({
    id: "captionDensity",
    label: "Timing density",
    status: denseCues.length === 0 ? "pass" : "warn",
    actual: denseCues.length + " dense",
    expected: "readable pace",
    message: denseCues.length === 0 ? "Caption timing is readable" : "Some cues move too quickly",
  });

  var duration = mediaInfo.duration || 0;
  var overrun = duration > 0 && cues.some(function (cue) { return cue.end > duration + 0.25; });
  checks.push({
    id: "captionDuration",
    label: "Timing bounds",
    status: overrun ? "fail" : "pass",
    actual: duration ? duration.toFixed(1) + "s media" : "unknown media",
    expected: "captions inside media",
    message: overrun ? "Caption timing extends past video duration" : "Caption timing fits media",
  });

  checks.push({
    id: "captionSafeZone",
    label: "Bottom safe zone",
    status: "warn",
    actual: "manual review",
    expected: "clear lower UI area",
    message: "Preview captions against the phone safe-zone overlay",
  });

  return {
    available: true,
    cues,
    checks,
    summary: {
      cues: cues.length,
      warnings: checks.filter(function (c) { return c.status === "warn"; }).length,
      failures: checks.filter(function (c) { return c.status === "fail"; }).length,
    },
  };
}
