import { NextResponse } from "next/server";
import { generateClips } from "../../../../lib/media-tools.js";

export const runtime = "nodejs";

export async function POST(request) {
  try {
    var body = await request.json();
    var result = await generateClips(body);
    return NextResponse.json(result);
  } catch (err) {
    return new NextResponse(err.message || "Clip generation failed", { status: err.status || 500 });
  }
}
