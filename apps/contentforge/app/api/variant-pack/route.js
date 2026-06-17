import { existsSync } from "fs";
import { runVariantPack } from "../../../lib/variant-pack.js";
import { resolveUploadPath } from "../../../lib/paths.js";
import { acquireProcessLock } from "../../../lib/process-lock.js";

export const runtime = "nodejs";

export function createVariantPackPostHandler(deps = {}) {
  var acquireProcessLockImpl = deps.acquireProcessLockImpl || acquireProcessLock;
  var existsSyncImpl = deps.existsSyncImpl || existsSync;
  var runVariantPackImpl = deps.runVariantPackImpl || runVariantPack;

  return async function POST(request) {
    var body;
    try {
      body = await request.json();
    } catch {
      return Response.json({ error: "Invalid JSON" }, { status: 400 });
    }
    var source = body.source || body.inputFile;
    var sourcePath = resolveUploadPath(source);
    if (!sourcePath || !existsSyncImpl(sourcePath)) {
      return Response.json({ error: "Source upload not found" }, { status: 404 });
    }
    var lock = await acquireProcessLockImpl("forge");
    if (!lock.acquired) {
      return Response.json({ error: "A forge run is already active" }, { status: 429 });
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
      var report = await runVariantPackImpl(body);
      return Response.json(report);
    } catch (err) {
      return Response.json({ error: err.message }, { status: 500 });
    } finally {
      await releaseLock();
    }
  };
}

export const POST = createVariantPackPostHandler();
