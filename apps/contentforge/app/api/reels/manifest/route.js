import { NextResponse } from "next/server";
import { existsSync } from "fs";
import { readFile } from "fs/promises";
import path from "path";
import { resolveRunFinalDir } from "../../../../lib/paths.js";
import { formatManifestCsv } from "../../../../lib/reels.js";

export const runtime = "nodejs";

export async function GET(request) {
  var url = new URL(request.url);
  var runId = url.searchParams.get("runId");
  var format = url.searchParams.get("format") || "json";
  if (!runId) return new NextResponse("Missing runId", { status: 400 });

  var finalDir = resolveRunFinalDir(runId);
  if (!finalDir) return new NextResponse("Invalid runId", { status: 400 });

  var manifestPath = path.join(finalDir, "reels_manifest.json");
  if (!existsSync(manifestPath)) return new NextResponse("Manifest not found", { status: 404 });

  var manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  if (format === "csv") {
    var csv = formatManifestCsv(manifest);
    return new NextResponse(csv, {
      headers: {
        "Content-Type": "text/csv",
        "Content-Disposition": "attachment; filename=\"contentforge_manifest_" + runId + ".csv\"",
      },
    });
  }

  return NextResponse.json(manifest);
}
