import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const root = path.resolve(path.dirname(__filename), "..");

const manifestSource = fs.readFileSync(path.join(root, "mcp-server/src/operatorControlPlane.ts"), "utf8");
const manifestDoc = fs.readFileSync(path.join(root, "docs/OPERATOR_ACTION_MANIFEST.md"), "utf8");
const apiReference = fs.readFileSync(path.join(root, "docs/API_REFERENCE.md"), "utf8");

const requiredFields = [
	"toolName",
	"riskLevel",
	"sideEffectType",
	"requiresApproval",
	"requiresIdempotencyKey",
	"supportsDryRun",
	"hostedAvailable",
	"rollbackSupport",
	"compensationActionName",
	"compensationDescription",
	"compensationRequiresApproval",
	"rollbackWindowHours",
];

const writeToolsMatch = manifestSource.match(/export const WRITE_TOOLS = new Set\(\[([\s\S]*?)\]\);/);
if (!writeToolsMatch) {
	throw new Error("Could not locate WRITE_TOOLS in operator control plane source");
}
const sourceToolNames = new Set([...writeToolsMatch[1].matchAll(/"([a-z][a-z0-9_]+)"/g)].map((match) => match[1]));

const documentedExamples = new Set([...manifestDoc.matchAll(/`([a-z][a-z0-9_]+)`/g)].map((match) => match[1]));
const missingFields = requiredFields.filter((field) => !manifestDoc.includes(`\`${field}\``) || !apiReference.includes(field));
if (missingFields.length) {
	throw new Error(`Operator docs are missing manifest fields: ${missingFields.join(", ")}`);
}

for (const phrase of [
	"GET /api/operator?action=manifest",
	"dry-run",
	"exact approval",
	"idempotency",
	"rollback/compensation",
	"source-workflow",
]) {
	if (!manifestDoc.includes(phrase) && !apiReference.includes(phrase)) {
		throw new Error(`Operator docs are missing required phrase: ${phrase}`);
	}
}

const missingExamples = [...sourceToolNames].filter((action) => !documentedExamples.has(action));
if (missingExamples.length) {
	throw new Error(`Operator manifest docs are missing canonical actions: ${missingExamples.join(", ")}`);
}

console.log("Operator docs match the canonical manifest contract.");
