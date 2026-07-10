import { NextResponse } from "next/server";
import path from "path";
import { existsSync } from "fs";
import { mkdir } from "fs/promises";
import { extractThumbnail, extractImageThumbnail, getVideoInfo, getImageInfo } from "../../../lib/pipeline.js";
import { resolveUploadPath, safeBasename } from "../../../lib/paths.js";

var IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp", ".heic"];

export async function POST(request) {
  try {
    var body = await request.json();
    var filename = body.filename;

    if (!filename || typeof filename !== "string") {
      return NextResponse.json({ error: "No filename" }, { status: 400 });
    }

    // Path traversal protection — strip to basename only
    var safeName = safeBasename(filename);
    var inputPath = resolveUploadPath(safeName);
    if (!safeName || !inputPath) {
      return NextResponse.json({ error: "Invalid filename" }, { status: 400 });
    }

    if (!existsSync(inputPath)) {
      return NextResponse.json({ error: "File not found" }, { status: 404 });
    }

    var thumbDir = path.join(process.cwd(), "public", "thumbnails");
    await mkdir(thumbDir, { recursive: true });

    var ext = path.extname(safeName).toLowerCase();
    var isImage = IMAGE_EXTS.includes(ext);

    var thumbName = "thumb_" + safeName.replace(/\.[^.]+$/, "") + ".jpg";
    var thumbPath = path.join(thumbDir, thumbName);

    if (isImage) {
      // Image: resize to thumbnail + get dimensions
      var results = await Promise.allSettled([
        extractImageThumbnail(inputPath, thumbPath),
        getImageInfo(inputPath),
      ]);

      var info = results[1].status === "fulfilled" ? results[1].value : {};

      return NextResponse.json({
        success: true,
        thumbnail: "/thumbnails/" + thumbName,
        mediaType: "image",
        info: {
          width: info.width || 0,
          height: info.height || 0,
          codec: info.codec || "unknown",
          size: info.size || 0,
          format: info.format || "unknown",
        },
      });
    } else {
      // Video: extract frame + get metadata
      var results = await Promise.all([
        extractThumbnail(inputPath, thumbPath),
        getVideoInfo(inputPath),
      ]);
      var videoInfo = results[1];

      return NextResponse.json({
        success: true,
        thumbnail: "/thumbnails/" + thumbName,
        mediaType: "video",
        info: {
          duration: videoInfo.duration,
          width: videoInfo.width,
          height: videoInfo.height,
          codec: videoInfo.codec,
          size: videoInfo.size,
          bitrate: videoInfo.bitrate,
          hasAudio: videoInfo.hasAudio,
        },
      });
    }
  } catch {
    return NextResponse.json(
      { error: "Thumbnail extraction failed" },
      { status: 500 }
    );
  }
}
