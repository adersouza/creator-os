#!/usr/bin/env node

import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { get } from "node:https";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const vendoredRoot = join(root, "pipeline_contracts");
const localContractsRoot = resolve(root, "..", "..", "packages", "pipeline_contracts");
const remoteBase =
	"https://raw.githubusercontent.com/adersouza/creator-os/main/packages/pipeline_contracts";

const files = [
	"schemas/audio_catalog_export.v1.example.json",
	"schemas/audio_catalog_export.v1.schema.json",
	"schemas/audio_intent.v1.example.json",
	"schemas/audio_intent.v1.schema.json",
	"schemas/campaign_draft_payload.v1.example.json",
	"schemas/campaign_draft_payload.v1.schema.json",
	"schemas/creative_plan.v1.example.json",
	"schemas/creative_plan.v1.schema.json",
	"schemas/generated_asset_lineage.v1.example.json",
	"schemas/generated_asset_lineage.v1.schema.json",
	"schemas/higgsfield_soul_image_prompt.v1.example.json",
	"schemas/higgsfield_soul_image_prompt.v1.schema.json",
	"schemas/kling_3_video_prompt.v1.example.json",
	"schemas/kling_3_video_prompt.v1.schema.json",
	"schemas/pattern_card.v1.example.json",
	"schemas/pattern_card.v1.schema.json",
	"schemas/performance_sync.v1.example.json",
	"schemas/performance_sync.v1.schema.json",
	"schemas/recommendation_accuracy_report.v1.example.json",
	"schemas/recommendation_accuracy_report.v1.schema.json",
	"schemas/recommendation_next_batch.v1.example.json",
	"schemas/recommendation_next_batch.v1.schema.json",
	"schemas/repurposing_plan.v1.example.json",
	"schemas/repurposing_plan.v1.schema.json",
	"schemas/video_analysis.v1.example.json",
	"schemas/video_analysis.v1.schema.json",
	["typescript/index.ts", "typescript.ts"],
];

function readVendored(path) {
	return readFileSync(join(vendoredRoot, path), "utf8");
}

function readCanonicalLocal(path) {
	return readFileSync(join(localContractsRoot, path), "utf8");
}

function readUrl(url) {
	return new Promise((resolvePromise, reject) => {
		get(url, (response) => {
			if (response.statusCode !== 200) {
				response.resume();
				reject(new Error(`HTTP ${response.statusCode} for ${url}`));
				return;
			}
			let body = "";
			response.setEncoding("utf8");
			response.on("data", (chunk) => {
				body += chunk;
			});
			response.on("end", () => resolvePromise(body));
		}).on("error", reject);
	});
}

const useLocal = existsSync(localContractsRoot);
const mismatches = [];

for (const entry of files) {
	const canonicalPath = Array.isArray(entry) ? entry[0] : entry;
	const vendoredPath = Array.isArray(entry) ? entry[1] : entry;
	const canonical = useLocal
		? readCanonicalLocal(canonicalPath)
		: await readUrl(`${remoteBase}/${canonicalPath}`);
	const vendored = readVendored(vendoredPath);
	if (canonical !== vendored) {
		mismatches.push(`${vendoredPath} differs from pipeline_contracts/${canonicalPath}`);
	}
}

if (mismatches.length > 0) {
	console.error("ERROR: ThreadsDashboard pipeline_contracts snapshot is stale.");
	console.error("Sync from ../../packages/pipeline_contracts or from:");
	console.error("https://github.com/adersouza/creator-os/tree/main/packages/pipeline_contracts");
	for (const mismatch of mismatches) console.error(`- ${mismatch}`);
	process.exit(1);
}

console.log(`Pipeline contracts snapshot is in sync with ${useLocal ? "creator-os package" : "GitHub main"}.`);
