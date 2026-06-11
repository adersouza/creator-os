import { NextResponse } from "next/server";
import { execFile } from "child_process";
import { writeFile, mkdir } from "fs/promises";
import path from "path";
import crypto from "crypto";
import { LEGACY_FINAL_DIR, REFERENCE_DIR, resolveAllowedReferenceTarget } from "../../../lib/paths.js";
import { getPythonCommand } from "../../../lib/python-runtime.js";

var MAX_REFERENCE_FILES = 100;
var MAX_REFERENCE_FILE_SIZE = 100 * 1024 * 1024;
var REFERENCE_TYPES = ["image/jpeg", "image/png", "image/webp", "video/mp4", "video/quicktime", "video/webm"];

function runReferenceDB(command, target, maxFiles) {
  return new Promise((resolve) => {
    var args = [path.join(process.cwd(), "lib", "reference_db.py"), command];
    if (target) args.push(target);
    if (maxFiles) args.push(String(maxFiles));

    execFile(getPythonCommand(), args, {
      timeout: 180000,
      maxBuffer: 10 * 1024 * 1024,
    }, (err, stdout) => {
      if (err) {
        resolve({ error: err.message });
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch {
        resolve({ error: "Failed to parse output" });
      }
    });
  });
}

// GET — stats or query output dir
export async function GET(request) {
  var url = new URL(request.url);
  var action = url.searchParams.get("action") || "stats";

  if (action === "stats") {
    var result = await runReferenceDB("stats");
    return NextResponse.json(result);
  }

  if (action === "query") {
    var result = await runReferenceDB("query", LEGACY_FINAL_DIR, 50);
    return NextResponse.json(result);
  }

  return NextResponse.json({ error: "Unknown action" }, { status: 400 });
}

// POST — add files to reference index or upload reference images
export async function POST(request) {
  var contentType = request.headers.get("content-type") || "";

  // JSON body — add from directory path
  if (contentType.includes("application/json")) {
    var body = await request.json();
    var action = body.action || "add";

    if (action === "add") {
      var dir = resolveAllowedReferenceTarget(body.directory);
      if (!dir) {
        return NextResponse.json({ error: "Directory must be inside uploads/ or output/" }, { status: 400 });
      }
      var result = await runReferenceDB("add", dir, Math.min(parseInt(body.maxFiles || 500, 10), 500));
      return NextResponse.json(result);
    }

    if (action === "clear") {
      var result = await runReferenceDB("clear");
      return NextResponse.json(result);
    }

    if (action === "query") {
      var dir = resolveAllowedReferenceTarget(body.directory);
      if (!dir) {
        return NextResponse.json({ error: "Directory must be inside uploads/ or output/" }, { status: 400 });
      }
      var result = await runReferenceDB("query", dir, Math.min(parseInt(body.maxFiles || 50, 10), 50));
      return NextResponse.json(result);
    }

    return NextResponse.json({ error: "Unknown action" }, { status: 400 });
  }

  // FormData — upload reference images
  var formData = await request.formData();
  var files = formData.getAll("files");

  if (!files || files.length === 0) {
    return NextResponse.json({ error: "No files uploaded" }, { status: 400 });
  }

  if (files.length > MAX_REFERENCE_FILES) {
    return NextResponse.json({ error: "Too many files uploaded" }, { status: 413 });
  }

  var refDir = REFERENCE_DIR;
  await mkdir(refDir, { recursive: true });

  var saved = 0;
  for (var file of files) {
    if (!file.name) continue;
    if (file.size > MAX_REFERENCE_FILE_SIZE) continue;
    if (file.type && !REFERENCE_TYPES.includes(file.type)) continue;
    var buffer = Buffer.from(await file.arrayBuffer());
    var ext = path.extname(file.name) || ".bin";
    var base = path.basename(file.name, ext).replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 50);
    var safeName = base + "_" + crypto.randomBytes(4).toString("hex") + ext;
    await writeFile(path.join(refDir, safeName), buffer);
    saved++;
  }

  // Add uploaded files to the index
  var result = await runReferenceDB("add", refDir, saved);
  result.uploaded = saved;

  return NextResponse.json(result);
}
