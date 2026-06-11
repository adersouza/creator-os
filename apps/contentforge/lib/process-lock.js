import { mkdir, open, readFile, rm } from "fs/promises";
import path from "path";
import { OUTPUT_DIR } from "./paths.js";

var LOCK_DIR = path.join(OUTPUT_DIR, ".locks");

export async function acquireProcessLock(name, { staleMs = 6 * 60 * 60 * 1000 } = {}) {
  await mkdir(LOCK_DIR, { recursive: true });
  var lockPath = path.join(LOCK_DIR, name + ".lock");
  var payload = JSON.stringify({
    pid: process.pid,
    createdAt: new Date().toISOString(),
  });

  try {
    var handle = await open(lockPath, "wx");
    await handle.writeFile(payload);
    await handle.close();
    return {
      acquired: true,
      path: lockPath,
      async release() {
        await rm(lockPath, { force: true });
      },
    };
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
  }

  var existing = null;
  try {
    existing = JSON.parse(await readFile(lockPath, "utf8"));
  } catch {
    existing = null;
  }
  var createdAt = existing?.createdAt ? Date.parse(existing.createdAt) : 0;
  var stale = !createdAt || Date.now() - createdAt > staleMs;
  if (stale) {
    await rm(lockPath, { force: true });
    return acquireProcessLock(name, { staleMs });
  }

  return {
    acquired: false,
    path: lockPath,
    existing,
    async release() {},
  };
}
