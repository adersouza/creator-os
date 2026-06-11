import { existsSync } from "fs";
import { NextResponse } from "next/server";
import { resolveUploadPath } from "../../../../lib/paths.js";
import { startVariantPackJob } from "../../../../lib/variant-pack-jobs.js";

export const runtime = "nodejs";

export async function POST(request) {
  var body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }
  var source = body.source || body.inputFile;
  var sourcePath = resolveUploadPath(source);
  if (!sourcePath || !existsSync(sourcePath)) {
    return NextResponse.json({ error: "Source upload not found" }, { status: 404 });
  }
  var job = await startVariantPackJob(body);
  return NextResponse.json(job, { status: 202 });
}
