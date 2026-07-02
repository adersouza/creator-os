import { createReadStream, existsSync, statSync } from "node:fs";
import { Readable } from "node:stream";
import path from "node:path";
import { NextResponse } from "next/server";
import { authorizeApiRequest } from "../../../../../lib/auth.js";
import { getInboxAsset } from "../../../../../lib/inbox.js";

export const dynamic = "force-dynamic";

var CONTENT_TYPES = {
  ".mp4": "video/mp4",
  ".mov": "video/quicktime",
  ".webm": "video/webm",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
};

// Serves the asset's own output_path (from the state table, never from the
// request), so there is no client-controlled path to traverse.
export async function GET(request, { params }) {
  var auth = authorizeApiRequest(request);
  if (!auth.ok) return NextResponse.json({ reason: auth.reason }, { status: auth.status });
  var { assetId } = await params;
  var asset = getInboxAsset(assetId);
  if (!asset || !asset.outputPath || !existsSync(asset.outputPath)) {
    return NextResponse.json({ reason: "media_not_found" }, { status: 404 });
  }
  var type = CONTENT_TYPES[path.extname(asset.outputPath).toLowerCase()];
  if (!type) return NextResponse.json({ reason: "unsupported_media_type" }, { status: 415 });
  var size = statSync(asset.outputPath).size;
  // ponytail: whole-file response, no Range support — local single-operator
  // preview; add Range parsing if seeking long reels ever matters.
  return new Response(Readable.toWeb(createReadStream(asset.outputPath)), {
    headers: { "content-type": type, "content-length": String(size) },
  });
}
