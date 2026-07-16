import { execFile } from "child_process";

function runTool(command, args, options = {}) {
  return new Promise(function (resolve) {
    execFile(command, args, {
      timeout: options.timeout || 20000,
      maxBuffer: options.maxBuffer || 2 * 1024 * 1024,
      encoding: options.encoding,
    }, function (error, stdout, stderr) {
      resolve({ error, stdout: stdout || Buffer.alloc(0), stderr: stderr || "" });
    });
  });
}

export function hammingDistance(a, b) {
  if (!a || !b || a.length !== b.length) return a && b ? Math.max(a.length, b.length) : 256;
  var dist = 0;
  for (var i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) dist++;
  }
  return dist;
}

export function bucketSimilarity(similarity, exactMatch, threshold = 0.92) {
  if (exactMatch || similarity >= threshold) return "duplicate";
  if (similarity >= Math.max(0, threshold - 0.12)) return "similar";
  return "unique";
}

var SAMPLE_POINTS = [0.05, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90];

async function probeDuration(filePath) {
  var result = await runTool("ffprobe", [
    "-v", "quiet",
    "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1",
    filePath,
  ], { timeout: 10000, maxBuffer: 1024 * 1024, encoding: "utf8" });
  if (result.error) return 0;
  return parseFloat(result.stdout) || 0;
}

async function frameHashAt(filePath, seconds, isVideo) {
  var args = [
    "-hide_banner",
  ];
  if (isVideo) args.push("-ss", String(Math.max(0, seconds || 0)));
  args.push(
    "-i", filePath,
    "-vframes", "1",
    "-vf", "scale=32:32,format=gray",
    "-f", "rawvideo",
    "-",
  );
  var result = await runTool("ffmpeg", args, { timeout: 15000, maxBuffer: 1024 * 1024, encoding: "buffer" });

  if (result.error || !result.stdout || result.stdout.length === 0) return null;
  var buffer = Buffer.isBuffer(result.stdout) ? result.stdout : Buffer.from(result.stdout, "binary");
  var total = 0;
  for (var byte of buffer) total += byte;
  var avg = total / buffer.length;
  var bits = "";
  for (var pixel of buffer) bits += pixel >= avg ? "1" : "0";
  return bits;
}

export function averageHashSimilarity(a = [], b = []) {
  var count = Math.min(a.length, b.length);
  if (!count) return 0;
  var total = 0;
  for (var i = 0; i < count; i++) {
    total += 1 - (hammingDistance(a[i], b[i]) / Math.max(a[i].length, 1));
  }
  return total / count;
}

export function temporalHashSimilarity(a = [], b = []) {
  var count = Math.min(a.length, b.length);
  if (!count) return 0;
  var best = 0;
  var maxOffset = Math.max(1, Math.ceil(count * 0.08));
  for (var offset = -maxOffset; offset <= maxOffset; offset++) {
    var total = 0;
    var matched = 0;
    for (var i = 0; i < count; i++) {
      var j = i + offset;
      if (j < 0 || j >= b.length) continue;
      total += 1 - (hammingDistance(a[i], b[j]) / Math.max(a[i].length, 1));
      matched++;
    }
    if (matched) best = Math.max(best, total / matched);
  }
  return best;
}

export async function multiFrameHash(filePath, isVideo) {
  if (!isVideo) {
    var still = await frameHashAt(filePath, 0, false);
    return still ? [still] : [];
  }
  var duration = await probeDuration(filePath);
  var hashes = [];
  for (var point of SAMPLE_POINTS) {
    var hash = await frameHashAt(filePath, duration ? duration * point : 1, true);
    if (hash) hashes.push(hash);
  }
  return hashes;
}
