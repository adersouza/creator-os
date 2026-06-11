import { NextResponse } from "next/server";
import { exportGif } from "../../../../lib/media-tools.js";

export const runtime = "nodejs";

export async function POST(request) {
  try {
    var body = await request.json();
    var result = await exportGif(body);
    return NextResponse.json(result);
  } catch (err) {
    return new NextResponse(err.message || "GIF export failed", { status: err.status || 500 });
  }
}
