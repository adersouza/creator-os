import { existsSync } from "fs";
import { NextResponse } from "next/server";
import { runVariantPack } from "../../../lib/variant-pack.js";
import { resolveUploadPath } from "../../../lib/paths.js";
import { acquireProcessLock } from "../../../lib/process-lock.js";

export const runtime = "nodejs";

export async function POST(request) {
  var body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }
  var source = body.source || body.inputFile;
  var sourcePath = resolveUploadPath(source);
  if (!sourcePath || !existsSync(sourcePath)) {
    return NextResponse.json({ error: "Source upload not found" }, { status: 404 });
  }
  var lock = await acquireProcessLock("forge");
  if (!lock.acquired) {
    return NextResponse.json({ error: "A forge run is already active" }, { status: 429 });
  }
  var released = false;
  async function releaseLock() {
    if (released) return;
    released = true;
    await lock.release();
  }
  request.signal?.addEventListener("abort", () => {
    releaseLock().catch(() => {});
  }, { once: true });
  try {
    var report = await runVariantPack(body);
    return NextResponse.json(report);
  } catch (err) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  } finally {
    await releaseLock();
  }
}
