import { NextResponse } from "next/server";
import { convertMedia } from "../../../../lib/media-tools.js";

export const runtime = "nodejs";

export async function POST(request) {
  try {
    var body = await request.json();
    var result = await convertMedia(body);
    return NextResponse.json(result);
  } catch (err) {
    return new NextResponse(err.message || "Conversion failed", { status: err.status || 500 });
  }
}
