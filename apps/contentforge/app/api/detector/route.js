import { NextResponse } from "next/server";
import { analyzeRunSimilarity, deleteRunFiles } from "../../../lib/detector.js";

export const runtime = "nodejs";

export async function POST(request) {
  try {
    var body = await request.json();
    if (!body.runId) return new NextResponse("Missing runId", { status: 400 });
    var result = await analyzeRunSimilarity({ runId: body.runId, threshold: body.threshold, sourceFile: body.sourceFile });
    return NextResponse.json(result);
  } catch (err) {
    return new NextResponse(err.message || "Detector failed", { status: err.status || 500 });
  }
}

export async function DELETE(request) {
  try {
    var body = await request.json();
    if (!body.runId) return new NextResponse("Missing runId", { status: 400 });
    var result = await deleteRunFiles({ runId: body.runId, files: body.files });
    return NextResponse.json(result);
  } catch (err) {
    return new NextResponse(err.message || "Delete failed", { status: err.status || 500 });
  }
}
