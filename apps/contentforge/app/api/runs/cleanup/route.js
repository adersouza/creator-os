import { NextResponse } from "next/server";
import { cleanupOldFiles } from "../../../../lib/reels.js";

export const runtime = "nodejs";

export async function POST(request) {
  try {
    var body = await request.json();
    var result = await cleanupOldFiles({
      olderThanDays: body.olderThanDays || 14,
      maxBytes: body.maxBytes,
    });
    return NextResponse.json(result);
  } catch (err) {
    return new NextResponse(err.message || "Cleanup failed", { status: err.status || 500 });
  }
}
