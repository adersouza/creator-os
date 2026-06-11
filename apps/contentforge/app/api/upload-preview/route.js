import { NextResponse } from "next/server";
import { stat } from "fs/promises";
import { createReadStream, existsSync } from "fs";
import path from "path";
import { Readable } from "stream";
import { resolveUploadPath, safeBasename } from "../../../lib/paths.js";

function getContentType(filename) {
  var ext = path.extname(filename).toLowerCase();
  if (ext === ".mp4") return "video/mp4";
  if (ext === ".mov") return "video/quicktime";
  if (ext === ".webm") return "video/webm";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  return "application/octet-stream";
}

export async function GET(request) {
  var url = new URL(request.url);
  var file = url.searchParams.get("file");
  var safeName = safeBasename(String(file || "").replace(/^uploads\//, ""));
  var filePath = resolveUploadPath(safeName || "");
  if (!safeName || !filePath) return new NextResponse("Invalid file", { status: 400 });
  if (!existsSync(filePath)) return new NextResponse("Not found", { status: 404 });

  var fileStats = await stat(filePath);
  var contentType = getContentType(safeName);
  var stream = createReadStream(filePath);
  return new NextResponse(Readable.toWeb(stream), {
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(fileStats.size),
      "Cache-Control": "public, max-age=3600",
    },
  });
}
