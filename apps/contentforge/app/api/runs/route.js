import { NextResponse } from "next/server";
import { cleanupOldFiles, deleteRun, listRuns } from "../../../lib/reels.js";
import { isValidRunId } from "../../../lib/paths.js";

export async function GET() {
  try {
    return NextResponse.json({ runs: await listRuns() });
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to list runs" }, { status: 500 });
  }
}

export async function POST(request) {
  try {
    var body = await request.json().catch(function () { return {}; });
    var olderThanDays = Math.max(1, Math.min(parseInt(body.olderThanDays || 14, 10), 365));
    var maxBytes = body.maxBytes ? Math.max(0, parseInt(body.maxBytes, 10) || 0) : 0;
    return NextResponse.json(await cleanupOldFiles({ olderThanDays, maxBytes }));
  } catch (error) {
    return NextResponse.json({ error: error.message || "Cleanup failed" }, { status: 500 });
  }
}

export async function DELETE(request) {
  try {
    var url = new URL(request.url);
    var runId = url.searchParams.get("runId");
    if (!isValidRunId(runId)) {
      return NextResponse.json({ error: "Invalid runId" }, { status: 400 });
    }
    return NextResponse.json(await deleteRun(runId));
  } catch (error) {
    return NextResponse.json(
      { error: error.message || "Delete failed" },
      { status: error.status || 500 }
    );
  }
}
