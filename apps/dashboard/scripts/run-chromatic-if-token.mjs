#!/usr/bin/env node
import { spawnSync } from "node:child_process";

if (!process.env.CHROMATIC_PROJECT_TOKEN) {
	console.log("Skipping Chromatic: CHROMATIC_PROJECT_TOKEN is not set.");
	process.exit(0);
}

const result = spawnSync(
	"npx",
	[
		"chromatic",
		"--project-token",
		process.env.CHROMATIC_PROJECT_TOKEN,
		"--exit-zero-on-changes",
	],
	{ stdio: "inherit" },
);

process.exit(result.status ?? 1);
