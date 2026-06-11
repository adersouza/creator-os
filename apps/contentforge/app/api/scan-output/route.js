import { NextResponse } from "next/server";
import { readdir, stat } from "fs/promises";
import path from "path";
import { resolveRunFinalDir } from "../../../lib/paths.js";

var SUPPORTED_EXTS = [".mp4", ".jpg", ".jpeg", ".png"];

export async function GET(request) {
  try {
    var url = new URL(request.url);
    var runId = url.searchParams.get("runId") || "latest";
    const finalDir = resolveRunFinalDir(runId);
    if (!finalDir) {
      return NextResponse.json({ error: "Invalid runId", files: [], count: 0 }, { status: 400 });
    }
    const entries = await readdir(finalDir);

    const files = [];
    for (const entry of entries) {
      var ext = path.extname(entry).toLowerCase();
      if (!SUPPORTED_EXTS.includes(ext)) continue;
      const filePath = path.join(finalDir, entry);
      const stats = await stat(filePath);
      files.push({
        name: entry,
        size: stats.size,
        created: stats.birthtime.toISOString(),
        type: ext === ".mp4" ? "video" : "image",
      });
    }

    files.sort((a, b) => a.name.localeCompare(b.name));

    return NextResponse.json({ files, count: files.length });
  } catch (error) {
    return NextResponse.json({ files: [], count: 0 });
  }
}
