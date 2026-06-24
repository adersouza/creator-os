import { execFile, execFileSync } from "child_process";
import { mkdir, readFile, rm } from "fs/promises";
import path from "path";

var base = process.env.CONTENTFORGE_URL || "http://localhost:3002";
var tmpDir = "/tmp/contentforge-e2e";
var cleanupTargets = [];

function run(command, args) {
  return new Promise(function (resolve, reject) {
    execFile(command, args, { timeout: 60000, maxBuffer: 4 * 1024 * 1024 }, function (error, stdout, stderr) {
      if (error) reject(new Error((stderr || error.message).slice(-2000)));
      else resolve(stdout || "");
    });
  });
}

async function upload(filePath, name, type) {
  var buffer = await readFile(filePath);
  var formData = new FormData();
  formData.append("file", new File([buffer], name, { type }));
  var response = await fetch(base + "/api/upload", { method: "POST", body: formData });
  if (!response.ok) throw new Error("upload failed " + response.status + ": " + await response.text());
  return response.json();
}

async function postJson(route, body) {
  var response = await fetch(base + route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(route + " failed " + response.status + ": " + await response.text());
  return response.json();
}

async function forge(body) {
  var response = await fetch(base + "/api/forge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error("forge failed " + response.status + ": " + await response.text());

  var reader = response.body.getReader();
  var decoder = new TextDecoder();
  var buffer = "";
  var complete = null;
  var errors = [];

  while (true) {
    var chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    var events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (var event of events) {
      if (!event.startsWith("data: ")) continue;
      var data = JSON.parse(event.slice(6));
      if (data.type === "error") errors.push(data.message);
      if (data.type === "complete") complete = data;
    }
  }

  if (!complete) throw new Error("forge did not emit complete event: " + errors.join("; "));
  return { complete, errors };
}

async function main() {
  await mkdir(tmpDir, { recursive: true });
  var sourcePath = path.join(tmpDir, "source-small.mp4");
  var audioPath = path.join(tmpDir, "replacement.wav");

  await run("ffmpeg", [
    "-hide_banner", "-loglevel", "error",
    "-f", "lavfi", "-i", "testsrc2=size=540x960:rate=30",
    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
    "-t", "2",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
    "-y", sourcePath,
  ]);
  await run("ffmpeg", [
    "-hide_banner", "-loglevel", "error",
    "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000",
    "-t", "2", "-c:a", "pcm_s16le", "-y", audioPath,
  ]);

  var source = await upload(sourcePath, "source-small.mp4", "video/mp4");
  var audio = await upload(audioPath, "replacement.wav", "audio/wav");
  cleanupTargets.push(source.path, audio.path);
  var forged = await forge({
    inputFile: source.path,
    numEdits: 1,
    spinsPerEdit: 1,
    variantPreset: "quality",
    variantOptions: { overlayText: "E2E CHECK", overlayPosition: "top", overlayFontSize: 44, overlayOpacity: 0.9 },
    qualityGate: { enabled: false },
    vertical: true,
    outputProfile: "organic",
  });

  var runId = forged.complete.runId;
  cleanupTargets.push("output/runs/" + runId);
  var analyze = await postJson("/api/reels/analyze", { runId, profileId: "organic", sourceFile: source.path });
  if (!analyze.variantReports?.length) throw new Error("analyze returned no variant reports");
  var file = analyze.variantReports[0].file;

  var detector = await postJson("/api/detector", { runId, threshold: 0.92, sourceFile: source.path });
  var cover = await postJson("/api/reels/cover", { runId, filename: file, timestamp: 1 });
  var edit = await postJson("/api/tools/edit", {
    inputFile: source.path,
    replacementAudioFile: audio.path,
    overlayText: "EDITOR CHECK",
    overlayPosition: "bottom",
    trimDuration: 1,
    normalizeAudio: true,
  });
  var gif = await postJson("/api/tools/gif", { inputFile: source.path, mode: "gif", fps: 8, width: 320 });
  cleanupTargets.push("output/runs/" + edit.runId, "output/runs/" + gif.runId);
  var zip = await fetch(base + "/api/download?runId=" + encodeURIComponent(runId) + "&all=true&files=" + encodeURIComponent(file));
  if (!zip.ok) throw new Error("selected zip failed " + zip.status + ": " + await zip.text());

  var probe = JSON.parse(execFileSync("sh", ["-lc", "ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_type,codec_name,width,height -of json output/runs/" + runId + "/final/*.mp4"], { encoding: "utf8" }));
  var video = probe.streams.find(function (stream) { return stream.codec_type === "video"; });
  var audioStream = probe.streams.find(function (stream) { return stream.codec_type === "audio"; });
  if (!video || video.width !== 1080 || video.height !== 1920 || video.codec_name !== "h264") throw new Error("unexpected video probe output");
  if (!audioStream || audioStream.codec_name !== "aac") throw new Error("unexpected audio probe output");

  console.log(JSON.stringify({
    ok: true,
    runId,
    readinessScore: analyze.score,
    detectorRows: detector.files?.length || 0,
    cover: cover.name,
    editRun: edit.runId,
    gifRun: gif.runId,
    selectedZipBytes: (await zip.arrayBuffer()).byteLength,
  }, null, 2));
}

main()
  .catch(function (error) {
    console.error(error.stack || error.message);
    process.exitCode = 1;
  })
  .finally(function () {
    if (process.env.CONTENTFORGE_KEEP_E2E === "1") return;
    var root = process.cwd();
    Promise.all([
      rm(tmpDir, { recursive: true, force: true }),
      ...cleanupTargets.map(function (target) {
        return rm(path.join(root, target), { recursive: true, force: true });
      }),
    ]).catch(function () {});
  });
