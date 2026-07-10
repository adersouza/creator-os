import { NextResponse } from "next/server";
import { writeFile, mkdir } from "fs/promises";
import path from "path";
import crypto from "crypto";

var MAX_FILE_SIZE = Number.parseInt(process.env.CONTENTFORGE_MAX_UPLOAD_BYTES || "", 10) || 500 * 1024 * 1024; // 500MB

function sniffMedia(buffer) {
  var magic = buffer.slice(0, 16);
  if (magic.length >= 12 && magic.slice(4, 8).toString("ascii") === "ftyp") {
    var brand = magic.slice(8, 12).toString("ascii").toLowerCase();
    if (["heic", "heix", "hevc", "mif1", "msf1", "avif"].includes(brand)) return "image";
    if (["m4a ", "m4b ", "m4p "].includes(magic.slice(8, 12).toString("ascii").toLowerCase())) return "audio";
    return "video";
  }
  if (magic[0] === 0x1a && magic[1] === 0x45 && magic[2] === 0xdf && magic[3] === 0xa3) return "video";
  if (magic[0] === 0xff && magic[1] === 0xd8 && magic[2] === 0xff) return "image";
  if (magic.slice(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return "image";
  if (magic.slice(0, 4).toString("ascii") === "RIFF" && buffer.slice(8, 12).toString("ascii") === "WEBP") return "image";
  if (magic.slice(0, 3).toString("ascii") === "ID3") return "audio";
  if (magic[0] === 0xff && (magic[1] & 0xe0) === 0xe0) return "audio";
  if (magic.slice(0, 4).toString("ascii") === "RIFF" && buffer.slice(8, 12).toString("ascii") === "WAVE") return "audio";
  if (magic.slice(0, 4).toString("ascii") === "fLaC") return "audio";
  if (magic.slice(0, 4).toString("ascii") === "OggS") return "audio";
  return null;
}

export async function POST(request) {
  try {
    var contentLength = Number.parseInt(request.headers.get("content-length") || "0", 10);
    if (contentLength > MAX_FILE_SIZE) {
      return NextResponse.json(
        { error: "File too large. Maximum " + Math.round(MAX_FILE_SIZE / (1024 * 1024)) + "MB." },
        { status: 413 }
      );
    }

    var formData = await request.formData();
    var file = formData.get("file");

    if (!file) {
      return NextResponse.json({ error: "No file uploaded" }, { status: 400 });
    }

    // File size check
    if (file.size > MAX_FILE_SIZE) {
      return NextResponse.json(
        { error: "File too large. Maximum " + Math.round(MAX_FILE_SIZE / (1024 * 1024)) + "MB." },
        { status: 413 }
      );
    }

    // Validate MIME type — accept video, image, or audio replacement tracks
    var type = file.type || "";
    var isVideo = type.startsWith("video/");
    var isImage = type.startsWith("image/");
    var isAudio = type.startsWith("audio/");

    if (!isVideo && !isImage && !isAudio) {
      return NextResponse.json(
        { error: "Only video, image, or audio files accepted" },
        { status: 415 }
      );
    }

    var uploadsDir = path.join(/* turbopackIgnore: true */ process.cwd(), "uploads");
    await mkdir(uploadsDir, { recursive: true });

    var bytes = await file.arrayBuffer();
    var buffer = Buffer.from(bytes);
    var sniffedType = sniffMedia(buffer);
    if (!sniffedType || (isVideo && sniffedType !== "video") || (isImage && sniffedType !== "image") || (isAudio && sniffedType !== "audio")) {
      return NextResponse.json(
        { error: "Uploaded file does not look like a supported media file" },
        { status: 415 }
      );
    }

    // Safe filename: hash prefix + original extension (prevents collisions and traversal)
    var ext = path.extname(file.name) || (isVideo ? ".mp4" : isAudio ? ".mp3" : ".jpg");
    var baseName = path.basename(file.name, ext).replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 50);
    var hash = crypto.randomBytes(4).toString("hex");
    var safeName = baseName + "_" + hash + ext;
    var filePath = path.join(uploadsDir, safeName);

    await writeFile(filePath, buffer);

    return NextResponse.json({
      success: true,
      filename: safeName,
      path: "uploads/" + safeName,
      size: buffer.length,
      mediaType: sniffedType,
    });
  } catch {
    return NextResponse.json(
      { error: "Upload failed" },
      { status: 500 }
    );
  }
}
