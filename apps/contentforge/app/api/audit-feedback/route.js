import { NextResponse } from "next/server.js";
import { appendFile, mkdir, readFile } from "fs/promises";
import path from "path";
import { PROJECT_ROOT, safeBasename } from "../../../lib/paths.js";

export const runtime = "nodejs";

var FEEDBACK_DIR = process.env.CONTENTFORGE_AUDIT_FEEDBACK_DIR ||
  path.join(PROJECT_ROOT, "test", "fixtures", "campaign-factory", "feedback");
var FEEDBACK_PATH = path.join(FEEDBACK_DIR, "operator_feedback.jsonl");
var VALID_LABELS = new Set(["useful", "false_positive", "too_strict", "missed_issue"]);

function cleanText(value, maxLength = 500) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, maxLength);
}

export async function GET() {
  try {
    var text = await readFile(FEEDBACK_PATH, "utf8").catch(function () { return ""; });
    var records = text
      .split(/\r?\n/)
      .filter(Boolean)
      .slice(-200)
      .map(function (line) {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      })
      .filter(Boolean);
    return NextResponse.json({ records });
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to read feedback" }, { status: 500 });
  }
}

export async function POST(request) {
  try {
    var body = await request.json();
    var label = cleanText(body.label, 40);
    if (!VALID_LABELS.has(label)) {
      return NextResponse.json({ error: "Invalid feedback label" }, { status: 400 });
    }
    var code = cleanText(body.code, 120);
    if (!code) {
      return NextResponse.json({ error: "Missing warning code" }, { status: 400 });
    }
    var targetFile = body.targetFile ? safeBasename(String(body.targetFile)) : null;
    var record = {
      schema: "contentforge.operator_feedback.v1",
      createdAt: new Date().toISOString(),
      targetFile,
      runId: cleanText(body.runId, 80) || null,
      auditProfile: cleanText(body.auditProfile, 80) || null,
      code,
      label,
      message: cleanText(body.message, 300),
      note: cleanText(body.note, 500),
    };
    await mkdir(FEEDBACK_DIR, { recursive: true });
    await appendFile(FEEDBACK_PATH, JSON.stringify(record) + "\n");
    return NextResponse.json({ ok: true, record });
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to save feedback" }, { status: 500 });
  }
}
