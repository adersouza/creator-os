import { NextResponse } from "next/server";
import { extractCoverCandidates, extractCoverFrame } from "../../../../lib/reels.js";
import { isValidRunId } from "../../../../lib/paths.js";

export async function POST(request) {
  try {
    var body = await request.json();
    if (!isValidRunId(body.runId)) {
      return NextResponse.json({ error: "Invalid runId" }, { status: 400 });
    }

    if (body.auto) {
      var covers = await extractCoverCandidates({
        runId: body.runId,
        filename: body.filename,
        count: body.count || 5,
      });
      return NextResponse.json({ covers });
    }

    var cover = await extractCoverFrame({
      runId: body.runId,
      filename: body.filename,
      timestamp: body.timestamp,
    });
    return NextResponse.json(cover);
  } catch (error) {
    return NextResponse.json(
      { error: error.message || "Cover extraction failed" },
      { status: error.status || 500 }
    );
  }
}
