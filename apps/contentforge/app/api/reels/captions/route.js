import { NextResponse } from "next/server";
import { saveRunCaptions } from "../../../../lib/reels.js";
import { isValidRunId } from "../../../../lib/paths.js";

export const runtime = "nodejs";

export async function POST(request) {
  try {
    var form = await request.formData();
    var runId = String(form.get("runId") || "");
    var file = form.get("file");
    if (!isValidRunId(runId)) {
      return NextResponse.json({ error: "Invalid runId" }, { status: 400 });
    }
    if (!file || typeof file.text !== "function") {
      return NextResponse.json({ error: "Missing SRT file" }, { status: 400 });
    }
    var text = await file.text();
    var result = await saveRunCaptions({ runId, text });
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { error: error.message || "Caption upload failed" },
      { status: error.status || 500 }
    );
  }
}
