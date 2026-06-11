import { NextResponse } from "next/server";
import { readdir, stat, unlink } from "fs/promises";
import { createReadStream, existsSync } from "fs";
import path from "path";
import { execFile } from "child_process";
import crypto from "crypto";
import { Readable } from "stream";
import { OUTPUT_DIR, resolveRunFile, resolveRunFinalDir, safeBasename } from "../../../lib/paths.js";

var SUPPORTED_EXTS = [".mp4", ".mov", ".jpg", ".jpeg", ".png", ".webp", ".gif"];

function getContentType(filename) {
  var ext = path.extname(filename).toLowerCase();
  if (ext === ".mp4") return "video/mp4";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".gif") return "image/gif";
  if (ext === ".webp") return "image/webp";
  return "application/octet-stream";
}

// Single file download
export async function GET(request) {
  var url = new URL(request.url);
  var filename = url.searchParams.get("file");
  var all = url.searchParams.get("all");
  var selectedFiles = url.searchParams.get("files");
  var runId = url.searchParams.get("runId") || "latest";

  if (all === "true") {
    return downloadAll(runId, selectedFiles);
  }

  if (!filename) {
    return new NextResponse("Missing file param", { status: 400 });
  }

  var safeName = safeBasename(filename);
  var filePath = resolveRunFile(runId, safeName);
  if (!safeName || !filePath) {
    return new NextResponse("Invalid file or runId", { status: 400 });
  }

  if (!existsSync(filePath)) {
    return new NextResponse("Not found", { status: 404 });
  }

  var fileStats = await stat(filePath);
  var stream = createReadStream(filePath);

  return new NextResponse(Readable.toWeb(stream), {
    headers: {
      "Content-Type": getContentType(safeName),
      "Content-Disposition": "attachment; filename=\"" + safeName + "\"",
      "Content-Length": String(fileStats.size),
    },
  });
}

async function downloadAll(runId, selectedFiles) {
  var finalDir = resolveRunFinalDir(runId);
  if (!finalDir) {
    return new NextResponse("Invalid runId", { status: 400 });
  }

  if (!existsSync(finalDir)) {
    return new NextResponse("No output files", { status: 404 });
  }

  var allFiles = await readdir(finalDir);
  var selected = selectedFiles
    ? new Set(selectedFiles.split(",").map(function (file) { return safeBasename(file); }).filter(Boolean))
    : null;
  var files = allFiles.filter(function (f) {
    var ext = path.extname(f).toLowerCase();
    return SUPPORTED_EXTS.includes(ext) && (!selected || selected.has(f));
  });

  if (files.length === 0) {
    return new NextResponse("No variants to download", { status: 404 });
  }

  // Create ZIP using system zip command (available on macOS)
  var zipPath = path.join(OUTPUT_DIR, "contentforge_variants_" + crypto.randomBytes(4).toString("hex") + ".zip");

  try {
    await new Promise(function (resolve, reject) {
      execFile("zip", ["-j", zipPath, ...files], { cwd: finalDir }, function (error) {
        if (error) reject(error);
        else resolve();
      });
    });
  } catch (e) {
    return new NextResponse("Failed to create ZIP", { status: 500 });
  }

  var zipStats = await stat(zipPath);
  var stream = createReadStream(zipPath);
  stream.on("close", function () {
    unlink(zipPath).catch(function () {});
  });

  return new NextResponse(Readable.toWeb(stream), {
    headers: {
      "Content-Type": "application/zip",
      "Content-Disposition": "attachment; filename=\"contentforge_variants.zip\"",
      "Content-Length": String(zipStats.size),
    },
  });
}
