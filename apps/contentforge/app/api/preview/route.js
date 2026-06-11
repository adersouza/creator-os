import { NextResponse } from "next/server";
import { stat } from "fs/promises";
import { createReadStream, existsSync } from "fs";
import path from "path";
import { Readable } from "stream";
import { resolveRunFile, safeBasename } from "../../../lib/paths.js";

function getContentType(filename) {
  var ext = path.extname(filename).toLowerCase();
  if (ext === ".mp4") return "video/mp4";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  if (ext === ".gif") return "image/gif";
  return "application/octet-stream";
}

// Serve files for in-browser preview (video + image)
export async function GET(request) {
  var url = new URL(request.url);
  var filename = url.searchParams.get("file");
  var runId = url.searchParams.get("runId") || "latest";

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
  var contentType = getContentType(safeName);
  var isVideo = contentType.startsWith("video/");

  // Support range requests for video seeking
  if (isVideo) {
    var range = request.headers.get("range");
    if (range) {
      var match = range.match(/^bytes=(\d*)-(\d*)$/);
      if (!match || (!match[1] && !match[2])) {
        return new NextResponse("Invalid range", {
          status: 416,
          headers: { "Content-Range": "bytes */" + fileStats.size },
        });
      }

      var parts = [match[1], match[2]];
      var start = parseInt(parts[0], 10);
      var end = parts[1] ? parseInt(parts[1], 10) : fileStats.size - 1;
      if (Number.isNaN(start)) {
        var suffixLength = parseInt(parts[1], 10);
        start = Math.max(fileStats.size - suffixLength, 0);
        end = fileStats.size - 1;
      }
      if (Number.isNaN(end) || start < 0 || end < start || start >= fileStats.size) {
        return new NextResponse("Invalid range", {
          status: 416,
          headers: { "Content-Range": "bytes */" + fileStats.size },
        });
      }
      end = Math.min(end, fileStats.size - 1);
      var chunkSize = end - start + 1;
      var buffer = Buffer.alloc(chunkSize);

      var { open } = await import("fs/promises");
      var fh = await open(filePath, "r");
      await fh.read(buffer, 0, chunkSize, start);
      await fh.close();

      return new NextResponse(buffer, {
        status: 206,
        headers: {
          "Content-Range": "bytes " + start + "-" + end + "/" + fileStats.size,
          "Accept-Ranges": "bytes",
          "Content-Length": String(chunkSize),
          "Content-Type": contentType,
        },
      });
    }
  }

  var stream = createReadStream(filePath);
  return new NextResponse(Readable.toWeb(stream), {
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(fileStats.size),
      ...(isVideo ? { "Accept-Ranges": "bytes" } : {}),
      "Cache-Control": "public, max-age=3600",
    },
  });
}
