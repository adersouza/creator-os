// Prepare sibling source repos for the mirror parity gate in CI.
//
// Local development already has ../ThreadsDashboard, ../campaign_factory, etc.
// GitHub Actions checks out only creator-os, so this script clones each source
// repo beside the checkout and pins it to mirror-sources.json sourceCommit.

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const cfg = JSON.parse(readFileSync(join(REPO_ROOT, "mirror-sources.json"), "utf8"));
const token = process.env.MIRROR_SYNC_TOKEN || "";

if (!(cfg.mirrors || []).length) {
  console.log("No committed mirrors configured; no source repos to prepare.");
  process.exit(0);
}

function authedUrl(url) {
  if (!token || !url.startsWith("https://github.com/")) return url;
  return url.replace("https://github.com/", `https://x-access-token:${token}@github.com/`);
}

function git(args, options = {}) {
  return execFileSync("git", args, {
    cwd: REPO_ROOT,
    encoding: "utf8",
    stdio: options.stdio || "pipe",
    maxBuffer: 64 * 1024 * 1024,
  });
}

for (const mirror of cfg.mirrors || []) {
  const repoPath = resolve(REPO_ROOT, mirror.sourceRepoPath);
  let shouldPin = process.env.CI === "true";
  if (existsSync(join(repoPath, ".git"))) {
    console.log(`source present: ${mirror.sourceRepoPath}`);
    if (!shouldPin) continue;
  } else {
    if (!mirror.sourceRepoUrl) {
      throw new Error(`Missing sourceRepoUrl for ${mirror.mirrorPath}`);
    }
    rmSync(repoPath, { recursive: true, force: true });
    console.log(`clone source: ${mirror.sourceRepoPath} @ ${mirror.sourceCommit.slice(0, 8)}`);
    git(["clone", "--no-checkout", "--filter=blob:none", authedUrl(mirror.sourceRepoUrl), repoPath], {
      stdio: "ignore",
    });
    shouldPin = true;
  }
  if (!shouldPin) continue;
  execFileSync("git", ["fetch", "--depth=1", "origin", mirror.sourceCommit], {
    cwd: repoPath,
    stdio: "ignore",
  });
  execFileSync("git", ["checkout", "--detach", mirror.sourceCommit], {
    cwd: repoPath,
    stdio: "ignore",
  });
}
