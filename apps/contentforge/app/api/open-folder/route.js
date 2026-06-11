import { execFile } from "child_process";
import { NextResponse } from "next/server";
import { resolveRunFinalDir } from "../../../lib/paths.js";

export async function POST(request) {
  var body = await request.json().catch(function () { return {}; });
  var finalDir = resolveRunFinalDir(body.runId || "latest");
  if (!finalDir) {
    return NextResponse.json({ error: "Invalid runId" }, { status: 400 });
  }

  return new Promise(function (resolve) {
    // execFile (not exec) — no shell interpolation, prevents command injection
    execFile("open", [finalDir], function (error) {
      if (error) {
        resolve(NextResponse.json({ error: "Could not open folder" }, { status: 500 }));
      } else {
        resolve(NextResponse.json({ success: true }));
      }
    });
  });
}
