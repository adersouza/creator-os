import { NextResponse } from "next/server.js";
import { applyLocalMediaCleanup, inspectLocalMediaCleanup } from "../../../../lib/local-media-cleanup.js";

export const runtime = "nodejs";

function optionsFromUrl(url) {
  return {
    olderThanDays: Number.parseFloat(url.searchParams.get("olderThanDays") || "14"),
    maxBytes: Number.parseInt(url.searchParams.get("maxBytes") || "0", 10) || 0,
  };
}

export async function GET(request) {
  try {
    var url = new URL(request.url);
    return NextResponse.json(await inspectLocalMediaCleanup(optionsFromUrl(url)));
  } catch (error) {
    return NextResponse.json({ error: error.message || "Cleanup inspection failed" }, { status: 500 });
  }
}

export async function POST(request) {
  try {
    var body = await request.json().catch(function () { return {}; });
    var options = {
      olderThanDays: Number.parseFloat(body.olderThanDays || 14),
      maxBytes: Number.parseInt(body.maxBytes || 0, 10) || 0,
    };
    if (body.confirm !== true) {
      return NextResponse.json({ error: "Cleanup requires confirm: true" }, { status: 400 });
    }
    return NextResponse.json(await applyLocalMediaCleanup(options));
  } catch (error) {
    return NextResponse.json({ error: error.message || "Cleanup failed" }, { status: 500 });
  }
}
