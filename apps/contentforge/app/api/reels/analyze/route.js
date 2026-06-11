import { NextResponse } from "next/server";
import { analyzeReelsRun, REELS_PROFILES } from "../../../../lib/reels.js";
import { isValidRunId } from "../../../../lib/paths.js";

export async function POST(request) {
  try {
    var body = await request.json();
    var runId = body.runId;
    var profileId = body.profileId || "organic";

    if (!isValidRunId(runId)) {
      return NextResponse.json({ error: "Invalid runId" }, { status: 400 });
    }
    if (!REELS_PROFILES[profileId]) {
      return NextResponse.json({ error: "Invalid profileId" }, { status: 400 });
    }

    var result = await analyzeReelsRun({ runId, profileId, sourceFile: body.sourceFile });
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { error: error.message || "Analyze failed" },
      { status: error.status || 500 }
    );
  }
}
