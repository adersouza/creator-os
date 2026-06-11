import { NextResponse } from "next/server";
import { generateFrames } from "../../../../lib/media-tools.js";

export const runtime = "nodejs";

export async function POST(request) {
  try {
    var body = await request.json();
    var result = await generateFrames(body);
    return NextResponse.json(result);
  } catch (err) {
    return new NextResponse(err.message || "Frame generation failed", { status: err.status || 500 });
  }
}
