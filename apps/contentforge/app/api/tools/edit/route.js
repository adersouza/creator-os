import { NextResponse } from "next/server";
import { editMedia } from "../../../../lib/media-tools.js";

export const runtime = "nodejs";

export async function POST(request) {
  try {
    var body = await request.json();
    var result = await editMedia(body);
    return NextResponse.json(result);
  } catch (err) {
    return new NextResponse(err.message || "Edit failed", { status: err.status || 500 });
  }
}
