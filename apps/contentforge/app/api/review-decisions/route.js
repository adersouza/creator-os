import { NextResponse } from "next/server.js";
import { loadReviewDecisions, recordReviewDecision } from "../../../lib/review-decisions.js";

export const runtime = "nodejs";

export async function GET(request) {
  try {
    var url = new URL(request.url);
    var runId = url.searchParams.get("runId") || "latest";
    var payload = await loadReviewDecisions(runId);
    if (url.searchParams.get("format") === "approved-manifest") {
      return NextResponse.json(payload.approvedManifest);
    }
    return NextResponse.json(payload);
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to read review decisions" }, { status: error.status || 400 });
  }
}

export async function POST(request) {
  try {
    var body = await request.json();
    var payload = await recordReviewDecision(body);
    return NextResponse.json(payload);
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to save review decision" }, { status: error.status || 400 });
  }
}
