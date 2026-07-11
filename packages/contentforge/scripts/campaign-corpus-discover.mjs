import { execFile } from "child_process";
import { readdir, stat } from "fs/promises";
import path from "path";

const VIDEO_EXTS = new Set([".mp4", ".mov", ".m4v", ".webm"]);

function argValue(name, fallback) {
  var prefix = name + "=";
  var match = process.argv.slice(2).find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : fallback;
}

async function walk(dir, maxDepth, depth = 0) {
  var entries = [];
  if (depth > maxDepth) return entries;
  var names = await readdir(dir).catch(function () { return []; });
  for (var name of names) {
    var fullPath = path.join(dir, name);
    var info = await stat(fullPath).catch(function () { return null; });
    if (!info) continue;
    if (info.isDirectory()) {
      entries.push(...await walk(fullPath, maxDepth, depth + 1));
      continue;
    }
    if (info.isFile() && VIDEO_EXTS.has(path.extname(name).toLowerCase())) {
      entries.push({ path: fullPath, sizeBytes: info.size });
    }
  }
  return entries;
}

function probe(file) {
  return new Promise((resolve) => {
    execFile("ffprobe", [
      "-v", "error",
      "-show_entries", "format=duration,format_name:format_tags=encoder,major_brand,creation_time:stream=codec_type,codec_name,width,height:stream_tags=handler_name,creation_time",
      "-of", "json",
      file.path,
    ], { timeout: 15000, maxBuffer: 1024 * 1024 }, (error, stdout) => {
      if (error) {
        resolve({ ...file, readable: false, error: error.message });
        return;
      }
      try {
        var data = JSON.parse(stdout);
        var video = (data.streams || []).find((stream) => stream.codec_type === "video") || {};
        var audio = (data.streams || []).find((stream) => stream.codec_type === "audio") || {};
        var width = video.width || 0;
        var height = video.height || 0;
        var aspect = height ? width / height : 0;
        var uploadReadyShape = width >= 720 && height >= 1280 && Math.abs(aspect - (9 / 16)) <= 0.12;
        var uploadReadyCodec = video.codec_name === "h264";
        var sourceType = /lavf|lavc|ffmpeg|x264/i.test(data.format?.tags?.encoder || "")
          ? "third_party_editor"
          : "unknown";
        resolve({
          ...file,
          readable: true,
          durationSec: Number.parseFloat(data.format?.duration || "0"),
          formatName: data.format?.format_name || "",
          width,
          height,
          videoCodec: video.codec_name || null,
          audioCodec: audio.codec_name || null,
          encoder: data.format?.tags?.encoder || null,
          handlerName: video.tags?.handler_name || null,
          suggested: {
            sourceType,
            expectedUploadReady: Boolean(uploadReadyShape && uploadReadyCodec),
            expectedBlockingCodes: uploadReadyShape ? [] : ["forensics_bad_dimensions"],
            expectedWarningCodes: [],
          },
        });
      } catch (parseError) {
        resolve({ ...file, readable: false, error: parseError.message });
      }
    });
  });
}

var root = path.resolve(argValue("--dir", path.join(process.env.HOME || process.cwd(), "Downloads")));
var maxDepth = Number.parseInt(argValue("--maxDepth", "2"), 10);
var limit = Number.parseInt(argValue("--limit", "50"), 10);
var files = (await walk(root, maxDepth)).slice(0, limit);
var results = [];
for (var file of files) {
  results.push(await probe(file));
}

console.log(JSON.stringify({
  schema: "contentforge.campaign_factory_corpus_discovery.v1",
  root,
  count: results.length,
  candidates: results,
}, null, 2));
